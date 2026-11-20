"""Replacement ranking: SIE vector search + rerank over the SingleStore catalog, then the mandate.

Strategy (mandate.replacement.strategy = same_item_unless_poor_reviews): the same item if its
reviews are acceptable, otherwise the best-rated candidate within budget. The Statsig
`replacement_strategy` variant is always logged; the user's mandate is authoritative.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend import rules
from backend.integrations import senso, sie, statsig
from backend.integrations.base import model_label
from backend.integrations.singlestore import db


def rank(order: Dict[str, Any], mandate: Dict[str, Any]) -> Dict[str, Any]:
    catalog = {c["sku"]: c for c in db().select("catalog")}
    original = catalog.get(order.get("sku") or "")
    category = ((original or {}).get("specs") or {}).get("category")
    query = f"Replacement for {order['item_name']}" + (f" ({category})" if category else "")
    qvec, emeta = sie.embed_text(query, is_query=True)
    hits = db().vector_search("catalog", "text_embedding", "sku", qvec, k=10)
    pool = [catalog[s] for s, _ in hits if s in catalog and
            (not category or (catalog[s].get("specs") or {}).get("category") == category)]
    docs = [f"{c['name']}. Rating {c['rating']}. {(c.get('specs') or {})}" for c in pool]
    order_ranked, rmeta = sie.rerank(query, docs) if docs else ([], {"mode": "none", "provider": "sie", "degraded": False})
    ranked = [pool[i] for i, _ in order_ranked]
    rerank_scores = {pool[i]["sku"]: round(s, 4) for i, s in order_ranked}

    variant, smeta = statsig.variant(mandate.get("user_id", "u_001"), "replacement_strategy")
    strategy = (mandate.get("replacement") or {}).get("strategy", "same_item_unless_poor_reviews")
    review_res, review_meta = senso.query(f"{order['item_name']} reviews hinge durability rating",
                                          store=f"reviews-{order['store']}")
    review_cite = next((c for c in review_res.get("citations", []) if (order.get("sku") or "~") in c.get("section", "")),
                       (review_res.get("citations") or [None])[0])

    checks: List[Dict[str, Any]] = []
    rejected: List[Dict[str, str]] = []
    chosen: Optional[Dict[str, Any]] = None
    price = float(order["price"])

    same_ok = False
    if original:
        poor = rules.poor_reviews(original.get("rating"), mandate)
        within, same_rules = rules.replacement_checks(price, original, mandate)
        checks += [poor] + same_rules
        same_ok = poor["passed"] and within
        if same_ok and strategy.startswith("same_item"):
            chosen = original
        else:
            rejected.append({"option": f"Same item: {original['name']}",
                             "reason": poor["evidence"] if not poor["passed"] else "fails the spending limits"})

    if chosen is None:
        eligible = []
        for c in ranked:
            if original and c["sku"] == original["sku"]:
                continue
            ok, rs = rules.replacement_checks(price, c, mandate)
            if ok and rules.poor_reviews(c.get("rating"), mandate)["passed"]:
                eligible.append(c)
            else:
                failed = next((r["evidence"] for r in rs if not r["passed"]), "poor reviews")
                rejected.append({"option": f"{c['name']} (${float(c['price']):.2f}, ★{c['rating']})", "reason": failed})
        eligible.sort(key=lambda c: (-float(c["rating"] or 0), float(c["price"])))
        if eligible:
            chosen = eligible[0]
            for c in eligible[1:]:
                rejected.append({"option": f"{c['name']} (${float(c['price']):.2f}, ★{c['rating']})",
                                 "reason": f"lower rating than {chosen['name']} (★{chosen['rating']})"})
            _, chosen_rules = rules.replacement_checks(price, chosen, mandate)
            checks += chosen_rules

    checks.append(rules.check("statsig.replacement_strategy", True,
                              f"Statsig variant '{variant['variant']}'" +
                              (" (experiment not configured)" if not variant.get("configured", True) else "") +
                              f"; mandate strategy '{strategy}' is authoritative"))
    return {
        "chosen": chosen, "rejected": rejected, "rules": checks, "query": query, "rerank_scores": rerank_scores,
        "statsig": variant, "strategy": strategy, "review_cite": review_cite,
        "model": model_label(rmeta, sie.model_name("rerank")) if docs else model_label(emeta, sie.model_name("text")),
        "candidates": [{"sku": c["sku"], "name": c["name"], "price": float(c["price"]), "rating": float(c["rating"] or 0),
                        "rerank": rerank_scores.get(c["sku"])} for c in ranked],
    }
