"""Amplitude: one event per agent step (fire-and-forget; never blocks a flow).

Mock: appends to data/events.jsonl so the success/approval/failure funnel can still be shown.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, Optional

import httpx

from backend.config import DATA_DIR, mode, settings

EVENTS = {"task_detected", "user_notified", "user_approved", "policy_retrieved", "decision_made", "return_filed",
          "adjustment_filed", "claim_filed", "order_placed", "verified", "refund_received", "failed"}


def _send_real(event: Dict[str, Any]) -> None:
    httpx.post("https://api2.amplitude.com/2/httpapi", timeout=10,
               json={"api_key": settings.amplitude_api_key, "events": [event]}).raise_for_status()


def _send_mock(event: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(DATA_DIR / "events.jsonl", "a") as f:
        f.write(json.dumps(event) + "\n")


def track(event_type: str, props: Optional[Dict[str, Any]] = None, user_id: str = "u_001") -> None:
    event = {"user_id": user_id, "event_type": event_type, "event_properties": props or {},
             "time": int(time.time() * 1000)}

    def run():
        try:
            if mode("amplitude") == "real":
                _send_real(event)
                return
        except Exception as e:
            event["event_properties"]["_amplitude_error"] = str(e)[:200]
        _send_mock(event)

    threading.Thread(target=run, daemon=True).start()
