"""Missing / late packages: carrier says lost/exception, or the ETA passed by 2+ days -> auto claim."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, Optional

from backend import clock, rules
from backend import orchestrator as O
from backend.actions import merchant_api
from backend.integrations import senso
from backend.integrations.base import model_label

money = rules.money


def detect(order: Dict[str, Any], mandate: Dict[str, Any]) -> Optional[str]:
    if order.get("status") != "in_transit" or not order.get("tracking_number"):
        return None
    if mandate.get("allowed_stores") and order.get("store") not in mandate["allowed_stores"]:
        return None
    tr = merchant_api.track(order["tracking_number"])
    if not tr:
        return None
    late = bool(tr.get("eta")) and clock.today() > date.fromisoformat(tr["eta"]) + timedelta(days=2)
    if tr["status"] not in ("lost", "exception") and not late:
        return None
    tid, created = O.create_task("missing_package", order["order_id"], idempotency_key=f"missing:{order['order_id']}",
                                 title=f"Missing package: {order['item_name']}", amount_usd=float(order["price"]),
                                 summary=f"Carrier status: {tr['status']}")
    if created:
        O.run_async(run, tid, order, tr, late)
    return tid


def run(tid: str, order: Dict[str, Any], tr: Dict[str, Any], late: bool) -> None:
    mandate = rules.load_mandate()
    O.step(tid, "task_detected", f"Carrier reports '{tr['status']}' for {order['tracking_number']}",
           reason="The background check saw your package marked lost by the carrier.",
           inputs={"tracking": tr}, sources=[{"doc": "Carrier tracking", "section": order["tracking_number"],
                                              "url": tr.get("url"), "retrieved_at": clock.iso(clock.now())}],
           rules_checked=[rules.check("carrier.lost_or_late", True, f"status {tr['status']}, eta {tr.get('eta')}, late={late}")],
           authorized_by="background_loop", track={"trigger": "missing_package", "store": order["store"]})
    facts, cite, smeta = senso.policy_summary(order["store"])
    O.step(tid, "policy_retrieved", "Store policy verified" if facts else "No verified policy",
           sources=O.senso_source(cite), rules_checked=[rules.verified_policy(facts, order["store"])],
           authorized_by="background_loop", model=model_label(smeta, "senso:search/context"))
    auto = bool(mandate.get("auto_missing_package_claim"))
    checks = [rules.check("mandate.auto_missing_package_claim", auto, f"auto_missing_package_claim={auto}"),
              rules.store_allowed(order["store"], mandate)]
    if not (auto and facts):
        O.step(tid, "decision_made", "Not filing automatically", rules_checked=checks, authorized_by="mandate:auto_missing_package_claim")
        return O.update_task(tid, status="failed", summary="Snapback did not file a claim automatically")
    O.step(tid, "decision_made", "File a missing-package claim",
           reason="Your rules let Snapback claim lost packages automatically.", rules_checked=checks,
           rejected=[{"option": "wait", "reason": "Carrier already marked the package lost"}],
           authorized_by="mandate:auto_missing_package_claim", track={"decision": "missing_claim"})
    O.update_task(tid, decision="missing_claim", status="executing")
    key = f"claim:{order['order_id']}"
    res = merchant_api.file_missing_claim(order["store"], order["order_id"], order.get("ship_zip") or "", key,
                                          verified_by="mandate:auto_missing_package_claim")
    if not res.get("ok"):
        return O.fail(tid, f"Claim refused: {res.get('error')}", authorized_by="mandate:auto_missing_package_claim")
    O.step(tid, "claim_filed", f"Claim {res['claim_id']} filed · refund {money(res['amount'])}",
           reason="Filed through the store's support endpoint with order number and ZIP.",
           inputs={"claim_id": res["claim_id"], "idempotency_key": key}, authorized_by="mandate:auto_missing_package_claim",
           model="merchant-api", track={"amount": res["amount"]})
    O.set_order_status(order["order_id"], "claimed")
    O.verify_email(tid, "claim_id", res["claim_id"], f"Claim {res['claim_id']}")
    O.update_task(tid, final_summary=f"Lost {order['item_name']} → claim filed, refund issued", amount_usd=res["amount"])
    O.await_refund(tid, res["claim_id"], res["amount"], f"{money(res['amount'])} refunded for the lost package")
