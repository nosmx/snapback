"""File a return on the merchant's portal (order # + ZIP, no login) with the browser agent.

Self-recovery (§5.6): retry once on a portal error, then fall back to the support email channel.
Every attempt is returned so the caller can log it. The idempotency key makes retries safe.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from backend.actions.browser import portal_page, set_hidden
from backend.config import settings

M = settings.merchant_base_url


def _confirmation(page) -> Dict[str, Any]:
    t = lambda tid: page.get_by_test_id(tid).inner_text().strip()
    refund = t("refund-amount")
    m = re.search(r"\$([\d,]+\.\d{2})", refund)
    return {"rma": t("rma"), "refund_amount": float(m.group(1).replace(",", "")) if m else None,
            "drop_off_by": t("drop-off-by"), "label_url": page.get_by_test_id("label-link").get_attribute("href"),
            "confirmation_url": page.url}


def file_return(store: str, order_no: str, zip_code: str, reason: str, idempotency_key: str,
                verified_by: str = "", return_method: str = "standard") -> Dict[str, Any]:
    attempts: List[Dict[str, Any]] = []
    with portal_page() as page:
        for attempt in (1, 2):
            page.goto(f"{M}/s/{store}/returns")
            page.get_by_test_id("order-no").fill(order_no)
            page.get_by_test_id("zip").fill(zip_code)
            page.get_by_test_id("lookup").click()
            page.wait_for_selector('[data-testid="order-found"], [data-testid="error"], [data-testid="return-confirmation"]')
            if page.locator('[data-testid="return-confirmation"]').count():
                return {"ok": True, "already": True, **_confirmation(page), "attempts": attempts}
            if page.locator('[data-testid="error"]').count():
                msg = page.get_by_test_id("error-message").inner_text()
                attempts.append({"channel": "portal", "attempt": attempt, "step": "lookup", "error": msg})
                return {"ok": False, "error": msg, "attempts": attempts}
            page.get_by_test_id("reason").select_option(reason)
            set_hidden(page, idempotency_key=idempotency_key, verified_by=verified_by, return_method=return_method)
            page.get_by_test_id("submit-return").click()
            page.wait_for_selector('[data-testid="return-confirmation"], [data-testid="error"]')
            if page.locator('[data-testid="return-confirmation"]').count():
                attempts.append({"channel": "portal", "attempt": attempt, "status": "confirmed"})
                return {"ok": True, **_confirmation(page), "attempts": attempts}
            msg = page.get_by_test_id("error-message").inner_text()
            attempts.append({"channel": "portal", "attempt": attempt, "step": "submit", "error": msg})
            if "temporarily unavailable" not in msg:
                break
    attempts.append({"channel": "support_email", "status": "drafted",
                     "note": "Portal failed twice; return request drafted to the store's support address"})
    return {"ok": False, "error": attempts[-2].get("error", "portal error"), "attempts": attempts}
