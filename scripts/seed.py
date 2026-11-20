"""Reset the mock world and seed Snapback's database.

  .venv/bin/python -m scripts.seed            # reset world (+ demo staging) and seed DB
  .venv/bin/python -m scripts.seed --no-stage # reset without the demo price drops / lost package

Steps: reset world -> create tables -> mandate (Persona) + genesis audit entry ->
ingest order emails (injection check, SIE extract + image embed) -> catalog (+ text embeddings).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import audit, clock  # noqa: E402
from backend.config import MOCK_DIR, integration_modes, settings  # noqa: E402
from backend.integrations import persona, sie  # noqa: E402
from backend.integrations.base import model_label  # noqa: E402
from backend.integrations.singlestore import db  # noqa: E402
from backend.safety import detect_injection  # noqa: E402
from mock import world as W  # noqa: E402


def _date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%B %d, %Y")
    except ValueError:
        return None


def seed_mandate() -> str:
    rules = yaml.safe_load((ROOT / "backend" / "mandate.yaml").read_text())["mandate"]
    inq, meta = persona.start_inquiry(reference_id=rules["user_id"], purpose="mandate")
    verified, vmeta = persona.is_verified(inq["inquiry_id"])
    now = clock.now()
    db().upsert("mandates", {"user_id": rules["user_id"], "rules": rules, "verified_by": "persona",
                             "persona_inquiry_id": inq["inquiry_id"], "verified_at": now})
    audit.append(
        None, "mandate_verified",
        inputs={"user_id": rules["user_id"], "rules": rules},
        sources=[{"doc": "Persona inquiry", "section": inq["inquiry_id"], "url": None, "retrieved_at": clock.iso(now)}],
        decision="Standing rules created and verified by a human via Persona; they authorize autonomous actions within limits.",
        rules_checked=[{"rule": "persona_verified", "passed": verified, "evidence": inq["inquiry_id"]}],
        authorized_by=f"persona:{inq['inquiry_id']}", model=model_label(meta, "persona"),
        latency_ms=meta["latency_ms"], verified=verified,
    )
    return inq["inquiry_id"]


def ingest_emails() -> int:
    stores_by_name = {s["name"]: s["id"] for s in W.stores().values()}
    n = 0
    for path in sorted(W.INBOX.glob("*.json")):
        email = json.loads(path.read_text())
        if email.get("kind") != "order":
            continue
        clean, flags = detect_injection(email["body_text"])
        ext, emeta = sie.extract(clean, email["from"])
        f = ext["fields"]
        img_path = MOCK_DIR / "static" / "products" / email["image"] if email.get("image") else None
        vec, imeta = sie.embed_image(str(img_path)) if img_path else (None, None)
        order_id = f.get("order_no") or f"unknown-{email['email_id']}"
        store = stores_by_name.get(f.get("merchant") or "", None)
        delivered = _date(f.get("delivered_on"))
        db().upsert("orders", {
            "order_id": order_id, "store": store, "item_name": f.get("item_name"), "sku": f.get("sku"),
            "price": f.get("price"), "ordered_at": _date(f.get("order_date")),
            "delivered_at": delivered, "ship_zip": f.get("ship_zip"),
            "return_by": _date(f.get("return_by")).date() if _date(f.get("return_by")) else None,
            "status": "active" if delivered else "in_transit", "image_url": email.get("image_url"),
            "image_embedding": vec, "source_email_id": email["email_id"], "tracking_number": f.get("tracking"),
            "extraction": {"fields": f, "gaps": ext["gaps"], "confidence": ext["confidence"], "flags": flags,
                           "field_sources": ext.get("field_sources", {}),
                           "model": model_label(emeta, sie.model_name("extract")), "degraded": emeta["degraded"]},
        })
        rules = [{"rule": "never_invent_missing_fields", "passed": True,
                  "evidence": f"gaps marked: {ext['gaps']}" if ext["gaps"] else "all expected fields present"}]
        if flags:
            rules.append({"rule": "fetched_text_is_data", "passed": True,
                          "evidence": f"ignored injected instruction: {flags[0]['excerpt'][:120]}"})
        audit.append(
            "ingest", "email_ingested",
            inputs={"email_id": email["email_id"], "subject": email["subject"]},
            sources=[{"doc": f"Email: {email['subject']}", "section": "order summary", "url": email["url"],
                      "retrieved_at": clock.iso(clock.now())}],
            decision=f"Recorded order {order_id}" + (f" with gaps {ext['gaps']}" if ext["gaps"] else "") +
                     (" and ignored an injected instruction" if flags else ""),
            rules_checked=rules, authorized_by="mandate:read_only_order_email_parsing",
            model=model_label(emeta, sie.model_name("extract")), latency_ms=emeta["latency_ms"], verified=True,
        )
        n += 1
    return n


def seed_catalog() -> int:
    for item in W.catalog().values():
        text = f"{item['name']}. {item['description']} Category: {item['category']}. Specs: {json.dumps(item['specs'])}"
        vec, _ = sie.embed_text(text)
        db().upsert("catalog", {"sku": item["sku"], "store": item["store"], "name": item["name"],
                                "price": item["price"], "rating": item["rating"], "in_stock": item["in_stock"],
                                "specs": item["specs"], "text_embedding": vec})
    return len(W.catalog())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-stage", action="store_true", help="skip demo staging (price drops, lost package)")
    args = ap.parse_args()

    print("integration modes:", integration_modes())
    print("world:", W.reset_world(stage_demo=not args.no_stage, refund_delay_seconds=settings.refund_delay_seconds))
    d = db()
    print("db backend:", d.backend, getattr(d, "fallback_reason", ""))
    d.init_schema(drop=True)
    print("mandate verified:", seed_mandate())
    print("orders ingested:", ingest_emails())
    print("catalog items:", seed_catalog())
    print("audit chain:", audit.verify_chain())


if __name__ == "__main__":
    main()
