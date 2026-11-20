"""Verifier: confirms outcomes from OUTSIDE evidence, never from the executor's own claim.

Evidence sources: the user's inbox (confirmation emails) and the bank ledger (posted refunds).
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

import httpx

from backend.config import settings

M = settings.merchant_base_url


def inbox() -> List[Dict[str, Any]]:
    return httpx.get(f"{M}/api/inbox", timeout=10).json()


def posted_transactions() -> List[Dict[str, Any]]:
    return httpx.get(f"{M}/api/bank/transactions", timeout=10).json()


def _poll(fn: Callable[[], Optional[Dict[str, Any]]], timeout_s: float, interval_s: float = 1.0) -> Optional[Dict[str, Any]]:
    deadline = time.time() + timeout_s
    while True:
        try:
            hit = fn()
        except Exception:
            hit = None
        if hit or time.time() >= deadline:
            return hit
        time.sleep(interval_s)


def find_email(meta_key: str, value: str, timeout_s: float = 10) -> Optional[Dict[str, Any]]:
    return _poll(lambda: next((e for e in inbox() if str((e.get("meta") or {}).get(meta_key)) == str(value)), None), timeout_s)


def find_refund(ref: str, timeout_s: float = 0) -> Optional[Dict[str, Any]]:
    return _poll(lambda: next((t for t in posted_transactions() if t.get("ref") == ref and t["amount"] > 0), None), timeout_s)


def find_charge(ref: str, timeout_s: float = 5) -> Optional[Dict[str, Any]]:
    return _poll(lambda: next((t for t in posted_transactions() if t.get("ref") == ref and t["amount"] < 0), None), timeout_s)


def email_source(e: Dict[str, Any]) -> Dict[str, Any]:
    return {"doc": f"Email: {e['subject']}", "section": e.get("kind", "email"), "url": e.get("url"),
            "retrieved_at": e.get("received_at")}


def bank_source(t: Dict[str, Any]) -> Dict[str, Any]:
    return {"doc": f"Bank ledger: {t['memo']}", "section": f"{t['amount']:+.2f} posted {t['posts_at']}",
            "url": f"{M}/bank", "retrieved_at": t["posts_at"]}
