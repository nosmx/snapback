"""Persona: verify the human behind the mandate and each one-tap approval.

Real: Persona inquiries API (JSON:API). The frontend runs the embedded flow with the
returned inquiry id + session token; the backend confirms status before acting.
Mock: an `inq_mock_*` inquiry that completes immediately (labeled mock in the audit log).
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, Optional, Tuple

import httpx

from backend.config import settings
from backend.integrations.base import call

API = "https://withpersona.com/api/v1"


def _headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {settings.persona_api_key}", "Persona-Version": "2023-01-05",
            "Content-Type": "application/json", "Accept": "application/json"}


def _real_start(reference_id: str, purpose: str) -> Dict[str, Any]:
    template = settings.persona_template_id_mandate if purpose == "mandate" else (
        settings.persona_template_id_approval or settings.persona_template_id_mandate)
    if not template:
        raise RuntimeError("PERSONA_TEMPLATE_ID_* not set")
    r = httpx.post(f"{API}/inquiries", headers=_headers(), timeout=15, json={
        "data": {"attributes": {"inquiry-template-id": template, "reference-id": reference_id,
                                "note": f"snapback:{purpose}"}}})
    r.raise_for_status()
    data = r.json()["data"]
    inquiry_id = data["id"]
    token = None
    try:
        s = httpx.post(f"{API}/inquiries/{inquiry_id}/resume", headers=_headers(), timeout=15)
        s.raise_for_status()
        token = s.json().get("meta", {}).get("session-token")
    except Exception:
        pass
    return {"inquiry_id": inquiry_id, "status": data["attributes"].get("status"), "session_token": token,
            "environment_id": settings.persona_environment_id, "template_id": template}


def _real_status(inquiry_id: str) -> str:
    r = httpx.get(f"{API}/inquiries/{inquiry_id}", headers=_headers(), timeout=15)
    r.raise_for_status()
    return r.json()["data"]["attributes"]["status"]


def start_inquiry(reference_id: str, purpose: str = "approval") -> Tuple[Dict[str, Any], Dict[str, Any]]:
    return call("persona", lambda: _real_start(reference_id, purpose),
                lambda: {"inquiry_id": f"inq_mock_{uuid.uuid4().hex[:12]}", "status": "pending",
                         "session_token": None, "environment_id": None, "template_id": None})


def status(inquiry_id: str) -> Tuple[str, Dict[str, Any]]:
    if inquiry_id.startswith("inq_mock_"):
        return "approved", {"provider": "persona", "mode": "mock", "degraded": False, "error": None, "latency_ms": 0}
    return call("persona", lambda: _real_status(inquiry_id), lambda: "approved")


def is_verified(inquiry_id: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
    if not inquiry_id:
        return False, {"provider": "persona", "mode": "none", "degraded": False, "error": "no inquiry", "latency_ms": 0}
    st, meta = status(inquiry_id)
    return st in ("completed", "approved"), meta
