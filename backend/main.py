"""Snapback orchestrator API (FastAPI, :8000). Contract: frontend/API_NEEDS.md, documented in API.md."""
from __future__ import annotations

import asyncio
import json
import logging
import signal
import time
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import audit, clock, events
from backend import orchestrator as O
from backend.config import DATA_DIR, MOCK_DIR, integration_modes, settings
from backend.flows import chat, duplicate, missing_package, photo, price_drop, return_window  # noqa: F401  (registers approval handlers)
from backend.integrations.singlestore import COLUMNS, db
from backend.triggers import background_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(title="Snapback")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
                   expose_headers=["X-Audit-Head-Seq"])
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
    persona_inquiry_id: Optional[str] = None   # set when the frontend ran Persona's embedded flow first


@app.post("/api/approvals/{approval_id}/answer")
def answer(approval_id: str, body: Answer):
    try:
        res = O.answer_approval(approval_id, body.option_id, body.persona_inquiry_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if res is None:
        raise HTTPException(404, "approval not found")
    return res


# ---------------- audit ----------------

@app.get("/api/audit")
def audit_entries(response: Response, task_id: str = None, limit: int = 200, since_seq: Optional[int] = None):
    """Entries for a task, the latest N, or (polling fallback for /api/stream) everything after since_seq,
    oldest first. X-Audit-Head-Seq is the chain head: if it's below your since_seq, the trail was reset."""
    if since_seq is not None:
        response.headers["X-Audit-Head-Seq"] = str(audit.head_seq())
        rows = audit.entries_since(since_seq, limit=max(limit, 500))
        if task_id:
            rows = [r for r in rows if r.get("task_id") == task_id]
        return audit.with_provenance(rows)
    if task_id:
        return audit.with_provenance(audit.entries_for_task(task_id))
    return audit.with_provenance(db().select("audit_log", order_by="seq DESC", limit=limit))


def _server_exiting() -> bool:
    """True once uvicorn has been asked to stop (e.g. --reload): open streams must end or the reload waits."""
    srv = getattr(signal.getsignal(signal.SIGTERM), "__self__", None)
    return bool(getattr(srv, "should_exit", False))


def _sse(eid: int, data: Dict[str, Any]) -> str:
    return f"id: {eid}\ndata: {json.dumps(data, default=str, separators=(',', ':'))}\n\n"


@app.get("/api/stream")
async def stream(request: Request, since_seq: Optional[int] = None):
    """Server-Sent Events: every new audit entry and task status change as it is written.

    Every event is a default `message` with a JSON `type`: hello | audit | task | reset | tampered | resync.
    ?since_seq=N first replays the sealed entries after N. Reconnects resume from Last-Event-ID.
    """
    last = request.headers.get("last-event-id", "")
    resume = int(last) if last.isdigit() else None

    async def gen():
        cursor = resume if resume is not None else events.current_id()
        sent_seq = 0
        yield "retry: 1500\n\n"
        if resume is None and since_seq is not None:
            for r in await run_in_threadpool(audit.entries_since, since_seq, 2000):
                v = audit.stream_view(r)
                sent_seq = max(sent_seq, v["seq"])
                yield _sse(cursor, v)
        if resume is None:
            yield _sse(cursor, {"type": "hello", "head_seq": await run_in_threadpool(audit.head_seq),
                                "boot_id": events.BOOT_ID})
        opened = last_beat = time.time()
        while not _server_exiting() and time.time() - opened < 600:   # the client reconnects after 10 min
            if await request.is_disconnected():
                break
            evs, missed = events.since(cursor)
            if missed:
                cursor = events.current_id()
                yield _sse(cursor, {"type": "resync", "reason": "events were missed; refetch /api/audit?since_seq=N"})
                continue
            for eid, data in evs:
                cursor = eid
                if data["type"] == "reset":
                    sent_seq = 0
                elif data["type"] == "audit":
                    if data["seq"] <= sent_seq:
                        continue          # already replayed from the database
                    sent_seq = data["seq"]
                yield _sse(eid, data)
            if evs:
                last_beat = time.time()
            elif time.time() - last_beat > 15:
                last_beat = time.time()
                yield ": ping\n\n"
            await asyncio.sleep(0.25)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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


class ChatMessage(BaseModel):
    message: str


@app.post("/api/chat")
def chat_message(body: ChatMessage):
    if not body.message.strip():
        raise HTTPException(400, "empty message")
    return {"task_id": chat.start(body.message.strip())}


@app.get("/api/persona/config")
def persona_config():
    """What the frontend needs to launch Persona's embedded flow (sandbox)."""
    from backend.integrations import persona as P
    return P.client_config()


@app.post("/api/loop/run")
def loop_run():
    return background_loop.run_once()


# ---------------- demo helpers ----------------

class Trigger(BaseModel):
    kind: str
    price: Optional[float] = None   # major_price_drop: new price (default $89); a new price level -> a new card


STAGED = ("price_drop_minor", "missing_package", "chat")


@app.post("/api/demo/reset")
def demo_reset(stage: bool = True, wait_s: float = 19.0):
    """Reset the world and re-seed, then stage the demo by RUNNING the real flows: the background
    loop (minor price drop -> adjustment, lost package -> claim, major drop card, return-window card)
    and a chat message ("my old Vortex Pro blender died" -> warranty claim). Returns once the three
    autonomous tasks are done and both cards are pending (or after wait_s)."""
    import yaml
    from concurrent.futures import ThreadPoolExecutor
    from scripts.seed import reset_all
    from backend.integrations import senso
    t0 = time.time()
    # Warm the cited Senso lookups the staged flows use, in parallel with the seed (the results keep
    # their own retrieved_at; identical queries within 120 s reuse them).
    warm = ThreadPoolExecutor(max_workers=8)
    for store in ("northwind-audio", "juniper-home", "kestrel-outdoors", "larkspur-supply"):
        warm.submit(senso.policy_summary, store)
    for q, store in (("price adjustment price drop refund the difference", "juniper-home"),
                     ("returns defective items return window refund", "juniper-home"),
                     ("warranty defects materials workmanship claim replacement", "juniper-home"),
                     ("return window unworn items refund return shipping", "kestrel-outdoors"),
                     ("returns defective items return window refund", "northwind-audio")):
        warm.submit(senso.query, q, store)
    with background_loop.LOOP_LOCK:
        events.publish({"type": "reset", "at": clock.iso(clock.now()).replace(" ", "T")})
        out = reset_all(stage=stage)
    seeded_s = round(time.time() - t0, 1)
    if not stage:
        return {"ok": True, "seconds": seeded_s, **{k: out[k] for k in ("orders", "catalog", "audit_chain", "db_backend")}}
    msg = yaml.safe_load((MOCK_DIR / "emails" / "orders.yaml").read_text()).get("demo_chat")
    if msg:
        chat.start(msg)                      # runs in parallel with the loop pass
    background_loop.run_once()
    warm.shutdown(wait=False)
    done, pending = [], []
    while time.time() - t0 < wait_s:
        tasks = db().select("tasks")
        done = [t for t in tasks if t["trigger_type"] in STAGED and t["status"] == "done"]
        pending = [a for a in db().select("approvals") if not a.get("choice")]
        if len(done) >= 3 and len(pending) >= 2:
            break
        time.sleep(0.4)
    return {"ok": len(done) >= 3 and len(pending) >= 2, "seconds": round(time.time() - t0, 1), "seed_seconds": seeded_s,
            "completed": [{"task_id": t["task_id"], "trigger_type": t["trigger_type"], "outcome": (t.get("details") or {}).get("outcome")} for t in done],
            "pending_approvals": len(pending), "audit_chain": audit.verify_chain(),
            **{k: out[k] for k in ("orders", "catalog", "db_backend")}}


class CalendarMode(BaseModel):
    mode: Optional[str] = None      # auto | mock | ics; null restores CALENDAR_MODE from .env


@app.get("/api/demo/calendar")
def calendar_mode_get():
    from backend.actions import calendar
    return {"mode": calendar.current_mode(), "calendar": settings.calendar_name,
            "mock_calendar_url": f"{settings.merchant_base_url}/calendar"}


@app.post("/api/demo/calendar")
def calendar_mode_set(body: CalendarMode):
    """Where drop-off reminders go. Test runners switch to `mock` so they don't fill the real Calendar."""
    from backend.actions import calendar
    try:
        return {"mode": calendar.set_mode(body.mode)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/demo/trigger")
def demo_trigger(body: Trigger):
    from backend import rules
    m = rules.load_mandate()
    if body.kind == "major_price_drop":
        httpx.post(f"{settings.merchant_base_url}/admin/price", data={"sku": "JNH-VORTEX-BL", "price": str(body.price or 89)}, timeout=10)
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
        events.publish({"type": "tampered", "seq": int(r["seq"]), "task_id": r.get("task_id")})
        return {"ok": True, "tampered_seq": r["seq"], "task_id": r.get("task_id"), "verify": audit.verify_chain()}
    raise HTTPException(400, f"unknown trigger kind {body.kind}")
