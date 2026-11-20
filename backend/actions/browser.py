"""Browser agent: Playwright, scripted against the mock merchant's stable data-testid selectors.

PLAYWRIGHT_HEADLESS=false opens a visible Chromium window (for the stage). One browser at a time.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Iterator

from backend.config import settings

_lock = threading.Lock()


@contextmanager
def portal_page() -> Iterator["object"]:
    from playwright.sync_api import sync_playwright

    headless = settings.playwright_headless
    with _lock:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless, slow_mo=0 if headless else settings.playwright_slow_mo_ms,
                                        args=["--window-size=1180,860", "--window-position=60,40"])
            page = browser.new_context(viewport={"width": 1160, "height": 780}).new_page()
            page.set_default_timeout(15000)
            try:
                yield page
            finally:
                if not headless:
                    time.sleep(0.6)  # let the audience see the confirmation page
                browser.close()


def set_hidden(page, **fields: str) -> None:
    page.evaluate(
        "(f) => { for (const [k, v] of Object.entries(f)) {"
        " const el = document.querySelector(`input[name=${k}]`); if (el) el.value = v; } }", fields)
