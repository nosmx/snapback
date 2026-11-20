"""Return-window alerts (§5.4): one card (Return · Keep · Remind me tomorrow); after "Return"
the whole return runs autonomously. No replacement unless the reason is "defective"."""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, Optional

from backend import clock, rules
from backend import orchestrator as O
from backend.integrations import senso
from backend.integrations.base import model_label
from backend.integrations.singlestore import db

money = rules.money


def detect(order: Dict[str, Any], mandate: Dict[str, Any], facts: Optional[Dict[str, Any]]) -> Optional[str]:
    if not facts or order.get("status") != "active" or not order.get("delivered_at"):
        return None
    a = rules.return_window_alert(order, facts, mandate)
    if not a["alert"]:
        return None
    key = f"retwin:{order['order_id']}"
    prior = db().select("tasks", {"idempotency_key": key}, limit=1)
    if prior:
        d = prior[0].get("details") or {}
        # one follow-up after "remind me tomorrow", then never again
        if prior[0].get("decision") == "snoozed" and d.get("snooze_until") and clock.today().isoformat() >= d["snooze_until"]:
            key = f"retwin:{order['order_id']}:reminder"
        else:
            return None
    tid, created = O.create_task("return_window", order["order_id"], idempotency_key=key,
                                 title=f"Return window closing: {order['item_name']}", amount_usd=float(order["price"]),
                                 summary=f"{a['days_left']} days left to return it")
    if created:
        O.run_async(run, tid, order, a)
    return tid


def run(tid: str, order: Dict[str, Any], a: Dict[str, Any]) -> None:
    deadline = a["deadline"]
    O.step(tid, "task_detected", f"Return window closes {deadline:%b %-d} ({a['days_left']} days left)",
           reason="The background check found an order whose return window is about to close.",
           inputs={"return_by": deadline.isoformat(), "days_left": a["days_left"]},
           sources=[O.email_source_for_order(order)], rules_checked=a["rules"], authorized_by="background_loop",
           track={"trigger": "return_window", "store": order["store"]})
    facts, cite, smeta = senso.policy_summary(order["store"])
    clause_res, _ = senso.query("return window unworn items refund return shipping", store=order["store"])
    clause = next((x for x in clause_res.get("citations", []) if "summary" not in x["section"].lower()), None)
    ship = float((facts or {}).get("return_shipping_usd_non_defective", 0) or 0)
    O.step(tid, "policy_retrieved", f"Policy: {facts.get('return_window_days')}-day returns · {money(ship)} return shipping" if facts else "No verified policy",
           reason="Return terms come from the store's policy in Senso.", inputs={"facts": facts},
           sources=O.senso_source(clause) + O.senso_source(cite), rules_checked=[rules.verified_policy(facts, order["store"])],
           authorized_by="background_loop", model=model_label(smeta, "senso:search/context"))
    store = order["store"].replace("-", " ").title()
    question = f"Your {store} {order['item_name']} ({money(float(order['price']))}) can be returned until {deadline:%b %-d}. Return it?"
    opts = [
        {"id": "return", "label": "Return it", "action": "execute", "net_savings_usd": round(float(order["price"]) - ship, 2),
         "detail": f"Snapback files it, refund to your card" + (f" · {money(ship)} return shipping" if ship else "")},
        {"id": "keep", "label": "Keep", "action": "dismiss", "detail": "Stop alerts for this item"},
        {"id": "snooze", "label": "Remind me tomorrow", "action": "snooze", "detail": f"One more reminder before {deadline:%b %-d}"},
    ]
    aid = O.create_approval(tid, question, opts, None,
                            deadline={"return_by": deadline.isoformat(), "days_left": a["days_left"], "price_usd": float(order["price"])})
    O.step(tid, "user_notified", f"Asked you: return the {order['item_name']} before {deadline:%b %-d}?",
           reason="Keeping or returning is your preference, so Snapback asks once.",
           inputs={"approval_id": aid, "question": question}, authorized_by="mandate:return_window_alert_days")
    O.update_task(tid, status="awaiting_user", decision="awaiting_choice",
                  summary=f"{a['days_left']} days left · {money(float(order['price']))}")


@O.on_answer("return_window")
def on_answer(tid: str, aid: str, opt: Dict[str, Any]) -> None:
    t = O.get_task(tid) or {}
    order = db().get("orders", "order_id", t.get("order_id"))
    if not order:
        return
    if opt["id"] == "keep":
        O.set_order_status(order["order_id"], "kept")
        return O.update_task(tid, decision="kept", status="done", summary="You're keeping it; alerts stopped")
    if opt["id"] == "snooze":
        until = (clock.today() + timedelta(days=1)).isoformat()
        return O.update_task(tid, decision="snoozed", status="done", snooze_until=until, summary=f"Reminder set for {until}")
    auth = f"approval:{aid}"
    O.update_task(tid, decision="return", status="executing")
    ret = O.execute_return(tid, order, "no_longer_needed", authorized_by=auth, verified_by=auth)
    if not ret:
        return
    O.verify_email(tid, "rma", ret["rma"], f"Return {ret['rma']}")
    O.update_task(tid, final_summary=f"{order['item_name']} returned before the window closed", amount_usd=ret["refund_amount"])
    O.await_refund(tid, ret["rma"], ret["refund_amount"], f"{money(ret['refund_amount'])} refunded · label saved, drop-off reminder set")
