"""Planner -> executor -> verifier plumbing shared by every flow.

- Every step is one audit.append(...) + one amplitude.track(...).
- Flows run in background threads; endpoints return immediately.
- Idempotency: tasks.idempotency_key + task state are checked before any executor action.
- A task is `done` only after the verifier confirms from outside evidence (inbox / bank ledger).
"""
from __future__ import annotations

import logging
import threading
import traceback
import uuid
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Tuple

from backend import audit, clock, rules, verifier
from backend.actions import calendar, returns_portal
from backend.config import settings
from backend.integrations import amplitude, persona
from backend.integrations.base import model_label
from backend.integrations.singlestore import db

log = logging.getLogger("snapback.orchestrator")
_task_lock = threading.RLock()
_answer_lock = threading.Lock()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------- tasks ----------------

def create_task(trigger_type: str, order_id: Optional[str], *, title: str, summary: str,
                idempotency_key: Optional[str] = None, status: str = "detected",
                amount_usd: Optional[float] = None, **details: Any) -> Tuple[str, bool]:
    """Returns (task_id, created). An existing task with the same idempotency key is returned as-is."""
    with _task_lock:
        if idempotency_key:
            rows = db().select("tasks", {"idempotency_key": idempotency_key}, limit=1)
            if rows:
                return rows[0]["task_id"], False
        tid = new_id("tsk")
        now = clock.now()
        db().insert("tasks", {
            "task_id": tid, "trigger_type": trigger_type, "order_id": order_id, "status": status, "decision": None,
            "idempotency_key": idempotency_key or tid, "created_at": now, "updated_at": now, "authorized_by": None,
            "details": {"title": title, "summary": summary, "amount_usd": amount_usd, **details},
        })
        return tid, True


def get_task(tid: str) -> Optional[Dict[str, Any]]:
    return db().get("tasks", "task_id", tid)


def update_task(tid: str, *, status: Optional[str] = None, decision: Optional[str] = None,
                authorized_by: Optional[str] = None, order_id: Optional[str] = None, **details: Any) -> None:
    with _task_lock:
        t = get_task(tid)
        if not t:
            return
        d = dict(t.get("details") or {})
        d.update(details)
        fields: Dict[str, Any] = {"details": d, "updated_at": clock.now()}
        for k, v in (("status", status), ("decision", decision), ("authorized_by", authorized_by), ("order_id", order_id)):
            if v is not None:
                fields[k] = v
        db().update("tasks", "task_id", tid, fields)


def set_order_status(order_id: str, status: str) -> None:
    db().update("orders", "order_id", order_id, {"status": status})


# ---------------- steps (audit + analytics) ----------------

