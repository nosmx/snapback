"""Tamper-evident audit trail: entry_hash = sha256(prev_hash + canonical_json(entry)).

One global chain ordered by `seq`. Values are normalized *before* hashing and inserting
(cost rounded to 5 dp, timestamps ISO-8601 with microseconds, integral floats as ints) so a
round-trip through SingleStore/SQLite re-hashes identically.
"""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from backend import clock
from backend.integrations.singlestore import db

GENESIS = "0" * 64
_lock = threading.Lock()

HASHED_FIELDS = ["seq", "task_id", "step", "inputs", "sources", "decision", "rejected_options", "rules_checked",
                 "authorized_by", "model", "cost_usd", "latency_ms", "verified", "created_at"]


def _canon(obj: Any) -> Any:
    if isinstance(obj, bool) or obj is None or isinstance(obj, str):
        return obj
    if isinstance(obj, (int,)):
        return obj
    if isinstance(obj, (float, Decimal)):
        f = float(obj)
        return int(f) if f.is_integer() else round(f, 6)
    if isinstance(obj, dict):
        return {str(k): _canon(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_canon(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat(sep=" ", timespec="microseconds")
    return str(obj)


def canonical_json(obj: Any) -> str:
    return json.dumps(_canon(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _norm_ts(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat(sep=" ", timespec="microseconds")
    return datetime.fromisoformat(str(v).replace("T", " ")).isoformat(sep=" ", timespec="microseconds")


def _norm_cost(v: Any) -> Optional[str]:
    return None if v is None else f"{Decimal(str(v)):.5f}"


def _payload(entry: Dict[str, Any]) -> Dict[str, Any]:
    p = {k: entry.get(k) for k in HASHED_FIELDS}
    p["cost_usd"] = _norm_cost(p["cost_usd"])
    p["created_at"] = _norm_ts(p["created_at"])
    p["verified"] = None if p["verified"] is None else bool(p["verified"])
    p["latency_ms"] = None if p["latency_ms"] is None else int(p["latency_ms"])
    p["seq"] = int(p["seq"])
    for k in ("inputs", "sources", "rejected_options", "rules_checked"):
        if isinstance(p[k], str):
            try:
                p[k] = json.loads(p[k])
            except ValueError:
                pass
    return p


def compute_hash(prev_hash: str, entry: Dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + canonical_json(_payload(entry))).encode()).hexdigest()


def _head() -> Dict[str, Any]:
    rows = db().query("SELECT seq, entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1")
    return rows[0] if rows else {"seq": 0, "entry_hash": GENESIS}


def append(task_id: Optional[str], step: str, *, inputs: Any = None, sources: Optional[List[Dict[str, Any]]] = None,
           decision: str = "", rejected_options: Optional[List[Dict[str, Any]]] = None,
           rules_checked: Optional[List[Dict[str, Any]]] = None, authorized_by: str = "", model: str = "",
           cost_usd: Optional[float] = None, latency_ms: Optional[int] = None,
           verified: Optional[bool] = None) -> Dict[str, Any]:
    """Append one step to the chain. Returns the stored entry (with hashes)."""
    with _lock:
        head = _head()
        entry = {
            "seq": int(head["seq"]) + 1, "task_id": task_id, "step": step,
            "inputs": _canon(inputs or {}), "sources": _canon(sources or []), "decision": decision,
            "rejected_options": _canon(rejected_options or []), "rules_checked": _canon(rules_checked or []),
            "authorized_by": authorized_by, "model": model,
            "cost_usd": None if cost_usd is None else float(_norm_cost(cost_usd)),
            "latency_ms": latency_ms, "verified": verified,
            "created_at": clock.iso(clock.now()),
        }
        entry["prev_hash"] = head["entry_hash"]
        entry["entry_hash"] = compute_hash(entry["prev_hash"], entry)
        db().insert("audit_log", entry)
    return entry


def verify_chain() -> Dict[str, Any]:
    rows = db().select("audit_log", order_by="seq ASC")
    prev = GENESIS
    for i, r in enumerate(rows, start=1):
        if int(r["seq"]) != i or r["prev_hash"] != prev or compute_hash(prev, r) != r["entry_hash"]:
            return {"ok": False, "entries": len(rows), "broken_at_seq": r["seq"], "head": prev}
        prev = r["entry_hash"]
    return {"ok": True, "entries": len(rows), "broken_at_seq": None, "head": prev}


def entries_for_task(task_id: str) -> List[Dict[str, Any]]:
    return db().select("audit_log", {"task_id": task_id}, order_by="seq ASC")
