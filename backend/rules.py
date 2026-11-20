"""Deterministic decision rules. No LLM here: rules decide eligibility, the LLM only explains.

Every numeric policy fact comes from the Senso "Policy summary" section (passed in as `facts`,
with its citation). Every check returns {rule, passed, evidence} for audit_log.rules_checked.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import yaml

from backend import clock
from backend.config import ROOT

Rule = Dict[str, Any]


STORE_NAMES = {"northwind-audio": "Northwind Audio", "juniper-home": "Juniper Home",
               "kestrel-outdoors": "Kestrel Outdoors", "larkspur-supply": "Larkspur Supply Co."}


def check(rule: str, passed: bool, evidence: str) -> Rule:
    return {"rule": rule, "passed": bool(passed), "evidence": evidence}


def money(x: float) -> str:
    return f"${x:,.2f}"


def _date(v: Any) -> Optional[date]:
    if not v:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).replace("T", " ")
    return datetime.fromisoformat(s[:26]).date() if len(s) > 10 else date.fromisoformat(s)


def load_mandate() -> Dict[str, Any]:
    """The Persona-verified mandate from SingleStore; falls back to mandate.yaml."""
    try:
        from backend.integrations.singlestore import db
        rows = db().select("mandates", limit=1)
        if rows and rows[0].get("rules"):
            m = dict(rows[0]["rules"])
            m["_persona_inquiry_id"] = rows[0].get("persona_inquiry_id")
            return m
    except Exception:
        pass
    return yaml.safe_load((ROOT / "backend" / "mandate.yaml").read_text())["mandate"]


# ---------------- shared checks ----------------

def store_allowed(store: Optional[str], mandate: Dict[str, Any]) -> Rule:
    allowed = mandate.get("allowed_stores") or []
    return check("mandate.allowed_stores", store in allowed,
                 f"{store or 'unknown store'} {'is' if store in allowed else 'is NOT'} in allowed_stores {allowed}")


def verified_policy(facts: Optional[Dict[str, Any]], store: Optional[str]) -> Rule:
    return check("verified_policy", facts is not None,
                 f"Senso policy summary found for {store}" if facts else f"No verified policy for {store} in Senso")


def return_deadline(order: Dict[str, Any], facts: Dict[str, Any]) -> Tuple[Optional[date], str]:
    """Conservative reading: the earlier of the email's return-by and delivery + policy window."""
    delivered = _date(order.get("delivered_at"))
    email_by = _date(order.get("return_by"))
    policy_by = delivered + timedelta(days=int(facts.get("return_window_days", 0))) if delivered else None
    candidates = [d for d in (email_by, policy_by) if d]
    if not candidates:
        return None, "no delivery date"
    eff = min(candidates)
    ev = f"email says return by {email_by}" if email_by else "email has no return-by"
    ev += f"; policy {facts.get('return_window_days')} days from delivery {delivered} = {policy_by}" if policy_by else ""
    if email_by and policy_by and email_by != policy_by:
        ev += f"; using the earlier date {eff}"
    return eff, ev


def in_return_window(order: Dict[str, Any], facts: Dict[str, Any], today: Optional[date] = None) -> Tuple[bool, Rule, Optional[date]]:
    today = today or clock.today()
    deadline, ev = return_deadline(order, facts)
    ok = bool(deadline and today <= deadline)
    days = (deadline - today).days if deadline else None
    return ok, check("policy.return_window", ok, f"{ev}; today {today}" + (f" ({days} days left)" if ok else " (closed)")), deadline


def under_warranty(order: Dict[str, Any], facts: Dict[str, Any], today: Optional[date] = None) -> Tuple[bool, Rule]:
    today = today or clock.today()
    delivered = _date(order.get("delivered_at"))
    days = int(facts.get("warranty_days", 0) or 0)
    if not delivered or not days:
        return False, check("policy.warranty", False, "no warranty term or delivery date")
    until = delivered + timedelta(days=days)
    ok = today <= until
    return ok, check("policy.warranty", ok, f"{days}-day warranty from delivery {delivered} covers until {until}; today {today}")


# ---------------- photo / defect ----------------

