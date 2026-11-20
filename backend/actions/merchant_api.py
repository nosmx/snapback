"""Merchant support endpoints (form posts) and read-only lookups: prices, carrier tracking."""
from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from backend.config import settings

M = settings.merchant_base_url


def _form(path: str, data: Dict[str, Any]) -> Dict[str, Any]:
    r = httpx.post(M + path, data=data, timeout=20)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"error": r.text[:200]}
    body.setdefault("ok", r.status_code == 200)
    body["http_status"] = r.status_code
    return body


def request_price_adjustment(store: str, order_no: str, zip_code: str, idempotency_key: str, verified_by: str = ""):
    return _form(f"/s/{store}/price-adjustment", {"order_no": order_no, "zip_code": zip_code,
                                                   "idempotency_key": idempotency_key, "verified_by": verified_by})


def file_warranty_claim(store: str, order_no: str, zip_code: str, description: str, idempotency_key: str, verified_by: str = ""):
    return _form(f"/s/{store}/warranty", {"order_no": order_no, "zip_code": zip_code, "description": description,
                                           "idempotency_key": idempotency_key, "verified_by": verified_by})


def file_missing_claim(store: str, order_no: str, zip_code: str, idempotency_key: str, verified_by: str = ""):
    return _form(f"/s/{store}/claims/missing", {"order_no": order_no, "zip_code": zip_code,
                                                 "idempotency_key": idempotency_key, "verified_by": verified_by})


def current_price(store: str, sku: str) -> Optional[Dict[str, Any]]:
    r = httpx.get(f"{M}/s/{store}/api/price/{sku}", timeout=10)
    return r.json() if r.status_code == 200 else None


def track(tracking: str) -> Optional[Dict[str, Any]]:
    r = httpx.get(f"{M}/carrier/track/{tracking}", timeout=10)
    return r.json() if r.status_code == 200 else None
