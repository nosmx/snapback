"""Duplicate orders (§5.1): same SKU ordered twice on the same day -> notify and ask; on yes, cancel the
extra order if it hasn't shipped (or return it if delivered). Orders Snapback placed itself are ignored."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional

from backend import rules
from backend import orchestrator as O
from backend.actions import merchant_api
from backend.integrations.singlestore import db

money = rules.money


def _snapback_orders() -> set:
    placed = set()
    for e in db().select("audit_log", {"step": "order_placed"}):
        inp = e.get("inputs") or {}
        if isinstance(inp, dict) and inp.get("order_no"):
            placed.add(inp["order_no"])
    return placed


def detect_all(orders: List[Dict[str, Any]], mandate: Dict[str, Any]) -> List[str]:
    mine = _snapback_orders()
    groups: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    for o in orders:
        if o.get("status") in ("active", "in_transit") and o.get("sku") and o.get("ordered_at") and o["order_id"] not in mine:
            groups[(o["sku"], str(o["ordered_at"])[:10])].append(o)
    out = []
    for (sku, day), group in groups.items():
        if len(group) < 2:
            continue
        group.sort(key=lambda o: o["order_id"])
        keep, extra = group[0], group[-1]
        tid, created = O.create_task("duplicate", extra["order_id"], idempotency_key=f"duplicate:{sku}:{day}",
                                     title=f"Duplicate order: {extra['item_name']}", amount_usd=float(extra["price"]),
                                     summary=f"Ordered twice on {day}: {keep['order_id']} and {extra['order_id']}")
        if created:
            O.run_async(run, tid, keep, extra)
        out.append(tid)
    return out


def run(tid: str, keep: Dict[str, Any], extra: Dict[str, Any]) -> None:
    day = str(extra["ordered_at"])[:10]
    O.step(tid, "task_detected", f"{extra['item_name']} ordered twice on {day}",
           reason="Two orders for the same item on the same day usually means an accidental double purchase.",
           inputs={"orders": [keep["order_id"], extra["order_id"]], "sku": extra["sku"]},
           sources=[O.email_source_for_order(keep), O.email_source_for_order(extra)],
           rules_checked=[rules.check("duplicate.same_sku_same_day", True, f"{keep['order_id']} and {extra['order_id']}: {extra['sku']} on {day}")],
           authorized_by="background_loop", track={"trigger": "duplicate", "store": extra["store"]})
    shipped = bool(extra.get("delivered_at"))
    opts = [{"id": "cancel_extra", "label": "Cancel the extra one" if not shipped else "Return the extra one",
             "action": "execute", "net_savings_usd": float(extra["price"]),
             "detail": f"{extra['order_id']} · {money(float(extra['price']))} back to your card"},
            {"id": "keep_both", "label": "Keep both", "action": "dismiss", "detail": "I meant to buy two"}]
    aid = O.create_approval(tid, f"You ordered {extra['item_name']} twice today. Cancel the extra order?", opts, "cancel_extra")
    O.step(tid, "user_notified", f"Asked you: cancel {extra['order_id']}?", reason="Only you know if two were intended.",
           inputs={"approval_id": aid}, authorized_by="mandate:duplicate_check")
    O.update_task(tid, status="awaiting_user", decision="awaiting_choice")


@O.on_answer("duplicate")
def on_answer(tid: str, aid: str, opt: Dict[str, Any]) -> None:
    t = O.get_task(tid) or {}
    extra = db().get("orders", "order_id", t.get("order_id"))
    if opt["action"] != "execute" or not extra:
        return O.update_task(tid, decision="kept", status="done", summary="You're keeping both orders")
    auth = f"approval:{aid}"
    O.update_task(tid, decision="cancel_extra", status="executing")
    if extra.get("delivered_at"):
        ret = O.execute_return(tid, extra, "no_longer_needed", authorized_by=auth, verified_by=auth)
        if ret:
            O.verify_email(tid, "rma", ret["rma"], f"Return {ret['rma']}")
            O.await_refund(tid, ret["rma"], ret["refund_amount"], f"{money(ret['refund_amount'])} refunded for the duplicate")
        return
    key = f"cancel:{extra['order_id']}"
    res = merchant_api.cancel_order(extra["store"], extra["order_id"], extra.get("ship_zip") or "", key, verified_by=auth)
    if not res.get("ok"):
        return O.fail(tid, f"Cancellation refused: {res.get('error')}", authorized_by=auth)
    O.step(tid, "claim_filed", f"Order {extra['order_id']} cancelled ({res['claim_id']}) · refund {money(res['amount'])}",
           reason="The extra order hadn't shipped, so Snapback cancelled it for a full refund.",
           inputs={"claim_id": res["claim_id"], "idempotency_key": key}, authorized_by=auth, model="merchant-api")
    O.set_order_status(extra["order_id"], "returned")
    O.verify_email(tid, "claim_id", res["claim_id"], f"Cancellation {res['claim_id']}")
    O.update_task(tid, final_summary=f"Duplicate {extra['item_name']} order cancelled", amount_usd=res["amount"])
    O.await_refund(tid, res["claim_id"], res["amount"], f"{money(res['amount'])} refunded for the duplicate order")
