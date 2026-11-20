"""Load one policy doc per store into Senso, wait for ingestion, then run sanity queries.

  .venv/bin/python -m scripts.load_senso
Idempotent: unchanged docs are skipped; changed docs replace the old node (data/senso_docs.json).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.config import MOCK_DIR, integration_modes  # noqa: E402
from backend.integrations import senso  # noqa: E402


def main() -> None:
    mode = integration_modes()["senso"]
    print("senso mode:", mode)
    docs = []
    for path in sorted((MOCK_DIR / "policies").glob("*.md")):
        md = path.read_text()
        title = md.splitlines()[0].lstrip("# ").strip()
        res, meta = senso.ingest(path.stem, title, md, {"store": path.stem, "type": "policy"})
        docs.append(path.stem)
        print(f"  {path.stem}: status={res.get('status')} ({meta['mode']}{', DEGRADED: ' + str(meta['error']) if meta['degraded'] else ''})")

    if mode == "real":
        deadline = time.time() + 180
        pending = set(docs)
        while pending and time.time() < deadline:
            for d in list(pending):
                st = senso.processing_status(d)
                if st in ("complete", "failed"):
                    print(f"  {d}: ingestion {st}")
                    pending.discard(d)
            if pending:
                time.sleep(3)
        if pending:
            print("  still processing:", sorted(pending))

    res, meta = senso.query("How long is the price adjustment window?", store="juniper-home")
    top = res["citations"][0] if res["citations"] else None
    print("test query ->", (top["section"], top["url"], top.get("source")) if top else "no answer", f"[{meta['mode']}]")
    for store in ("northwind-audio", "juniper-home", "kestrel-outdoors", "larkspur-supply"):
        facts, cit, m = senso.policy_summary(store)
        print(f"summary {store}: " + (f"window={facts['return_window_days']}d adj_allowed={facts.get('price_adjustment_allowed')} "
                                      f"warranty={facts.get('warranty_days')}d <- {cit['source']} {cit['section']}"
                                      if facts else "NO VERIFIED POLICY (do not act)") + f" [{m['mode']}]")


if __name__ == "__main__":
    main()
