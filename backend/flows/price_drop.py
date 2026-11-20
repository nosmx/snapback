"""Price drops (§5.1, §5.3). Minor -> automatic price adjustment (if policy allows).
Major -> one decision card with pre-computed options; after the tap everything runs autonomously.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from backend import clock, rules
from backend import orchestrator as O
from backend.actions import checkout, merchant_api
from backend.config import settings
from backend.integrations import senso
from backend.integrations.base import model_label
from backend.integrations.singlestore import db

M = settings.merchant_base_url
money = rules.money


def detect(order: Dict[str, Any], mandate: Dict[str, Any], force: bool = False) -> Optional[str]:
    if order.get("status") != "active" or not order.get("delivered_at") or not order.get("sku"):
        return None
    if mandate.get("allowed_stores") and order.get("store") not in mandate["allowed_stores"]:
        return None
    info = merchant_api.current_price(order["store"], order["sku"])
    if not info:
        return None
    cur, paid = float(info["price"]), float(order["price"])
    if cur >= paid:
        return None
    c = rules.classify_price_drop(paid, cur, mandate)
    major = c["severity"] == "major"
    tid, created = O.create_task(
        "price_drop_major" if major else "price_drop_minor", order["order_id"],
        idempotency_key=f"pricedrop:{order['order_id']}:{cur:.2f}",
        title=f"{order['item_name']} dropped {c['pct']:.0f}%", amount_usd=c["diff"],
        summary=f"{money(paid)} → {money(cur)} at {order['store']}")
    if created:
        O.run_async(run_major if major else run_minor, tid, order, cur, c, info)
    return tid


def _detected(tid: str, order: Dict[str, Any], cur: float, c: Dict[str, Any], info: Dict[str, Any]) -> None:
    O.step(tid, "task_detected", f"Price dropped {money(float(order['price']))} → {money(cur)} (−{c['pct']}%)",
           reason=f"The background check saw the {order['item_name']} selling for less than you paid.",
           inputs={"paid": float(order["price"]), "current": cur, "drop_usd": c["diff"], "drop_pct": c["pct"]},
           sources=[{"doc": "Store price feed", "section": order["sku"], "url": info.get("url") or f"{M}/s/{order['store']}",
                     "retrieved_at": clock.iso(clock.now())}, O.email_source_for_order(order)],
           rules_checked=[c["rule"]], authorized_by="background_loop",
           track={"trigger": "price_drop_" + c["severity"], "store": order["store"]})


def _policy(tid: str, order: Dict[str, Any]):
    facts, cite, smeta = senso.policy_summary(order["store"])
    clause_res, _ = senso.query("price adjustment price drop refund the difference", store=order["store"])
    clause = next((x for x in clause_res.get("citations", []) if "summary" not in x["section"].lower()), None)
    adj = "price adjustments within " + f"{facts.get('price_adjustment_window_days')} days" if facts and facts.get("price_adjustment_allowed") else "no price adjustments"
    O.step(tid, "policy_retrieved",
           (f"Policy: {adj} · {facts.get('return_window_days')}-day returns" if facts else "No verified policy found"),
           reason="Price-adjustment and return rules come from the store's policy in Senso.",
           inputs={"facts": facts}, sources=O.senso_source(clause) + O.senso_source(cite),
           rules_checked=[rules.verified_policy(facts, order["store"])], authorized_by="background_loop",
           model=model_label(smeta, "senso:search/context"), latency_ms=smeta.get("latency_ms"))
    return facts


def run_minor(tid: str, order: Dict[str, Any], cur: float, c: Dict[str, Any], info: Dict[str, Any]) -> None:
    mandate = rules.load_mandate()
    _detected(tid, order, cur, c, info)
    facts = _policy(tid, order)
    if not facts:
        return O.update_task(tid, status="failed", summary="No verified policy: Snapback did not act")
    opts = rules.price_drop_options(order, cur, facts, mandate)
    auto = bool((mandate.get("price_drop") or {}).get("auto_adjust_minor"))
    can_adjust = any(o["id"] == "price_match" for o in opts["options"])
    checks = opts["rules"] + [rules.check("mandate.price_drop.auto_adjust_minor", auto, f"auto_adjust_minor={auto}")]
    if not (auto and can_adjust):
        O.step(tid, "decision_made", "Information only: no automatic option", rules_checked=checks,
               rejected=opts["rejected"], authorized_by="mandate:price_drop.auto_adjust_minor")
        return O.update_task(tid, status="done", decision="info_only", summary=f"Price dropped to {money(cur)}; no policy option applies")
    O.step(tid, "decision_made", f"Auto price adjustment +{money(c['diff'])}",
           reason=f"A minor drop inside the {facts.get('price_adjustment_window_days')}-day adjustment window: your rules let Snapback claim it automatically.",
           rules_checked=checks, rejected=opts["rejected"], authorized_by="mandate:price_drop.auto_adjust_minor",
           track={"decision": "price_adjustment"})
    O.update_task(tid, decision="price_adjustment", status="executing", title=f"Price adjustment: {order['item_name']}")
    _adjust(tid, order, cur, "mandate:price_drop.auto_adjust_minor")


def _adjust(tid: str, order: Dict[str, Any], cur: float, authorized_by: str) -> None:
    key = f"adjust:{order['order_id']}:{cur:.2f}"
    res = merchant_api.request_price_adjustment(order["store"], order["order_id"], order.get("ship_zip") or "", key,
                                                verified_by=authorized_by)
    if not res.get("ok"):
        return O.fail(tid, f"Price adjustment refused: {res.get('error')}", authorized_by=authorized_by)
    O.step(tid, "adjustment_filed", f"Adjustment {res['adjustment_id']} filed · +{money(res['amount'])}",
           reason="Snapback asked the store to refund the difference through its price-adjustment endpoint.",
           inputs={"adjustment_id": res["adjustment_id"], "idempotency_key": key, "already": res.get("already", False)},
           authorized_by=authorized_by, model="merchant-api", track={"amount": res["amount"]})
    O.verify_email(tid, "adjustment_id", res["adjustment_id"], f"Price adjustment {res['adjustment_id']}")
    O.update_task(tid, final_summary=f"{order['item_name']} price drop → {money(res['amount'])} adjustment claimed",
                  amount_usd=res["amount"])
    O.await_refund(tid, res["adjustment_id"], res["amount"], f"{money(res['amount'])} price adjustment refunded")


def run_major(tid: str, order: Dict[str, Any], cur: float, c: Dict[str, Any], info: Dict[str, Any]) -> None:
    mandate = rules.load_mandate()
    _detected(tid, order, cur, c, info)
    facts = _policy(tid, order)
    if not facts:
        return O.update_task(tid, status="failed", summary="No verified policy: Snapback did not act")
    opts = rules.price_drop_options(order, cur, facts, mandate)
    executable = [o for o in opts["options"] if o["action"] == "execute"]
    line = " · ".join(f"{o['label'].lower()} +{money(o['net_savings_usd'])}" for o in executable) or "no eligible option"
    O.step(tid, "options_computed", line[:1].upper() + line[1:],
           reason="Net savings computed from the cited policy: price difference minus restocking and return shipping.",
           inputs={"options": opts["options"], "return_rebuy_math": opts["math"], "recommended": opts["recommended"]},
           rules_checked=opts["rules"], rejected=opts["rejected"], authorized_by="mandate:price_drop.major_if")
    if opts["info_only"]:
        O.step(tid, "user_notified", "Told you about the drop (no option applies)", authorized_by="mandate:price_drop.major_if")
        return O.update_task(tid, status="done", decision="info_only", summary="Price dropped, but no policy option applies")
    question = f"Your {order['item_name']} dropped from {money(float(order['price']))} to {money(cur)}. Want the difference back?"
    card_opts = [{k: v for k, v in o.items() if k != "math"} for o in opts["options"]]
    aid = O.create_approval(tid, question, card_opts, opts["recommended"],
                            price_math={"paid_usd": float(order["price"]), "current_usd": cur, "drop_pct": c["pct"]})
    rec = next(o for o in executable if o["id"] == opts["recommended"])
    O.step(tid, "user_notified", f"Asked you: {rec['label'].lower()} recommended (+{money(rec['net_savings_usd'])})",
           reason="A major drop needs your choice; Snapback never acts on one without it.",
           inputs={"approval_id": aid, "question": question}, authorized_by="mandate:price_drop.major_if",
           track={"trigger": "price_drop_major"})
    O.update_task(tid, status="awaiting_user", decision="awaiting_choice", amount_usd=rec["net_savings_usd"],
                  summary=f"{money(float(order['price']))} → {money(cur)} · tap to get up to {money(rec['net_savings_usd'])} back")


@O.on_answer("price_drop_major")
def on_major_answer(tid: str, aid: str, opt: Dict[str, Any]) -> None:
    t = O.get_task(tid) or {}
    order = db().get("orders", "order_id", t.get("order_id"))
    if opt.get("action") != "execute" or not order:
        return O.update_task(tid, decision="ignored", status="done", summary="You chose to ignore the drop")
    auth = f"approval:{aid}"
    info = merchant_api.current_price(order["store"], order["sku"]) or {}
    cur = float(info.get("price", order["price"]))
    still = cur < float(order["price"])
    O.step(tid, "price_rechecked", f"Still {money(cur)}" if still else f"Price is back to {money(cur)}: not executed",
           reason="Prices can change while you decide, so Snapback re-checked before acting.",
           sources=[{"doc": "Store price feed", "section": order["sku"], "url": info.get("url"), "retrieved_at": clock.iso(clock.now())}],
           rules_checked=[rules.check("price_still_lower", still, f"paid {money(float(order['price']))}, now {money(cur)}")],
           authorized_by=auth)
    if not still:
        return O.update_task(tid, status="expired", summary="The lower price disappeared before Snapback could act")
    O.update_task(tid, decision=opt["id"], status="executing")
    if opt["id"] == "price_match":
        return _adjust(tid, order, cur, auth)
    if opt["id"] == "return_rebuy":
        buy = checkout.place_order(order["store"], order["sku"], order.get("ship_zip") or "", idempotency_key=f"rebuy:{order['order_id']}",
                                   verified_by=auth, max_price=cur)
        if not buy["ok"]:
            return O.fail(tid, f"Re-buy failed: {buy.get('error')}", authorized_by=auth)
        O.step(tid, "order_placed", f"New order {buy['order_no']} at {money(buy['charged'])} (placed first to lock the price)",
               reason="Snapback buys at the new price before returning the original, so the lower price can't slip away.",
               inputs={"order_no": buy["order_no"], "idempotency_key": f"rebuy:{order['order_id']}"},
               sources=[{"doc": "Checkout confirmation", "section": buy["order_no"], "url": buy.get("confirmation_url"),
                         "retrieved_at": clock.iso(clock.now())}], authorized_by=auth, model="playwright")
        ret = O.execute_return(tid, order, "better_price", authorized_by=auth, verified_by=auth)
        if not ret:
            return O.update_task(tid, status="failed", summary=f"New order {buy['order_no']} placed but the return failed: retrying via support")
        O.verify_email(tid, "order_no", buy["order_no"], f"New order {buy['order_no']}")
        O.verify_email(tid, "rma", ret["rma"], f"Return {ret['rma']}")
        net = round(ret["refund_amount"] - buy["charged"], 2)
        O.update_task(tid, final_summary=f"Re-bought at {money(buy['charged'])}, returned the original", amount_usd=net,
                      final_amount=net)
        O.await_refund(tid, ret["rma"], ret["refund_amount"], f"Re-bought at {money(buy['charged'])} · {money(ret['refund_amount'])} refund (net +{money(net)})")
