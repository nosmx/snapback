"""Snapback orchestrator API (FastAPI, :8000). Contract: frontend/API_NEEDS.md, documented in API.md."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import audit, clock
from backend import orchestrator as O
from backend.config import DATA_DIR, MOCK_DIR, integration_modes, settings
from backend.flows import missing_package, photo, price_drop, return_window  # noqa: F401  (registers approval handlers)
from backend.integrations.singlestore import COLUMNS, db
from backend.triggers import background_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(title="Snapback")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
for sub in ("uploads", "reminders"):
    (DATA_DIR / sub).mkdir(parents=True, exist_ok=True)
app.mount("/photos", StaticFiles(directory=str(MOCK_DIR / "photos")), name="photos")
app.mount("/api/uploads", StaticFiles(directory=str(DATA_DIR / "uploads")), name="uploads")
app.mount("/api/reminders", StaticFiles(directory=str(DATA_DIR / "reminders")), name="reminders")

HIDDEN_DECISIONS = {"kept", "ignored"}


@app.on_event("startup")
def _startup() -> None:
    db().start_keepalive()  # SingleStore workspace auto-suspends after ~20 min idle
    background_loop.start()


# ---------------- health ----------------

@app.get("/api/health")
def health():
    d = db()
    modes = integration_modes()
    modes["db"] = "real" if d.backend == "singlestore" else "mock"
    return {"ok": True, "integrations": modes, "db_backend": d.backend,
            "db_fallback_reason": getattr(d, "fallback_reason", None), "llm_model": settings.llm_model,
            "counts": {t: d.count(t) for t in COLUMNS}}


# ---------------- orders ----------------

ORDER_FIELDS = ("order_id", "store", "item_name", "sku", "price", "ordered_at", "delivered_at", "return_by", "status", "image_url")


def order_view(o: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return {k: o.get(k) for k in ORDER_FIELDS} if o else None


@app.get("/api/orders")
def orders():
    return db().select("orders", order_by="ordered_at DESC")


@app.get("/api/orders/{order_id}")
def order(order_id: str):
    o = db().get("orders", "order_id", order_id)
    if not o:
        raise HTTPException(404, "order not found")
    return o


@app.get("/api/mandate")
def mandate():
    rows = db().select("mandates", limit=1)
    return rows[0] if rows else {}


# ---------------- tasks / feed ----------------

def task_view(t: Dict[str, Any], orders_by_id: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    d = t.get("details") or {}
    o = (orders_by_id or {}).get(t.get("order_id")) if orders_by_id is not None else (
        db().get("orders", "order_id", t["order_id"]) if t.get("order_id") else None)
    return {**t, "title": d.get("title"), "summary": d.get("summary"), "outcome": d.get("outcome"),
            "amount_usd": d.get("amount_usd"), "order": order_view(o)}


@app.get("/api/feed")
def feed():
    orders_by_id = {o["order_id"]: o for o in db().select("orders")}
    rows = db().select("tasks", order_by="created_at DESC")
    return [task_view(t, orders_by_id) for t in rows if (t.get("decision") or "") not in HIDDEN_DECISIONS]


@app.get("/api/tasks/{task_id}")
def task(task_id: str):
    t = O.get_task(task_id)
    if not t:
        raise HTTPException(404, "task not found")
    return task_view(t)


# ---------------- approvals ----------------

@app.get("/api/approvals")
def approvals(pending: bool = False, task_id: Optional[str] = None):
    rows = db().select("approvals", {"task_id": task_id} if task_id else None, order_by="asked_at DESC")
    if pending:
        rows = [a for a in rows if not a.get("choice")]
    return [O.serialize_approval(a) for a in rows]


class Answer(BaseModel):
    option_id: str


@app.post("/api/approvals/{approval_id}/answer")
def answer(approval_id: str, body: Answer):
    try:
        res = O.answer_approval(approval_id, body.option_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if res is None:
        raise HTTPException(404, "approval not found")
    return res


# ---------------- audit ----------------

@app.get("/api/audit")
def audit_entries(task_id: str = None, limit: int = 200):
    if task_id:
        return audit.entries_for_task(task_id)
    return db().select("audit_log", order_by="seq DESC", limit=limit)


@app.get("/api/audit/verify")
def audit_verify():
    return audit.verify_chain()


@app.get("/api/audit/export")
def audit_export(task_id: Optional[str] = None):
    entries = audit.entries_for_task(task_id) if task_id else db().select("audit_log", order_by="seq ASC")
    return {"exported_at": clock.iso(clock.now()), "task_id": task_id, "chain": audit.verify_chain(), "entries": entries}


# ---------------- triggers ----------------

@app.post("/api/photo")
async def upload_photo(file: UploadFile = File(...)):
    content = await file.read()
    if not content:
        raise HTTPException(400, "empty file")
    return {"task_id": photo.start(content, file.filename or "photo.png")}


@app.post("/api/loop/run")
def loop_run():
    return background_loop.run_once()


# ---------------- demo helpers ----------------

class Trigger(BaseModel):
    kind: str


@app.post("/api/demo/reset")
def demo_reset(stage: bool = True):
    from scripts.seed import reset_all
    with background_loop.LOOP_LOCK:
        out = reset_all(stage=stage)
    O.run_async(background_loop.run_once)   # autonomous actions start right away ("while you were away")
    return {"ok": True, **{k: v for k, v in out.items() if k in ("orders", "catalog", "audit_chain", "db_backend")}}


@app.post("/api/demo/trigger")
def demo_trigger(body: Trigger):
    from backend import rules
    m = rules.load_mandate()
    if body.kind == "major_price_drop":
        httpx.post(f"{settings.merchant_base_url}/admin/price", data={"sku": "JNH-VORTEX-BL", "price": "89"}, timeout=10)
        o = db().get("orders", "order_id", "JNH-58213")
        return {"ok": True, "task_id": price_drop.detect(o, m) if o else None}
    if body.kind == "return_window":
        o = db().get("orders", "order_id", "KSO-77120")
        facts = background_loop.screening_facts(o["store"]) if o else None
        return {"ok": True, "task_id": return_window.detect(o, m, facts) if o else None}
    if body.kind == "tamper":
        rows = db().select("audit_log", {"step": "decision_made"}, order_by="seq DESC", limit=1) or \
            db().select("audit_log", order_by="seq DESC", limit=1)
        if not rows:
            raise HTTPException(409, "audit log is empty")
        r = rows[0]
        # edit a sealed row WITHOUT re-hashing: verification must now fail at this seq
        db().update("audit_log", "entry_id", r["entry_id"], {"decision": (r.get("decision") or "") + " (edited after sealing)"})
        return {"ok": True, "tampered_seq": r["seq"], "task_id": r.get("task_id"), "verify": audit.verify_chain()}
    raise HTTPException(400, f"unknown trigger kind {body.kind}")
