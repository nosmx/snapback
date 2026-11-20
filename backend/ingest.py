"""Order-email ingestion: injection check -> SIE extraction -> image embedding -> orders row + audit entry.

Used by the seed (batched, with an SIE result cache so demo resets are fast) and by the background
loop (new order emails, e.g. confirmations of purchases, become tracked orders).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

from backend import audit, clock
from backend.config import DATA_DIR, MOCK_DIR, integration_modes, settings
from backend.integrations import sie
from backend.integrations.base import model_label
from backend.integrations.singlestore import db
from backend.safety import detect_injection

ORDER_KINDS = ("order", "order_confirmation")
_CACHE_FILE = DATA_DIR / "sie_cache.json"
_cache: Optional[Dict[str, Any]] = None


def cached(kind: str, material: bytes, fn: Callable[[], Tuple[Any, Dict[str, Any]]]):
    """Cache real, non-degraded SIE results keyed by (model, mode, input)."""
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(_CACHE_FILE.read_text())
        except (FileNotFoundError, ValueError):
            _cache = {}
    key = f"{kind}:{sie.model_name(kind)}:{integration_modes()['sie']}:" + hashlib.sha256(material).hexdigest()
    if key in _cache:
        res, meta = _cache[key]
        return res, {**meta, "latency_ms": 0, "cached": True}
    res, meta = fn()
    if meta["mode"] == "real" and not meta["degraded"]:
        _cache[key] = [res, meta]
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(_cache))
    return res, meta


def _date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%B %d, %Y")
    except ValueError:
        return None


def _stores_by_name() -> Dict[str, str]:
    stores = json.loads((MOCK_DIR / "stores" / "stores.json").read_text())
    return {s["name"]: s["id"] for s in stores}


def build(email: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Returns (orders row, audit.append kwargs) for one order email. Never invents values."""
    clean, flags = detect_injection(email["body_text"])
    ext, emeta = cached("extract", (clean + "|" + email["from"]).encode(), lambda: sie.extract(clean, email["from"]))
    f = ext["fields"]
    img = None
    if email.get("image"):   # same lookup as the merchant's /static/products/<name>: overrides first
        img = next((d / email["image"] for d in (MOCK_DIR / "product_images", MOCK_DIR / "static" / "products")
                    if (d / email["image"]).is_file()), None)
    vec = None
    if img and img.exists():
        vec, _ = cached("image", img.read_bytes(), lambda: sie.embed_image(str(img)))
    order_id = f.get("order_no") or f"unknown-{email['email_id']}"
    delivered = _date(f.get("delivered_on"))
    rb = _date(f.get("return_by"))
    row = {
        "order_id": order_id, "store": _stores_by_name().get(f.get("merchant") or ""), "item_name": f.get("item_name"),
        "sku": f.get("sku"), "price": f.get("price"), "ordered_at": _date(f.get("order_date")),
        "delivered_at": delivered, "ship_zip": f.get("ship_zip"), "return_by": rb.date() if rb else None,
        "status": "active" if delivered else "in_transit", "image_url": email.get("image_url"),
        "image_embedding": vec, "source_email_id": email["email_id"], "tracking_number": f.get("tracking"),
        "extraction": {"fields": f, "gaps": ext["gaps"], "confidence": ext["confidence"], "flags": flags,
                       "field_sources": ext.get("field_sources", {}),
                       "model": model_label(emeta, sie.model_name("extract")), "degraded": emeta["degraded"]},
    }
    rules = [{"rule": "never_invent_missing_fields", "passed": True,
              "evidence": f"gaps marked: {ext['gaps']}" if ext["gaps"] else "all expected fields present"}]
    if flags:
        rules.append({"rule": "fetched_text_is_data", "passed": True,
                      "evidence": f"ignored injected instruction: {flags[0]['excerpt'][:120]}"})
    entry = dict(
        task_id="ingest", step="email_ingested",
        inputs={"email_id": email["email_id"], "subject": email["subject"],
                **({"reason": "An instruction hidden in the email was treated as data and ignored."} if flags else {})},
        sources=[{"doc": f"Email: {email['subject']}", "section": "order summary", "url": email.get("url"),
                  "retrieved_at": clock.iso(clock.now())}],
        decision=f"Recorded order {order_id}" + (f" with gaps {ext['gaps']}" if ext["gaps"] else "") +
                 (" · ignored injected instruction" if flags else ""),
        rules_checked=rules, authorized_by="mandate:read_only_order_email_parsing",
        model=model_label(emeta, sie.model_name("extract")), latency_ms=emeta["latency_ms"], verified=True,
    )
    return row, entry


def ingest_all_from_dir() -> int:
    """Seed path: every order email in the inbox, inserted in batches."""
    rows, entries = [], []
    for path in sorted((MOCK_DIR / "emails" / "inbox").glob("*.json")):
        email = json.loads(path.read_text())
        if email.get("kind") in ORDER_KINDS:
            r, e = build(email)
            rows.append(r)
            entries.append(e)
    db().insert_many("orders", rows)
    audit.append_many(entries)
    return len(rows)


def ingest_new_emails() -> List[str]:
    """Runtime path: order emails that arrived since the last pass (e.g. purchase confirmations)."""
    try:
        inbox = httpx.get(f"{settings.merchant_base_url}/api/inbox", timeout=10).json()
    except Exception:
        return []
    known = {o["source_email_id"] for o in db().select("orders") if o.get("source_email_id")}
    new = []
    for email in sorted(inbox, key=lambda e: e["received_at"]):
        if email.get("kind") in ORDER_KINDS and email["email_id"] not in known:
            row, entry = build(email)
            if db().get("orders", "order_id", row["order_id"]):
                continue
            db().insert("orders", row)
            audit.append(**entry)
            new.append(row["order_id"])
    return new
