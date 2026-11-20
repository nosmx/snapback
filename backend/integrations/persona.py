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

API = "https://api.withpersona.com/api/v1"   # per docs.withpersona.com "Creating inquiries"


def _headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {settings.persona_api_key}", "Persona-Version": "2023-01-05",
            "Content-Type": "application/json", "Accept": "application/json"}


def _real_start(reference_id: str, purpose: str) -> Dict[str, Any]:
    """POST /api/v1/inquiries with an itmpl_ template (required). meta.auto-create-inquiry-session
    returns a session token the embedded client can resume with."""
    template = settings.persona_template_id_mandate if purpose == "mandate" else (
        settings.persona_template_id_approval or settings.persona_template_id_mandate)
    if not template:
        raise RuntimeError("PERSONA_TEMPLATE_ID_* not set (an inquiry cannot be created without a template)")
    r = httpx.post(f"{API}/inquiries", headers=_headers(), timeout=15, json={
        "data": {"attributes": {"inquiry-template-id": template, "note": f"snapback:{purpose}:{reference_id}",
                                "tags": ["snapback", purpose]}},
        "meta": {"auto-create-inquiry-session": True, "auto-create-account-reference-id": "u_001"}})
    r.raise_for_status()
    body = r.json()
    data = body["data"]
    return {"inquiry_id": data["id"], "status": data["attributes"].get("status"),
            "session_token": (body.get("meta") or {}).get("session-token"),
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
    return call("persona", lambda: _real_status(inquiry_id), lambda: "unknown")


VERIFIED = ("completed", "approved")


def is_verified(inquiry_id: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
    if not inquiry_id:
        return False, {"provider": "persona", "mode": "none", "degraded": False, "error": "no inquiry", "latency_ms": 0}
    st, meta = status(inquiry_id)
    meta = {**meta, "status": st}
    return st in VERIFIED, meta


def client_config() -> Dict[str, Any]:
    """For the frontend's embedded flow: new Persona.Client({templateId, environmentId, ...})."""
    from backend.config import mode
    return {"mode": mode("persona"), "environment_id": settings.persona_environment_id or None,
            "template_id": settings.persona_template_id_approval or settings.persona_template_id_mandate or None,
            "environment": "sandbox" if settings.persona_api_key.startswith("persona_sandbox_") else
                           ("production" if settings.persona_api_key else None),
            "verified_statuses": list(VERIFIED)}
