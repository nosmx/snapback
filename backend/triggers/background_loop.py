"""Background loop: every BACKGROUND_LOOP_SECONDS, look for price drops, closing return windows and
missing packages, and follow up on refunds. Runs once per machine: an exclusive file lock keeps the
uvicorn --reload parent/child (or a second server) from starting a duplicate loop.
"""
from __future__ import annotations

import fcntl
import logging
import threading
import time
from typing import Any, Dict, Optional, Tuple

from backend import orchestrator as O
from backend.ingest import ingest_new_emails
from backend import rules
from backend.config import DATA_DIR, settings
from backend.flows import duplicate, missing_package, price_drop, return_window
from backend.integrations import senso
from backend.integrations.singlestore import db

log = logging.getLogger("snapback.loop")
LOOP_LOCK = threading.RLock()          # held while a pass runs; demo reset takes it too
_quiet_until = 0.0                     # scheduled passes skip until then (a demo reset runs its own pass)


def quiet(seconds: float) -> None:
    """Hold off scheduled passes, so a demo reset's own pass isn't queued behind one."""
    global _quiet_until
    _quiet_until = time.time() + seconds
_lock_fh = None
_facts_cache: Dict[str, Tuple[float, Optional[Dict[str, Any]]]] = {}


def screening_facts(store: str, ttl_s: float = 600) -> Optional[Dict[str, Any]]:
    """Cached policy facts for SCREENING only (saves Senso search credits). Each task's own
    policy_retrieved step does a fresh, cited retrieval."""
    hit = _facts_cache.get(store)
    if hit and time.time() - hit[0] < ttl_s:
        return hit[1]
    facts, _, _ = senso.policy_summary(store)
    _facts_cache[store] = (time.time(), facts)
    return facts


def run_once(scheduled: bool = False) -> Dict[str, int]:
    stats = {"tasks": 0, "refunds_closed": 0, "new_orders": 0}
    with LOOP_LOCK:
        if scheduled and time.time() < _quiet_until:
            return stats
        try:
            stats["new_orders"] = len(ingest_new_emails())   # e.g. confirmations of purchases
        except Exception as e:
            log.warning("loop: email ingestion: %s", e)
        mandate = rules.load_mandate()
        orders = db().select("orders")
        try:
            stats["tasks"] += len([t for t in duplicate.detect_all(orders, mandate) if t])
        except Exception as e:
            log.warning("loop: duplicates: %s", e)
        for o in orders:
            try:
                for tid in (price_drop.detect(o, mandate),
                            return_window.detect(o, mandate, screening_facts(o["store"]) if o.get("store") else None),
                            missing_package.detect(o, mandate)):
                    stats["tasks"] += 1 if tid else 0
            except Exception as e:
                log.warning("loop: order %s: %s", o.get("order_id"), e)
        try:
            stats["refunds_closed"] = O.recheck_awaiting_refunds()
        except Exception as e:
            log.warning("loop: refund follow-up: %s", e)
    return stats


def start() -> bool:
    global _lock_fh
    if _lock_fh is not None:
        return True
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fh = open(DATA_DIR / "background_loop.lock", "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        log.info("background loop already running in another process")
        return False
    _lock_fh = fh

    def loop() -> None:
        time.sleep(2)
        while True:
            try:
                s = run_once(scheduled=True)
                if s["tasks"] or s["refunds_closed"]:
                    log.info("loop pass: %s", s)
            except Exception as e:
                log.warning("loop pass failed: %s", e)
            time.sleep(max(5, settings.background_loop_seconds))

    threading.Thread(target=loop, daemon=True, name="background-loop").start()
    log.info("background loop every %ss", settings.background_loop_seconds)
    return True