def decide_defect(order: Dict[str, Any], facts: Optional[Dict[str, Any]], mandate: Dict[str, Any],
                  today: Optional[date] = None) -> Dict[str, Any]:
    """return_and_replace | warranty_claim | buy_fix | do_not_act"""
    today = today or clock.today()
    rules: List[Rule] = [store_allowed(order.get("store"), mandate), verified_policy(facts, order.get("store"))]
    rejected: List[Dict[str, str]] = []
    if not rules[0]["passed"] or facts is None:
        return {"decision": "do_not_act", "rules": rules, "rejected": [],
                "authorized_by": "mandate:allowed_stores" if not rules[0]["passed"] else "mandate:verified_policy_required"}

    in_window, r_window, deadline = in_return_window(order, facts, today)
    warranty, r_warranty = under_warranty(order, facts, today)
    auto = bool(mandate.get("auto_return_defective"))
    rules += [r_window, r_warranty, check("mandate.auto_return_defective", auto, f"auto_return_defective={auto}")]

    if in_window and auto:
        rejected = [{"option": "warranty_claim", "reason": "Return window is still open: a refund beats a repair"},
                    {"option": "buy_fix", "reason": "Covered by a free return"}]
        return {"decision": "return_and_replace", "rules": rules, "rejected": rejected, "deadline": deadline,
                "authorized_by": "mandate:auto_return_defective"}
    if warranty:
        rejected = [{"option": "return_and_replace", "reason": f"Return window closed on {deadline}"},
                    {"option": "buy_fix", "reason": "Still under warranty: the store covers it"}]
        return {"decision": "warranty_claim", "rules": rules, "rejected": rejected,
                "authorized_by": "mandate:auto_return_defective"}
    rejected = [{"option": "return_and_replace", "reason": f"Return window closed on {deadline}"},
                {"option": "warranty_claim", "reason": "Warranty expired"}]
    return {"decision": "buy_fix", "rules": rules, "rejected": rejected, "authorized_by": "mandate:replacement"}



# ---------------- damage evidence + return method ----------------

_BATTERY_DAMAGE = re.compile(
    r"\b(exposed|swollen|swelling|puffed|bulging|punctured|leaking|burnt|burned|charred|damaged|cracked)\b[^.;]{0,30}\bbatter(y|ies)\b"
    r"|\bbatter(y|ies)\b[^.;]{0,30}\b(exposed|swollen|swelling|puffed|bulging|punctured|leaking|burnt|damaged|visible|showing)\b",
    re.IGNORECASE)
_PHYSICAL_DAMAGE = re.compile(r"\b(crack|cracked|broken|split|shattered|snapped|dent|dented|torn|exposed|burnt|swollen)\b",
                              re.IGNORECASE)
RETURN_METHOD_LABELS = {"standard": "standard return label", "in_store_dropoff": "in-store drop-off",
                        "battery_safe_label": "battery-safe return label"}


