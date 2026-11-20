"""Photo trigger (generalcontext §6): identify -> match order -> policy -> decide -> act -> replace -> verify.

Matching: the top candidate must clear MATCH_FLOOR (else no_match: nothing is filed) and beat the
runner-up by >= MATCH_MARGIN; near-ties are broken by recent delivery; if still ambiguous the user
gets a top-3 tap (last resort, §5.6). Both were calibrated with real SigLIP; see NOTES.md.

Damage: Claude vision DESCRIBES the photo (damage_assessed); rules.damage_evidence reads that
description, and the cited Senso policy decides the return method (e.g. damaged battery -> in-store).
"""
from __future__ import annotations

import math
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend import clock, rules, verifier
from backend import orchestrator as O
from backend.actions import checkout, merchant_api
from backend.config import DATA_DIR, settings
from backend.flows import replacement
from backend.integrations import llm, senso, sie
from backend.integrations.base import model_label
from backend.integrations.singlestore import db

MATCH_MARGIN = 0.04
MATCH_FLOOR = 0.49     # real photo of the Pulse earbuds 0.546 vs the unrelated fixture's best 0.436 (NOTES.md)
_VISION = ThreadPoolExecutor(max_workers=2, thread_name_prefix="vision")
UPLOADS = DATA_DIR / "uploads"
STORE_NAMES = rules.STORE_NAMES


def start(content: bytes, filename: str) -> str:
    tid, _ = O.create_task("photo", None, title="Snap: identifying the item", status="planned",
                           summary="Photo received · identifying the item…")
    UPLOADS.mkdir(parents=True, exist_ok=True)
    ext = (Path(filename or "photo.png").suffix or ".png").lower()
    path = UPLOADS / f"{tid}{ext}"
    path.write_bytes(content)
    if ext in (".heic", ".heif"):  # iPhone photos: SIE accepts jpeg/png/webp
        jpg = path.with_suffix(".jpg")
        subprocess.run(["sips", "-s", "format", "jpeg", str(path), "--out", str(jpg)], capture_output=True, check=False)
        if jpg.exists():
            path = jpg
    O.update_task(tid, photo_url=f"http://localhost:8000/api/uploads/{path.name}")
    O.run_async(run, tid, str(path), filename or path.name)
    return tid


def _confidence(scores: List[float], tau: float = 0.05) -> int:
    e = [math.exp((s - scores[0]) / tau) for s in scores]
    return round(e[0] / sum(e) * 100)


