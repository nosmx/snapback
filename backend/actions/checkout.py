"""Place an order on the merchant's mock checkout with the browser agent.

The agent never sees card data: the store charges its saved mock wallet. `max_price` guards
against the price changing between decision and purchase.
"""
from __future__ import annotations

import re
from typing import Any, Dict

from backend.actions.browser import portal_page, set_hidden
from backend.config import settings

M = settings.merchant_base_url


def place_order(store: str, sku: str, ship_zip: str, idempotency_key: str, verified_by: str = "",
                max_price: float = 0.0) -> Dict[str, Any]:
    with portal_page() as page:
        page.goto(f"{M}/s/{store}/checkout?sku={sku}")
        if page.locator('[data-testid="error"]').count():
            return {"ok": False, "error": page.get_by_test_id("error-message").inner_text()}
        page.get_by_test_id("ship-zip").fill(ship_zip)
        set_hidden(page, idempotency_key=idempotency_key, verified_by=verified_by,
                   max_price=f"{max_price:.2f}" if max_price else "")
        page.get_by_test_id("place-order").click()
        page.wait_for_selector('[data-testid="order-confirmation"], [data-testid="error"]')
        if page.locator('[data-testid="error"]').count():
            return {"ok": False, "error": page.get_by_test_id("error-message").inner_text()}
        charged = page.get_by_test_id("charged").inner_text()
        m = re.search(r"\$([\d,]+\.\d{2})", charged)
        return {"ok": True, "order_no": page.get_by_test_id("new-order-no").inner_text().strip(),
                "charged": float(m.group(1).replace(",", "")) if m else None, "confirmation_url": page.url}
