"""Shared mock-fallback plumbing for sponsor integrations.

Each call returns (result, meta). meta is written into the audit log so a mock answer is
always labeled as one: {"provider", "mode", "degraded", "error", "latency_ms"}.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, Tuple

from backend.config import mode

log = logging.getLogger("snapback.integrations")


def call(provider: str, real_fn: Callable[[], Any], mock_fn: Callable[[], Any]) -> Tuple[Any, Dict[str, Any]]:
    t0 = time.time()
    if mode(provider) == "real":
        try:
            result = real_fn()
            return result, {"provider": provider, "mode": "real", "degraded": False, "error": None,
                            "latency_ms": int((time.time() - t0) * 1000)}
        except Exception as e:  # never let a sponsor failure block the demo
            log.warning("%s real call failed, using mock: %s", provider, e)
            result = mock_fn()
            return result, {"provider": provider, "mode": "mock", "degraded": True, "error": str(e)[:300],
                            "latency_ms": int((time.time() - t0) * 1000)}
    result = mock_fn()
    return result, {"provider": provider, "mode": "mock", "degraded": False, "error": None,
                    "latency_ms": int((time.time() - t0) * 1000)}


def model_label(meta: Dict[str, Any], real_model: str) -> str:
    return real_model if meta["mode"] == "real" else f"mock:{meta['provider']}"
