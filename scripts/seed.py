"""Reset the mock world and seed Snapback's database.

  .venv/bin/python -m scripts.seed            # reset world (+ demo staging) and seed DB
  .venv/bin/python -m scripts.seed --no-stage # without the demo price drops / lost package
  .venv/bin/python -m scripts.seed --drop     # drop + recreate tables (after schema / vector-dim changes)

Steps: reset world -> tables -> mandate (Persona) + genesis audit entry -> ingest order emails
(injection check, SIE extract + image embed) -> catalog (+ text embeddings). SIE results are cached
and rows are inserted in batches, so a reset takes a few seconds.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import audit, clock  # noqa: E402
from backend.config import integration_modes, settings  # noqa: E402
from backend.ingest import cached, ingest_all_from_dir  # noqa: E402
from backend.integrations import persona, sie  # noqa: E402
from backend.integrations.base import model_label  # noqa: E402
from backend.integrations.singlestore import COLUMNS, db  # noqa: E402
from mock import world as W  # noqa: E402


def seed_mandate() -> str:
    rules = yaml.safe_load((ROOT / "backend" / "mandate.yaml").read_text())["mandate"]
    inq, meta = persona.start_inquiry(reference_id=rules["user_id"], purpose="mandate")
    verified, _ = persona.is_verified(inq["inquiry_id"])
    now = clock.now()
    db().insert("mandates", {"user_id": rules["user_id"], "rules": rules, "verified_by": "persona",
                             "persona_inquiry_id": inq["inquiry_id"], "verified_at": now})
    audit.append(
        None, "mandate_verified", inputs={"user_id": rules["user_id"], "rules": rules},
        sources=[{"doc": "Persona inquiry", "section": inq["inquiry_id"], "url": None, "retrieved_at": clock.iso(now)}],
        decision="Standing rules created and verified by a human via Persona; they authorize autonomous actions within limits.",
        rules_checked=[{"rule": "persona_verified", "passed": verified, "evidence": inq["inquiry_id"]}],
        authorized_by=f"persona:{inq['inquiry_id']}", model=model_label(meta, "persona"),
        latency_ms=meta["latency_ms"], verified=verified)
    return inq["inquiry_id"]


def seed_catalog() -> int:
    rows = []
    for item in W.catalog().values():
        text = f"{item['name']}. {item['description']} Category: {item['category']}. Specs: {json.dumps(item['specs'])}"
        vec, _ = cached("text", text.encode(), lambda: sie.embed_text(text))
        rows.append({"sku": item["sku"], "store": item["store"], "name": item["name"], "price": item["price"],
                     "rating": item["rating"], "in_stock": item["in_stock"],
                     "specs": {**item["specs"], "category": item["category"]}, "text_embedding": vec})
    db().insert_many("catalog", rows)
    return len(rows)


def reset_all(stage: bool = True, verbose: bool = False, drop: bool = False) -> Dict[str, Any]:
    """Reset the mock world and re-seed the database. Used by `make reset` and POST /api/demo/reset."""
    out: Dict[str, Any] = {"integration_modes": integration_modes()}
    out["world"] = W.reset_world(stage_demo=stage, refund_delay_seconds=settings.refund_delay_seconds)
    for sub in ("uploads", "reminders"):
        shutil.rmtree(ROOT / "data" / sub, ignore_errors=True)
        (ROOT / "data" / sub).mkdir(parents=True, exist_ok=True)
    d = db()
    out["db_backend"] = d.backend
    d.init_schema(drop=drop)          # CREATE IF NOT EXISTS (drop only when the schema/dims changed)
    if not drop:
        for t in COLUMNS:             # clearing rows is much faster than DDL on SingleStore
            d.execute(f"DELETE FROM {t}")
    out["mandate_inquiry"] = seed_mandate()
    out["orders"] = ingest_all_from_dir()
    out["catalog"] = seed_catalog()
    out["audit_chain"] = audit.verify_chain()
    if verbose:
        for k, v in out.items():
            print(f"{k}: {v}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-stage", action="store_true", help="skip demo staging (price drops, lost package)")
    ap.add_argument("--drop", action="store_true", help="drop and recreate tables (after schema or vector-dim changes)")
    args = ap.parse_args()
    reset_all(stage=not args.no_stage, verbose=True, drop=args.drop)


if __name__ == "__main__":
    main()
