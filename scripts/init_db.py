"""Create Snapback's tables (SingleStore if SINGLESTORE_URL is set, else SQLite).

  .venv/bin/python -m scripts.init_db [--drop]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.integrations.singlestore import COLUMNS, db  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--drop", action="store_true")
    args = ap.parse_args()
    d = db()
    d.init_schema(drop=args.drop)
    print(f"backend={d.backend}", {t: d.count(t) for t in COLUMNS})