def step(tid: str, name: str, decision: str, *, reason: str = "", inputs: Optional[Dict[str, Any]] = None,
         sources: Optional[List[Dict[str, Any]]] = None, rejected: Optional[List[Dict[str, Any]]] = None,
         rules_checked: Optional[List[Dict[str, Any]]] = None, authorized_by: str = "", model: str = "",
         cost_usd: Optional[float] = None, latency_ms: Optional[int] = None, verified: Optional[bool] = None,
         track: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    inp = dict(inputs or {})
    if reason:
        inp["reason"] = reason
    entry = audit.append(tid, name, inputs=inp, sources=sources, decision=decision, rejected_options=rejected,
                         rules_checked=rules_checked, authorized_by=authorized_by, model=model, cost_usd=cost_usd,
                         latency_ms=latency_ms, verified=verified)
    amplitude.track(name, {"task_id": tid, "authorized_by": authorized_by, "model": model or None,
                           "cost_usd": cost_usd, "latency_ms": latency_ms, "verified": verified, **(track or {})})
    return entry


def fail(tid: str, why: str, *, authorized_by: str = "verifier", inputs: Optional[Dict[str, Any]] = None) -> None:
    step(tid, "failed", why[:140], reason=why, inputs=inputs, authorized_by=authorized_by)
    update_task(tid, status="failed", summary=why[:200])


def run_async(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    def wrapper() -> None:
        try:
            fn(*args, **kwargs)
        except Exception as e:  # never leave a task spinning silently
            log.error("flow %s failed: %s\n%s", getattr(fn, "__name__", fn), e, traceback.format_exc())
            tid = next((a for a in args if isinstance(a, str) and a.startswith("tsk_")), None)
            if tid:
                try:
                    fail(tid, f"Flow error ({type(e).__name__}): {str(e)[:160]}")
                except Exception:
                    pass
    threading.Thread(target=wrapper, daemon=True, name=f"flow-{getattr(fn, '__name__', 'x')}").start()


# ---------------- sources ----------------

def email_source_for_order(order: Dict[str, Any]) -> Dict[str, Any]:
    return {"doc": f"Order email {order['order_id']}", "section": "order summary",
            "url": f"{settings.merchant_base_url}/inbox/{order.get('source_email_id')}",
            "retrieved_at": clock.iso(clock.now())}


def senso_source(cit: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not cit:
        return []
    keep = ("doc", "section", "url", "retrieved_at", "quote", "source", "senso_kb_node_id", "store")
    return [{k: cit.get(k) for k in keep if cit.get(k) is not None}]


def persona_source(inquiry_id: str) -> Dict[str, Any]:
    return {"doc": "Persona inquiry", "section": inquiry_id, "url": None, "retrieved_at": clock.iso(clock.now())}


# ---------------- approvals (one-tap, Persona-verified) ----------------

HANDLERS: Dict[str, Callable[..., None]] = {}


def on_answer(trigger_type: str):
    def deco(fn: Callable[..., None]) -> Callable[..., None]:
        HANDLERS[trigger_type] = fn
        return fn
    return deco


def create_approval(tid: str, question: str, options: List[Dict[str, Any]], recommended: Optional[str], *,
                    price_math: Optional[Dict[str, Any]] = None, deadline: Optional[Dict[str, Any]] = None) -> str:
    aid = new_id("apr")
    db().insert("approvals", {"approval_id": aid, "task_id": tid, "question": question, "options": options,
                              "recommended": recommended, "choice": None, "persona_inquiry_id": None,
                              "asked_at": clock.now(), "answered_at": None})
    update_task(tid, approval_id=aid, price_math=price_math, deadline=deadline)
    return aid


def serialize_approval(a: Dict[str, Any]) -> Dict[str, Any]:
    t = get_task(a["task_id"]) or {}
    d = t.get("details") or {}
    out = dict(a)
    if d.get("price_math"):
        out["price_math"] = d["price_math"]
    if d.get("deadline"):
        out["deadline"] = d["deadline"]
    out["persona_verified"] = bool(a.get("persona_inquiry_id"))
    return out


def answer_approval(aid: str, option_id: str) -> Optional[Dict[str, Any]]:
    """Idempotent: a second answer returns the first result and never re-executes."""
    with _answer_lock:
        a = db().get("approvals", "approval_id", aid)
        if not a:
            return None
        t = get_task(a["task_id"]) or {}
        if a.get("choice"):
            return {"task_id": a["task_id"], "status": t.get("status"), "persona_inquiry_id": a.get("persona_inquiry_id"),
                    "choice": a["choice"], "replayed": True}
        opt = next((o for o in (a.get("options") or []) if o["id"] == option_id), None)
        if not opt:
            raise ValueError(f"unknown option {option_id}")
        action = opt.get("action", "execute")
        inquiry_id, verified, pmeta = None, None, {"mode": "none", "provider": "persona"}
        if action == "execute":
            inq, pmeta = persona.start_inquiry(reference_id=aid, purpose="approval")
            inquiry_id = inq["inquiry_id"]
            verified, _ = persona.is_verified(inquiry_id)
            if not verified:
                step(a["task_id"], "user_approved", "Persona verification failed: not executed",
                     reason="The approval could not be verified as the account holder, so nothing was executed.",
                     inputs={"approval_id": aid, "option_id": option_id}, sources=[persona_source(inquiry_id)],
                     rules_checked=[rules.check("persona_verified", False, inquiry_id)], authorized_by="user",
                     model=model_label(pmeta, "persona"), verified=False)
                return {"task_id": a["task_id"], "status": t.get("status"), "persona_inquiry_id": inquiry_id, "verified": False}
        db().update("approvals", "approval_id", aid, {"choice": option_id, "persona_inquiry_id": inquiry_id,
                                                      "answered_at": clock.now()})
        authorized = f"approval:{aid}" if action == "execute" else "user"
        step(a["task_id"], "user_approved",
             f"User chose: {opt['label']}" + (" · verified by Persona" if verified else ""),
             reason=(f"The account holder picked “{opt['label']}” with one tap"
                     + (" and Persona confirmed it was them." if verified else ".")),
             inputs={"approval_id": aid, "option_id": option_id, "persona_inquiry_id": inquiry_id},
             sources=[persona_source(inquiry_id)] if inquiry_id else [],
             rules_checked=[rules.check("persona_verified", True, inquiry_id)] if verified else [],
             authorized_by=authorized, model=model_label(pmeta, "persona") if inquiry_id else "",
             verified=verified, track={"option": option_id, "trigger": t.get("trigger_type")})
        status = "executing" if action == "execute" else t.get("status")
        update_task(a["task_id"], status=status, approval_choice=option_id)
    handler = HANDLERS.get(t.get("trigger_type", ""))
    if handler:
        if action == "execute":
            run_async(handler, a["task_id"], aid, opt)
        else:
            handler(a["task_id"], aid, opt)
            status = (get_task(a["task_id"]) or {}).get("status", status)
    return {"task_id": a["task_id"], "status": status, "persona_inquiry_id": inquiry_id, "choice": option_id}


# ---------------- shared flow pieces ----------------

def execute_return(tid: str, order: Dict[str, Any], reason_code: str, authorized_by: str,
                   verified_by: str = "") -> Optional[Dict[str, Any]]:
    """Browser agent files the return; verifier confirms the email; reminder added. Returns the return record."""
    key = f"return:{order['order_id']}"
    update_task(tid, status="executing", summary=f"Filing the return for {order['item_name']} on the store's portal…")
    res = returns_portal.file_return(order["store"], order["order_id"], order.get("ship_zip") or "", reason_code,
                                     idempotency_key=key, verified_by=verified_by)
    if not res["ok"]:
        step(tid, "return_filed", f"Return failed: {res.get('error', 'portal error')}",
             reason="The portal rejected the return after a retry; a request was drafted to store support instead.",
             inputs={"attempts": res.get("attempts"), "idempotency_key": key}, authorized_by=authorized_by,
             model="playwright", verified=False)
        update_task(tid, status="failed", summary=f"Return could not be filed: {res.get('error')}")
        return None
    step(tid, "return_filed", f"Return {res['rma']} filed · refund {rules.money(res['refund_amount'])}",
         reason=f"The browser agent looked up order {order['order_id']} by order number and ZIP and submitted the return.",
         inputs={"order_id": order["order_id"], "reason_code": reason_code, "idempotency_key": key,
                 "attempts": res.get("attempts"), "label_url": res.get("label_url")},
         sources=[{"doc": "Returns portal confirmation", "section": res["rma"], "url": res.get("confirmation_url"),
                   "retrieved_at": clock.iso(clock.now())}],
         authorized_by=authorized_by, model="playwright", track={"store": order["store"], "rma": res["rma"]})
    set_order_status(order["order_id"], "returned")
    by = date.fromisoformat(res["drop_off_by"])
    rem = calendar.add_dropoff_reminder(tid, f"Drop off {order['item_name']} return ({res['rma']})", by)
    step(tid, "reminder_added", f"Drop-off reminder for {rem['remind_on']} (deadline {by})",
         reason="A calendar reminder makes sure the package is dropped off before the label expires.",
         inputs=rem, sources=[{"doc": "Return label", "section": res["rma"], "url": res.get("label_url"),
                               "retrieved_at": clock.iso(clock.now())}], authorized_by=authorized_by)
    update_task(tid, rma=res["rma"], label_url=res.get("label_url"), refund_expected=res["refund_amount"],
                ics_url=rem["ics_url"])
    return res


def verify_email(tid: str, meta_key: str, value: str, what: str) -> Optional[Dict[str, Any]]:
    e = verifier.find_email(meta_key, value, timeout_s=10)
    step(tid, "verified", f"{what} confirmed by email" if e else f"{what}: no confirmation email yet",
         reason=("Checked the inbox for the store's confirmation instead of trusting the executor."),
         sources=[verifier.email_source(e)] if e else [], authorized_by="verifier", verified=bool(e),
         inputs={"looked_for": {meta_key: value}})
    return e


def await_refund(tid: str, ref: str, amount: float, outcome: str, wait_s: float = 40) -> bool:
    """Task closes only when the refund posts in the bank ledger. If it hasn't yet, the background
    loop keeps checking tasks in `awaiting_refund`."""
    update_task(tid, status="awaiting_refund", refund_ref=ref, refund_expected=amount, pending_outcome=outcome,
                summary=f"Waiting for {rules.money(amount)} to post to your original payment method…")
    txn = verifier.find_refund(ref, timeout_s=wait_s)
    if not txn:
        return False
    close_refund(tid, txn, outcome)
    return True


def close_refund(tid: str, txn: Dict[str, Any], outcome: str) -> None:
    with _task_lock:
        t = get_task(tid)
        if not t or t["status"] == "done":
            return
        step(tid, "refund_received", f"{rules.money(txn['amount'])} posted to original payment",
             reason="The bank ledger shows the refund, so the verifier closed the task.",
             sources=[verifier.bank_source(txn)], authorized_by="verifier", verified=True,
             track={"amount": txn["amount"]})
        d = t.get("details") or {}
        # money recovered: the refund itself, unless the flow set a net figure (e.g. return & rebuy)
        update_task(tid, status="done", outcome=outcome, amount_usd=d.get("final_amount", txn["amount"]),
                    summary=d.get("final_summary") or d.get("summary"))


def recheck_awaiting_refunds() -> int:
    """Background-loop follow-up: close tasks whose refund has since posted."""
    n = 0
    for t in db().select("tasks", {"status": "awaiting_refund"}):
        d = t.get("details") or {}
        if d.get("refund_ref"):
            txn = verifier.find_refund(d["refund_ref"])
            if txn:
                close_refund(t["task_id"], txn, d.get("pending_outcome") or "Refund received")
                n += 1
    return n