def run(tid: str, path: str, filename: str) -> None:
    mandate = rules.load_mandate()
    O.step(tid, "task_detected", "Photo received", reason="You snapped a photo of something that broke.",
           inputs={"filename": filename, "bytes": Path(path).stat().st_size}, authorized_by="user",
           track={"trigger": "photo"})
    O.update_task(tid, status="executing")
    vision = _VISION.submit(llm.describe_damage, path)      # runs while the photo is embedded and matched

    # ---- identify ----
    vec, imeta = sie.embed_image(path)
    hits = db().vector_search("orders", "image_embedding", "order_id", vec, k=5)
    orders = {o["order_id"]: o for o in db().select("orders")}
    cands = [{"order_id": oid, "item": orders.get(oid, {}).get("item_name"), "score": round(s, 4)} for oid, s in hits]
    O.step(tid, "photo_identified", f"Photo embedded · compared with {len(orders)} order images",
           reason="The photo was turned into an image embedding and compared with the product images from your order emails.",
           inputs={"candidates": cands, "photo_url": (O.get_task(tid) or {}).get("details", {}).get("photo_url")},
           authorized_by="mandate:auto_return_defective", model=model_label(imeta, sie.model_name("image")),
           latency_ms=imeta["latency_ms"], track={"trigger": "photo"})

    # ---- match (margin-based) ----
    scores = [c["score"] for c in cands]
    margin = round(scores[0] - scores[1], 4) if len(scores) > 1 else 1.0
    floor_ok = bool(scores) and scores[0] >= MATCH_FLOOR
    if not floor_ok:
        best = f"best {cands[0]['order_id']} {scores[0]:.3f}" if cands else "no order images"
        O.step(tid, "order_matched", "No matching order: nothing was filed",
               reason="The photo doesn't look like any product from your order emails, so Snapback won't guess.",
               inputs={"candidates": cands[:3], "match_floor": MATCH_FLOOR},
               rejected=[{"option": f"{c['order_id']} {c['item']}", "reason": f"similarity {c['score']:.3f} < floor {MATCH_FLOOR}"}
                         for c in cands[:3]],
               rules_checked=[rules.check("match.floor", False, f"{best} (needs >= {MATCH_FLOOR})")],
               authorized_by="mandate:auto_return_defective", model=model_label(imeta, sie.model_name("image")))
        O.update_task(tid, status="failed", decision="no_match", title="No matching order",
                      summary="Snapback couldn't match this photo to any of your orders, so it didn't act. Try another photo or tell it in chat.")
        return
    checks = [rules.check("match.floor", True, f"top {cands[0]['order_id']} {scores[0]:.3f} >= {MATCH_FLOOR}"),
              rules.check("match.margin", margin >= MATCH_MARGIN,
                          f"top {cands[0]['order_id']} {scores[0]:.3f} vs next {cands[1]['order_id']} {scores[1]:.3f}: "
                          f"margin {margin:.3f} (needs >= {MATCH_MARGIN})")]
    chosen = cands[0]
    if margin < MATCH_MARGIN:
        near = [c for c in cands if scores[0] - c["score"] < MATCH_MARGIN]
        today = clock.today()
        recent = [c for c in near if orders[c["order_id"]].get("delivered_at") and
                  rules._date(orders[c["order_id"]]["delivered_at"]) >= today - timedelta(days=30)]
        checks.append(rules.check("match.tiebreak_recent_delivery", len(recent) == 1,
                                  f"{len(recent)} of {len(near)} near-tied orders delivered in the last 30 days"))
        if len(recent) == 1:
            chosen = recent[0]
        else:
            _assess_damage(tid, vision, filename)
            return _ask_top3(tid, cands[:3], orders, checks)
    order = orders[chosen["order_id"]]
    pct = _confidence(scores)
    ext = order.get("extraction") or {}
    O.update_task(tid, order_id=order["order_id"], title=f"{order['item_name']}: checking the store policy",
                  summary=f"Matched your photo to {order['item_name']} ({order['order_id']})")
    O.step(tid, "order_matched", f"Matched {order['item_name']} · {order['order_id']} · {pct}%",
           reason=f"The photo is closest to the {order['item_name']} from your {STORE_NAMES.get(order['store'], order['store'])} order, well ahead of the next candidate.",
           inputs={"order_id": order["order_id"], "confidence_pct": pct, "margin": margin,
                   "extracted": {k: (ext.get("fields") or {}).get(k) for k in ("merchant", "order_no", "order_date", "price", "ship_zip", "return_by")},
                   "field_sources": ext.get("field_sources"), "gaps": ext.get("gaps")},
           sources=[O.email_source_for_order(order)],
           rejected=[{"option": f"{c['order_id']} {c['item']}", "reason": f"similarity {c['score']:.3f}, {scores[0] - c['score']:.3f} below the match"}
                     for c in cands if c["order_id"] != order["order_id"]][:3],
           rules_checked=checks, authorized_by="mandate:auto_return_defective",
           model=ext.get("model") or "", track={"store": order["store"], "confidence": pct})
    _assess_damage(tid, vision, filename, order)

    after_match(tid, order, mandate)


