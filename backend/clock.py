"""World clock shared with the mock merchant (demo can advance time via /admin).

Reads only the clock offset from mock/state/world.json; everything else about the
outside world is reached through the merchant's HTTP API, the inbox, or the bank ledger.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from backend.config import MOCK_DIR

WORLD_FILE = MOCK_DIR / "state" / "world.json"


def _offset_hours() -> float:
    try:
        return float(json.loads(WORLD_FILE.read_text()).get("clock_offset_hours", 0))
    except (FileNotFoundError, ValueError):
        return 0.0


def now() -> datetime:
    """Naive UTC 'now', shifted by the demo clock offset."""
    return datetime.utcnow() + timedelta(hours=_offset_hours())


def today() -> date:
    # Demo runs in PT; dates shown to the user are PT calendar dates.
    return (now() - timedelta(hours=8)).date()


def iso(dt: datetime) -> str:
    return dt.isoformat(sep=" ", timespec="microseconds")