def damage_evidence(desc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Turn the vision model's DESCRIPTION into evidence with deterministic patterns. The model's own
    booleans are recorded but not trusted: the rules read the words it used."""
    desc = desc or {}
    text = "; ".join([str(desc.get("summary") or "")] + [str(x) for x in desc.get("damage") or []])
    assessed = bool(desc.get("damage")) or (desc.get("summary") and "not assessed" not in str(desc.get("summary")))
    battery = bool(_BATTERY_DAMAGE.search(text)) if assessed else None
    physical = bool(_PHYSICAL_DAMAGE.search(text)) if assessed else None
    rules = [check("evidence.physical_damage_visible", bool(physical),
                   f"description: '{text[:120]}'" if assessed else "photo not assessed (vision model unavailable)"),
             check("evidence.battery_damaged", bool(battery),
                   (f"battery damage named in the description: '{text[:120]}'" if battery else
                    "no battery damage named in the description") if assessed else "photo not assessed")]
    return {"assessed": bool(assessed), "physical_damage": physical, "battery_damage": battery, "text": text, "rules": rules}


def _methods(facts: Dict[str, Any]) -> List[str]:
    raw = facts.get("damaged_battery_methods") or ""
    return [m.strip() for m in str(raw).split(",") if m.strip() in RETURN_METHOD_LABELS]


def choose_return_method(facts: Optional[Dict[str, Any]], battery_damage: Optional[bool],
                         clause: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """standard | in_store_dropoff | battery_safe_label. Facts come only from the cited Senso policy summary."""
    facts = facts or {}
    if not battery_damage:
        return {"method": "standard", "rules": [check("return_method.standard", True, "no battery damage in the evidence")],
                "rejected": []}
    methods = _methods(facts)
    mail_ok = facts.get("damaged_battery_standard_mail", True)
    rules = [check("policy.damaged_battery_clause", bool(methods),
                   (f"cited '{clause.get('section')}': " if clause else "") +
                   f"damaged_battery_methods={facts.get('damaged_battery_methods')}, "
                   f"damaged_battery_standard_mail={facts.get('damaged_battery_standard_mail')}")]
    if not methods:
        rules.append(check("return_method.conservative", True, "policy silent on damaged batteries: standard label, flagged"))
        return {"method": "standard", "rules": rules, "rejected": []}
    rejected = []
    if mail_ok is False:
        rejected.append({"option": "standard return mail", "reason": "Policy: damaged batteries can't go in standard return mail"})
    # in-store drop-off refunds at drop-off; the battery-safe label refunds after inspection
    if "in_store_dropoff" in methods and facts.get("damaged_battery_refund_in_store") == "at_dropoff":
        method = "in_store_dropoff"
    else:
        method = methods[0]
    for m in methods:
        if m != method:
            rejected.append({"option": RETURN_METHOD_LABELS[m],
                             "reason": ("Refund only after inspection, pickup within 5 business days"
                                        if m == "battery_safe_label" else "Slower refund than the chosen method")})
    rules.append(check("return_method.battery_safe", True,
                       f"{RETURN_METHOD_LABELS[method]}: refund {facts.get('damaged_battery_refund_in_store') if method == 'in_store_dropoff' else facts.get('damaged_battery_refund_label')}"))
    return {"method": method, "rules": rules, "rejected": rejected}


# ---------------- price drops ----------------

def classify_price_drop(paid: float, current: float, mandate: Dict[str, Any]) -> Dict[str, Any]:
    diff = round(paid - current, 2)
    pct = round(diff / paid * 100, 1) if paid else 0.0
    t = (mandate.get("price_drop") or {}).get("major_if") or {"min_percent": 15, "min_usd": 20}
    if diff <= 0:
        sev = "none"
    elif pct >= t["min_percent"] or diff >= t["min_usd"]:
        sev = "major"
    else:
        sev = "minor"
    rule = check("mandate.price_drop.major_if", sev == "major",
                 f"drop {money(diff)} ({pct}%) vs thresholds {t['min_percent']}% or {money(t['min_usd'])} -> {sev}")
    return {"severity": sev, "diff": diff, "pct": pct, "rule": rule}


def price_drop_options(order: Dict[str, Any], current: float, facts: Dict[str, Any], mandate: Dict[str, Any],
                       today: Optional[date] = None) -> Dict[str, Any]:
    """Options the policy allows, each with net savings. Return & rebuy = diff - restocking - return shipping."""
    today = today or clock.today()
    paid = float(order["price"])
    diff = round(paid - current, 2)
    delivered = _date(order.get("delivered_at"))
    rules: List[Rule] = []
    options: List[Dict[str, Any]] = []
    rejected: List[Dict[str, str]] = []

    adj_allowed = bool(facts.get("price_adjustment_allowed"))
    adj_days = int(facts.get("price_adjustment_window_days", 0) or 0)
    adj_until = delivered + timedelta(days=adj_days) if delivered else None
    adj_ok = adj_allowed and adj_until is not None and today <= adj_until
    rules.append(check("policy.price_adjustment", adj_ok,
                       f"price_adjustment_allowed={adj_allowed}, window {adj_days} days from {delivered} -> until {adj_until}; today {today}"))
    if adj_ok:
        options.append({"id": "price_match", "label": "Price match", "action": "execute", "net_savings_usd": diff,
                        "detail": f"The store refunds the {money(diff)} difference. No hassle."})
    else:
        rejected.append({"option": "price_match", "reason": "Policy does not allow a price adjustment" if not adj_allowed
                         else f"Price-adjustment window closed on {adj_until}"})

    in_window, r_window, deadline = in_return_window(order, facts, today)
    rules.append(r_window)
    restock = round(paid * float(facts.get("restocking_fee_pct_non_defective_opened", 0) or 0) / 100, 2)
    ship = float(facts.get("return_shipping_usd_non_defective", 0) or 0)
    net_rebuy = round(diff - restock - ship, 2)
    math = f"{money(diff)} difference - {money(restock)} restocking - {money(ship)} return shipping = {money(net_rebuy)}"
    rules.append(check("savings.return_rebuy_positive", net_rebuy > 0, math))
    if in_window and net_rebuy > 0:
        fees = " · ".join(x for x in ([f"{money(ship)} return shipping"] if ship else []) +
                          ([f"{money(restock)} restocking"] if restock else []))
        options.append({"id": "return_rebuy", "label": "Return & rebuy", "action": "execute", "net_savings_usd": net_rebuy,
                        "detail": "Needs a drop-off" + (f" · {fees}" if fees else ""), "math": math})
    else:
        rejected.append({"option": "return_rebuy", "reason": f"Return window closed on {deadline}" if not in_window
                         else f"Fees exceed the savings: {math}"})

    options.append({"id": "ignore", "label": "Ignore", "action": "dismiss", "net_savings_usd": None,
                    "detail": f"Keep paying {money(paid)}"})
    executable = [o for o in options if o["action"] == "execute"]
    recommended = None
    if executable:  # highest net savings; ties go to price match (no drop-off)
        recommended = sorted(executable, key=lambda o: (-o["net_savings_usd"], o["id"] != "price_match"))[0]["id"]
    return {"options": options, "recommended": recommended, "rejected": rejected, "rules": rules,
            "info_only": not executable, "net_rebuy": net_rebuy, "math": math}


# ---------------- return window ----------------

def return_window_alert(order: Dict[str, Any], facts: Dict[str, Any], mandate: Dict[str, Any],
                        today: Optional[date] = None) -> Dict[str, Any]:
    today = today or clock.today()
    n = int(mandate.get("return_window_alert_days", 3))
    in_window, r_window, deadline = in_return_window(order, facts, today)
    days_left = (deadline - today).days if deadline else None
    alert = bool(in_window and days_left is not None and days_left <= n and order.get("status") == "active")
    return {"alert": alert, "days_left": days_left, "deadline": deadline,
            "rules": [r_window, check("mandate.return_window_alert_days", alert,
                                      f"{days_left} days left vs alert threshold {n} days; order status {order.get('status')}")]}


# ---------------- replacement purchase ----------------

def replacement_checks(original_price: float, candidate: Dict[str, Any], mandate: Dict[str, Any]) -> Tuple[bool, List[Rule]]:
    rep = mandate.get("replacement") or {}
    cap = float(mandate.get("require_approval_over_usd", 200))
    max_extra = float(rep.get("max_extra_spend_usd", 30))
    price = float(candidate["price"])
    extra = round(price - original_price, 2)
    rules = [
        check("mandate.replacement.enabled", bool(rep.get("enabled", True)), f"replacement.enabled={rep.get('enabled', True)}"),
        check("catalog.in_stock", bool(candidate.get("in_stock", True)), f"{candidate['name']} in stock: {candidate.get('in_stock', True)}"),
        check("mandate.replacement.max_extra_spend_usd", extra <= max_extra,
              f"{money(price)} - {money(original_price)} = {money(extra)} extra vs limit {money(max_extra)}"),
        check("mandate.require_approval_over_usd", price <= cap, f"new order charge {money(price)} vs cap {money(cap)}"),
    ]
    return all(r["passed"] for r in rules), rules


def poor_reviews(rating: Optional[float], mandate: Dict[str, Any]) -> Rule:
    thr = float((mandate.get("replacement") or {}).get("poor_review_threshold", 3.5))
    poor = rating is not None and float(rating) < thr
    return check("mandate.replacement.poor_review_threshold", not poor,
                 f"rating {rating} {'<' if poor else '>='} threshold {thr}" + (" -> poor reviews" if poor else ""))
