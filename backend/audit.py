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

from backend import clock, events
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
        events.publish(stream_view(entry))
    return entry


def append_many(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Append several entries in one round trip (seed path). Same hashing as append()."""
    if not items:
        return []
    with _lock:
        head = _head()
        seq, prev = int(head["seq"]), head["entry_hash"]
        out = []
        for it in items:
            seq += 1
            cost = it.get("cost_usd")
            entry = {
                "seq": seq, "task_id": it.get("task_id"), "step": it["step"],
                "inputs": _canon(it.get("inputs") or {}), "sources": _canon(it.get("sources") or []),
                "decision": it.get("decision", ""), "rejected_options": _canon(it.get("rejected_options") or []),
                "rules_checked": _canon(it.get("rules_checked") or []), "authorized_by": it.get("authorized_by", ""),
                "model": it.get("model", ""), "cost_usd": None if cost is None else float(_norm_cost(cost)),
                "latency_ms": it.get("latency_ms"), "verified": it.get("verified"), "created_at": clock.iso(clock.now()),
            }
            entry["prev_hash"] = prev
            entry["entry_hash"] = prev = compute_hash(prev, entry)
            out.append(entry)
        db().insert_many("audit_log", out)
        for entry in out:
            events.publish(stream_view(entry))
    return out


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


# ---------------- provenance + streaming views ----------------

SIE_ORGS = ("google/", "BAAI/", "Qwen/", "fastino/")
AUDIT_ONLY = {"email_ingested", "mandate_verified"}   # seed entries; not sent to Amplitude


def _obj(v: Any) -> Any:
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return None
    return v


def _db_mode() -> str:
    return "real" if getattr(db(), "backend", "") == "singlestore" else "mock"


def provenance(e: Dict[str, Any]) -> Dict[str, Any]:
    """Which integration produced a step: {provider, mode, providers}.

    Derived only from sealed fields (step, model label, inputs, sources), so the stream and
    /api/audit always agree and the answer is covered by the hash chain. The model label comes from
    the integration meta at call time: the real model id when live, `mock:<provider>` when mocked.
    mode is real | mock, or None for Snapback's own components.
    """
    step = e.get("step") or ""
    model = (e.get("model") or "").strip()
    inputs = _obj(e.get("inputs")) or {}
    sources = _obj(e.get("sources")) or []
    mode: Any = "real"
    if model.startswith("mock:"):
        provider, mode = model[5:] or "mock", "mock"
    elif model.startswith("senso"):
        provider = "senso"
    elif model.startswith("persona"):
        provider = "persona"
    elif model.startswith("claude"):
        provider = "llm"
    elif model.startswith("statsig"):
        provider = "statsig"
    elif model == "playwright":
        provider = "playwright"
    elif model.startswith("osascript"):
        provider = "calendar"
    elif model == "ics":
        provider, mode = "calendar", None
    elif model == "merchant-api":
        provider, mode = "merchant_api", None
    elif model.startswith(SIE_ORGS) or "/" in model:
        provider = "sie"
    elif step in ("verified", "refund_received"):
        provider, mode = "verifier", None
    elif step == "user_approved":
        provider, mode = "user", None
    else:
        provider, mode = "snapback", None
    if step == "order_matched" and isinstance(inputs, dict) and "margin" in inputs:
        # photo match: DOT_PRODUCT vector search in SingleStore over SIE image embeddings
        provider, mode = "singlestore", _db_mode()

    providers = [provider]

    def add(p: str) -> None:
        if p not in providers:
            providers.append(p)

    if step == "photo_identified" or (step == "order_matched" and provider == "singlestore"):
        add("sie")
    if step == "replacement_ranked":
        add("singlestore")       # catalog vector search
    if isinstance(inputs, dict):
        if inputs.get("statsig") is not None:
            add("statsig")
        if inputs.get("persona_inquiry_id"):
            add("persona")
    if any(isinstance(x, dict) and x.get("source") in ("senso", "local-mirror") for x in sources or []):
        add("senso")
    if step not in AUDIT_ONLY:
        add("amplitude")         # every agent step is also sent to Amplitude
    return {"provider": provider, "mode": mode, "providers": providers}


def with_provenance(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    for r in rows:
        r.update(provenance(r))
    return rows


def stream_view(e: Dict[str, Any]) -> Dict[str, Any]:
    """The compact audit event sent over /api/stream."""
    ts = _norm_ts(e.get("created_at"))
    return {"type": "audit", "seq": int(e["seq"]), "task_id": e.get("task_id"), "step": e.get("step"),
            "decision": e.get("decision"), "authorized_by": e.get("authorized_by") or None,
            "model": e.get("model") or None, "latency_ms": e.get("latency_ms"),
            "cost_usd": None if e.get("cost_usd") is None else float(e["cost_usd"]),
            "verified": e.get("verified"), **provenance(e),
            "created_at": ts.replace(" ", "T") if ts else None}


def entries_since(since_seq: int, limit: int = 500) -> List[Dict[str, Any]]:
    from backend.integrations.singlestore import COLUMNS
    return db().query(f"SELECT {', '.join(COLUMNS['audit_log'])} FROM audit_log WHERE seq > %s "
                      f"ORDER BY seq ASC LIMIT {int(limit)}", [int(since_seq)])


def head_seq() -> int:
    return int(_head()["seq"])