def _assess_damage(tid: str, vision: Any, filename: str, order: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """damage_assessed: the vision model's description is evidence; rules read it."""
    try:
        desc, dmeta = vision.result(timeout=40)
    except Exception as e:  # never block the flow on the evidence step
        desc, dmeta = {"summary": "not assessed (vision error)", "damage": []}, {"model": "mock:llm", "error": str(e)[:200]}
    ev = rules.damage_evidence(desc)
    t = O.get_task(tid) or {}
    photo_url = (t.get("details") or {}).get("photo_url")
    O.step(tid, "damage_assessed", f"Damage: {desc.get('summary')}" if ev["assessed"] else "Damage: not assessed",
           reason=("A vision model described what's visibly wrong. That description is evidence only; "
                   "the store policy and Snapback's rules decide what happens."),
           inputs={"description": desc, "evidence": {k: ev[k] for k in ("physical_damage", "battery_damage")},
                   "item": order["item_name"] if order else None, "error": dmeta.get("error")},
           sources=[{"doc": "Your photo", "section": filename, "url": photo_url, "retrieved_at": clock.iso(clock.now())}],
           rules_checked=ev["rules"], authorized_by="mandate:auto_return_defective", model=dmeta.get("model", ""),
           cost_usd=dmeta.get("cost_usd"), latency_ms=dmeta.get("latency_ms"))
    O.update_task(tid, damage={"summary": desc.get("summary"), "assessed": ev["assessed"],
                               "physical_damage": ev["physical_damage"], "battery_damage": ev["battery_damage"]})
    return ev


def after_match(tid: str, order: Dict[str, Any], mandate: Dict[str, Any]) -> None:
    """Policy (Senso) -> rules -> act. Shared by the photo flow, the top-3 card and the chat trigger."""
    # ---- policy + reviews (Senso) ----
    facts, summary_cite, smeta = senso.policy_summary(order["store"])
    clause_res, _ = senso.query("returns defective items return window refund", store=order["store"]) if facts else ({}, None)
    clause = next((c for c in clause_res.get("citations", []) if "summary" not in c["section"].lower()), None) if facts else None
    sources = O.senso_source(clause) + O.senso_source(summary_cite)
    if facts:
        decision_line = (f"{STORE_NAMES.get(order['store'])} policy: {facts.get('return_window_days')}-day returns · "
                         f"{int(facts.get('warranty_days', 0)) // 365 or facts.get('warranty_days')}"
                         f"{'-year' if int(facts.get('warranty_days', 0)) >= 365 else '-day'} warranty")
    else:
        decision_line = f"No verified policy found for {STORE_NAMES.get(order['store'], order['store'])}"
    O.step(tid, "policy_retrieved", decision_line,
           reason="Store rules come only from the policy documents in Senso, quoted with their section.",
           inputs={"facts": facts}, sources=sources, rules_checked=[rules.verified_policy(facts, order["store"])],
           authorized_by="mandate:auto_return_defective", model=model_label(smeta, "senso:search/context"),
           latency_ms=smeta.get("latency_ms"), track={"store": order["store"]})

    # ---- damage evidence -> return method (cited policy decides) ----
    damage = ((O.get_task(tid) or {}).get("details") or {}).get("damage") or {}
    method = {"method": "standard", "rules": [], "rejected": []}
    if facts and damage.get("battery_damage"):
        bres, _ = senso.query("damaged swollen exposed lithium battery return mail in-store drop-off battery-safe label",
                              store=order["store"])
        battery_clause = next((c for c in bres.get("citations", []) if "batter" in c["section"].lower()), None)
        method = rules.choose_return_method(facts, True, battery_clause)
        sources = O.senso_source(battery_clause) + sources

    # ---- decide (rules) ----
    d = rules.decide_defect(order, facts, mandate)
    template = {
        "return_and_replace": f"The {order['item_name']} is still inside the return window and defective, so Snapback returns it for a full refund and orders a working replacement.",
        "warranty_claim": "The return window has closed but the warranty still covers defects, so Snapback files a warranty claim.",
        "buy_fix": "Neither the return window nor the warranty covers this, so a replacement would cost money: Snapback asks you first.",
        "do_not_act": "Snapback found no verified store policy, so it will not act on its own and flags this for you.",
    }[d["decision"]]
    reason, lmeta = llm.explain(d["decision"], {"template": template, "item": order["item_name"], "facts": facts,
                                                "rules": d["rules"]})
    label = {"return_and_replace": "Return + replacement", "warranty_claim": "Warranty claim",
             "buy_fix": "Buy a replacement (needs your OK)", "do_not_act": "Do not act: no verified policy"}[d["decision"]]
    returning = d["decision"] == "return_and_replace"
    if returning and method["method"] != "standard":
        label += f" · {rules.RETURN_METHOD_LABELS[method['method']]} (damaged battery)"
        reason += (f" The photo shows a damaged battery and the policy forbids standard return mail, so it goes back by "
                   f"{rules.RETURN_METHOD_LABELS[method['method']]}.")
    O.step(tid, "decision_made", label, reason=reason,
           inputs={"decision": d["decision"], "return_method": method["method"] if returning else None,
                   "return_reason": "damaged" if damage.get("physical_damage") else "defective",
                   "damage": damage.get("summary")},
           sources=sources, rejected=d["rejected"] + (method["rejected"] if returning else []),
           rules_checked=d["rules"] + (method["rules"] if returning else []), authorized_by=d["authorized_by"],
           model=lmeta["model"], cost_usd=lmeta.get("cost_usd"), latency_ms=lmeta.get("latency_ms"),
           track={"decision": d["decision"], "store": order["store"]})
    O.update_task(tid, decision=d["decision"], authorized_by=d["authorized_by"], title=label)

    if d["decision"] == "return_and_replace":
        return _return_and_replace(tid, order, mandate, method=method["method"],
                                   reason_code="damaged" if damage.get("physical_damage") else "defective")
    if d["decision"] == "warranty_claim":
        return _warranty(tid, order, mandate)
    if d["decision"] == "buy_fix":
        return _ask_buy(tid, order, mandate)
    O.update_task(tid, status="failed", summary=f"No verified policy for {STORE_NAMES.get(order['store'], order['store'])}: Snapback did not act and flagged it for you.")


def _return_and_replace(tid: str, order: Dict[str, Any], mandate: Dict[str, Any], method: str = "standard",
                        reason_code: str = "defective") -> None:
    persona_ref = f"persona:{mandate.get('_persona_inquiry_id')}"
    ret = O.execute_return(tid, order, reason_code, authorized_by="mandate:auto_return_defective", verified_by=persona_ref,
                           return_method=method)
    if not ret:
        return
    # ---- replacement ----
    O.update_task(tid, summary="Return filed · choosing a replacement…")
    r = replacement.rank(order, mandate)
    chosen = r["chosen"]
    sources = O.senso_source(r.get("review_cite"))
    if not chosen:
        ask = r.get("ask")
        O.step(tid, "replacement_ranked",
               f"Needs your OK: {ask['name']} · ${float(ask['price']):.2f} is over your limits" if ask else "No replacement fits your limits",
               reason=("The best replacement costs more than your mandate allows, so buying it needs your one-tap approval."
                       if ask else "Every candidate was out of stock, broke a spending limit or had poor reviews."),
               inputs={"candidates": r["candidates"], "statsig": r["statsig"]}, sources=sources, rejected=r["rejected"],
               rules_checked=r["rules"], authorized_by="mandate:replacement", model=r["model"])
        if ask:
            return _ask_over_cap(tid, order, ret, ask, mandate)
    else:
        same = chosen.get("sku") == order.get("sku")
        O.step(tid, "replacement_ranked", f"Chose {chosen['name']} · ${float(chosen['price']):.2f} · ★{chosen['rating']}",
               reason=("Same item: its reviews are fine and it fits your limits." if same else
                       f"The original has poor reviews, so Snapback picked the best-rated option within your +${(mandate.get('replacement') or {}).get('max_extra_spend_usd', 30)} limit."),
               inputs={"query": r["query"], "candidates": r["candidates"], "statsig": r["statsig"], "strategy": r["strategy"]},
               sources=sources, rejected=r["rejected"], rules_checked=r["rules"], authorized_by="mandate:replacement",
               model=r["model"], track={"sku": chosen["sku"], "variant": r["statsig"].get("variant")})
        buy = checkout.place_order(chosen["store"], chosen["sku"], order.get("ship_zip") or "", idempotency_key=f"buy:{tid}",
                                   verified_by=persona_ref, max_price=float(chosen["price"]))
        if buy["ok"]:
            O.step(tid, "order_placed", f"Ordered {chosen['name']} · {buy['order_no']} · ${buy['charged']:.2f}",
                   reason="The browser agent placed the order on the store's checkout with your saved wallet (no card data seen).",
                   inputs={"order_no": buy["order_no"], "sku": chosen["sku"], "idempotency_key": f"buy:{tid}"},
                   sources=[{"doc": "Checkout confirmation", "section": buy["order_no"], "url": buy.get("confirmation_url"),
                             "retrieved_at": clock.iso(clock.now())}],
                   rules_checked=[rules.check("mandate.require_approval_over_usd", buy["charged"] <= float(mandate.get("require_approval_over_usd", 200)),
                                              f"charged ${buy['charged']:.2f}")],
                   authorized_by="mandate:replacement", model="playwright", track={"amount": buy["charged"]})
            O.update_task(tid, replacement_order=buy["order_no"], replacement_name=chosen["name"])
        else:
            O.step(tid, "order_placed", f"Replacement order failed: {buy.get('error')}", reason="Checkout refused the order.",
                   authorized_by="mandate:replacement", model="playwright", verified=False)
    # ---- verify ----
    O.update_task(tid, status="verifying", summary="Verifying with the store's emails…")
    O.verify_email(tid, "rma", ret["rma"], f"Return {ret['rma']}")
    det = (O.get_task(tid) or {}).get("details") or {}
    if det.get("replacement_order"):
        O.verify_email(tid, "order_no", det["replacement_order"], f"Replacement order {det['replacement_order']}")
    outcome = f"{rules.money(ret['refund_amount'])} refunded" + (f" · {det['replacement_name']} ordered" if det.get("replacement_name") else "")
    O.update_task(tid, final_summary=f"Photo of broken {order['item_name']} → return filed" +
                  (f", {det['replacement_name']} ordered" if det.get("replacement_name") else ""),
                  amount_usd=ret["refund_amount"])
    O.await_refund(tid, ret["rma"], ret["refund_amount"], outcome)


def _ask_over_cap(tid: str, order: Dict[str, Any], ret: Dict[str, Any], c: Dict[str, Any], mandate: Dict[str, Any]) -> None:
    """Return is done; the replacement is over the mandate's limits -> one-tap card (§5.6)."""
    O.verify_email(tid, "rma", ret["rma"], f"Return {ret['rma']}")
    txn = verifier.find_refund(ret["rma"], timeout_s=settings.await_refund_seconds)
    if txn:
        O.step(tid, "refund_received", f"{rules.money(txn['amount'])} posted to original payment",
               reason="The bank ledger shows the refund for the return.", sources=[verifier.bank_source(txn)],
               authorized_by="verifier", verified=True)
    cap = float(mandate.get("require_approval_over_usd", 200))
    opts = [{"id": "buy", "label": f"Buy {c['name']}", "action": "execute", "net_savings_usd": None,
             "detail": f"${float(c['price']):.2f} · ★{c['rating']} · over your ${cap:.0f} auto-buy limit"},
            {"id": "skip", "label": "Skip the replacement", "action": "dismiss", "detail": "Just keep the refund"}]
    aid = O.create_approval(tid, f"Your {order['item_name']} return is done. Buy {c['name']} (${float(c['price']):.2f}) as a replacement?",
                            opts, "buy")
    O.step(tid, "user_notified", f"Asked you before spending ${float(c['price']):.2f}",
           reason="Purchases over your auto-buy limit always need a Persona-verified tap.",
           inputs={"approval_id": aid, "sku": c["sku"]}, authorized_by="mandate:require_approval_over_usd")
    O.update_task(tid, status="awaiting_user", decision="return_done_replacement_needs_ok", over_cap_sku=c["sku"],
                  amount_usd=txn["amount"] if txn else ret["refund_amount"],
                  outcome=(f"{rules.money(txn['amount'])} refunded" if txn else None),
                  summary=f"Return done · replacement {c['name']} needs your OK")


def _warranty(tid: str, order: Dict[str, Any], mandate: Dict[str, Any]) -> None:
    key = f"warranty:{order['order_id']}"
    O.update_task(tid, status="executing", summary="Filing a warranty claim…")
    res = merchant_api.file_warranty_claim(order["store"], order["order_id"], order.get("ship_zip") or "",
                                           "Stopped working (reported with a photo via Snapback)", idempotency_key=key,
                                           verified_by=f"persona:{mandate.get('_persona_inquiry_id')}")
    if not res.get("ok"):
        return O.fail(tid, f"Warranty claim rejected: {res.get('error')}", authorized_by="mandate:auto_return_defective")
    clause_res, _ = senso.query("warranty defects materials workmanship claim replacement", store=order["store"])
    clause = next((c for c in clause_res.get("citations", []) if "warrant" in c["section"].lower()), None)
    O.step(tid, "claim_filed", f"Warranty claim {res['claim_id']} filed · replacement ships by {res['ship_by']}",
           reason="The store's warranty covers the defect, so Snapback filed the claim through its support endpoint.",
           inputs={"claim_id": res["claim_id"], "idempotency_key": key}, sources=O.senso_source(clause),
           authorized_by="mandate:auto_return_defective", model="merchant-api", track={"store": order["store"]})
    O.set_order_status(order["order_id"], "claimed")
    e = O.verify_email(tid, "claim_id", res["claim_id"], f"Warranty claim {res['claim_id']}")
    if e:
        O.update_task(tid, status="done", outcome=f"Warranty replacement ships by {res['ship_by']}",
                      amount_usd=float(order["price"]), summary=f"Broken {order['item_name']} → warranty claim approved")


def _ask_top3(tid: str, top: List[Dict[str, Any]], orders: Dict[str, Any], checks: List[Dict[str, Any]]) -> None:
    opts = [{"id": c["order_id"], "label": orders[c["order_id"]]["item_name"], "action": "execute",
             "detail": f"{STORE_NAMES.get(orders[c['order_id']]['store'])} · {c['order_id']}", "net_savings_usd": None}
            for c in top] + [{"id": "none", "label": "None of these", "action": "dismiss", "detail": "Not one of my orders"}]
    aid = O.create_approval(tid, "Which of your orders is in the photo?", opts, None)
    O.step(tid, "user_notified", "Asked you to pick the item (top 3)", reason="The photo matched several orders too closely to choose safely.",
           inputs={"approval_id": aid, "options": [o["id"] for o in opts]}, rules_checked=checks, authorized_by="mandate:auto_return_defective")
    O.update_task(tid, status="awaiting_user", title="Which item is this?", summary="Tap the order that matches your photo")


def _ask_buy(tid: str, order: Dict[str, Any], mandate: Dict[str, Any]) -> None:
    r = replacement.rank(order, mandate)
    c = r["chosen"]
    if not c:
        return O.update_task(tid, status="expired", summary="Not covered, and no replacement fits your limits")
    opts = [{"id": "buy", "label": f"Buy {c['name']}", "detail": f"${float(c['price']):.2f} · ★{c['rating']}", "action": "execute",
             "net_savings_usd": None},
            {"id": "ignore", "label": "Ignore", "detail": "Do nothing", "action": "dismiss"}]
    aid = O.create_approval(tid, f"{order['item_name']} isn't covered anymore. Buy a replacement?", opts, "buy")
    O.step(tid, "user_notified", "Asked before spending money", reason="Not covered by return or warranty, so a purchase needs your OK.",
           inputs={"approval_id": aid}, authorized_by="mandate:replacement")
    O.update_task(tid, status="awaiting_user", amount_usd=float(c["price"]))


@O.on_answer("photo")
def _photo_answer(tid: str, aid: str, opt: Dict[str, Any]) -> None:
    """Top-3 pick or buy-fix approval for a photo task."""
    t = O.get_task(tid) or {}
    mandate = rules.load_mandate()
    if opt["action"] != "execute":
        if (t.get("details") or {}).get("over_cap_sku"):
            O.update_task(tid, status="done", summary="Return done · you skipped the replacement")
        else:
            O.update_task(tid, decision="ignored", status="done", summary="You dismissed this")
        return
    if opt["id"] == "buy" and t.get("order_id"):
        order = db().get("orders", "order_id", t["order_id"])
        sku = (t.get("details") or {}).get("over_cap_sku")
        if sku:
            row = db().get("catalog", "sku", sku)
            info = merchant_api.current_price(row["store"], sku) or {}
            c = {**row, "price": float(info.get("price", row["price"]))}
        else:
            c = replacement.rank(order, mandate)["chosen"]
        buy = checkout.place_order(c["store"], c["sku"], order.get("ship_zip") or "", idempotency_key=f"buy:{tid}",
                                   verified_by=f"approval:{aid}", max_price=float(c["price"]))
        if buy["ok"]:
            O.step(tid, "order_placed", f"Ordered {c['name']} · {buy['order_no']} · ${buy['charged']:.2f}",
                   reason="You approved the purchase with one tap.", inputs={"order_no": buy["order_no"], "sku": c["sku"]},
                   authorized_by=f"approval:{aid}", model="playwright")
            O.verify_email(tid, "order_no", buy["order_no"], f"Order {buy['order_no']}")
            prev = (t.get("details") or {}).get("outcome")
            O.update_task(tid, status="done", outcome=(f"{prev} · " if prev else "") + f"{c['name']} ordered",
                          decision=t.get("decision") if sku else "buy_fix")
        else:
            O.fail(tid, f"Purchase failed: {buy.get('error')}", authorized_by=f"approval:{aid}")
        return
    # the user picked the matching order from the top-3 card: continue the normal flow from the match
    order = db().get("orders", "order_id", opt["id"])
    if order:
        O.step(tid, "order_matched", f"Matched {order['item_name']} · {order['order_id']} · picked by you",
               reason="You confirmed which order is in the photo.", sources=[O.email_source_for_order(order)],
               authorized_by=f"approval:{aid}")
        after_match(tid, order, mandate)
