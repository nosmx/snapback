"""Statsig: `replacement_strategy` experiment (same_item vs best_rated).

The user's mandate is authoritative; the variant is always logged, and applied only when the
mandate's strategy is `experiment` (see NOTES.md).
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, Tuple

import httpx

from backend.config import settings
from backend.integrations.base import call

VARIANTS = ["same_item", "best_rated"]


def _real(user_id: str, name: str) -> Dict[str, Any]:
    r = httpx.post("https://statsigapi.net/v1/get_config", timeout=10,
                   headers={"statsig-api-key": settings.statsig_server_secret},
                   json={"user": {"userID": user_id}, "configName": name})
    r.raise_for_status()
    body = r.json()
    value = body.get("value") or {}
    configured = bool(value) or body.get("rule_id") is not None
    # Unconfigured experiment: Statsig returns {} with rule_id null. Record that honestly.
    return {"variant": value.get("strategy") or value.get("variant") or "same_item",
            "rule_id": body.get("rule_id"), "group": body.get("group_name") or ("" if configured else "not_configured"),
            "configured": configured}


def _mock(user_id: str, name: str) -> Dict[str, Any]:
    h = int(hashlib.sha256(f"{name}:{user_id}".encode()).hexdigest(), 16)
    return {"variant": VARIANTS[h % 2], "rule_id": "mock_rule", "group": "mock", "configured": True}


def variant(user_id: str = "u_001", name: str = "replacement_strategy") -> Tuple[Dict[str, Any], Dict[str, Any]]:
    return call("statsig", lambda: _real(user_id, name), lambda: _mock(user_id, name))
