"""Chat trigger (§5.1): "the blender died" -> intent classifier -> match against order history ->
the same policy/rules/act path as the photo flow. Matching is checked by code, not by the LLM."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from backend import rules
from backend import orchestrator as O
from backend.flows.photo import STORE_NAMES, after_match
from backend.integrations import llm
from backend.integrations.singlestore import db
from backend.safety import detect_injection

STOP = {"the", "a", "an", "my", "our", "it", "is", "and", "or", "of", "to", "just", "old", "new", "anymore",
        "won't", "wont", "turn", "on", "off", "stopped", "working", "died", "broke", "broken", "dead", "with"}


def _match(message: str, orders: List[Dict[str, Any]]) -> List[Tuple[Dict[str, Any], int]]:
    words = set(re.findall(r"[a-z0-9]+", message.lower())) - STOP
    scored = []
    for o in orders:
        name = set(re.findall(r"[a-z0-9]+", (o.get("item_name") or "").lower())) - STOP
        scored.append((o, len(words & name)))
    return sorted(scored, key=lambda x: -x[1])


def start(message: str) -> str:
    tid, _ = O.create_task("chat", None, title="Chat: understanding your message", status="planned",
                           summary=message[:120])
    O.run_async(run, tid, message)
    return tid


def run(tid: str, message: str) -> None:
    mandate = rules.load_mandate()
    clean, flags = detect_injection(message)
    O.step(tid, "task_detected", f"Message: “{clean[:80]}”", reason="You told Snapback something broke.",
           inputs={"message": clean, "injection_flags": flags}, authorized_by="user", track={"trigger": "chat"})
    O.update_task(tid, status="executing")
    orders = [o for o in db().select("orders") if o.get("status") in ("active", "in_transit")]
    intent, lmeta = llm.classify_intent(clean, orders)
    O.step(tid, "intent_classified", f"Intent: {intent.get('intent', 'other').replace('_', ' ')}",
           reason="The message was classified; matching it to an order is checked by code next.",
           inputs={"intent": intent}, authorized_by="user", model=lmeta["model"], cost_usd=lmeta.get("cost_usd"),
           latency_ms=lmeta.get("latency_ms"))
    if intent.get("intent") not in ("broken_item", "return_request"):
        return O.update_task(tid, status="done", decision="no_action", title="Nothing to do",
                             summary="Snapback didn't find a broken item or return request in that message")
    ranked = _match(clean, orders)
    best, score = ranked[0] if ranked else (None, 0)
    runner = ranked[1][1] if len(ranked) > 1 else 0
    ok = bool(best) and score >= 2 and score > runner
    checks = [rules.check("match.item_name_overlap", ok,
                          f"best {best['order_id'] if best else '-'} shares {score} words with the message; next shares {runner}")]
    if not ok:
        O.step(tid, "order_matched", "Couldn't tell which order you mean", rules_checked=checks, authorized_by="user")
        return O.update_task(tid, status="failed", title="Which item?", summary="Snapback couldn't match the message to one order")
    pct = min(99, 60 + 13 * (score - runner))
    O.update_task(tid, order_id=best["order_id"], title=f"{best['item_name']}: checking the store policy",
                  summary=f"Matched “{clean[:60]}” to {best['item_name']} ({best['order_id']})")
    O.step(tid, "order_matched", f"Matched {best['item_name']} · {best['order_id']} · {pct}%",
           reason=f"Your message names the {best['item_name']} from your {STORE_NAMES.get(best['store'], best['store'])} order.",
           inputs={"order_id": best["order_id"], "confidence_pct": pct}, sources=[O.email_source_for_order(best)],
           rejected=[{"option": f"{o['order_id']} {o['item_name']}", "reason": f"shares {s} words"} for o, s in ranked[1:3]],
           rules_checked=checks, authorized_by="mandate:auto_return_defective",
           model=(best.get("extraction") or {}).get("model") or "", track={"store": best["store"]})
    after_match(tid, best, mandate)


# Chat tasks continue through the photo flow after the match (after_match), so their approvals
# (over-cap buy, buy-fix) are answered by the same handler.
from backend.flows.photo import _photo_answer  # noqa: E402

O.on_answer("chat")(_photo_answer)
