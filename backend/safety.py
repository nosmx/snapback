"""Fetched text (emails, pages, listings) is data, never instructions.

detect_injection() flags instruction-like text so it can be logged as
"ignored injected instruction" and stripped before anything downstream sees it.
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

_PATTERNS = [
    r"ignore (all |your |any )?(previous|prior|above) (rules|instructions)",
    r"\b(system|developer) (notice|prompt|message)\b.*\b(ai|assistant|agent)s?\b",
    r"\bto (ai|llm) (assistants?|agents?)\b",
    r"approval has (already )?been granted",
    r"\b(immediately|now) (purchase|buy|order|refund|transfer)\b",
]
_RX = [re.compile(p, re.IGNORECASE) for p in _PATTERNS]


def detect_injection(text: str) -> Tuple[str, List[Dict[str, str]]]:
    """Returns (clean_text, flags). Lines matching an injection pattern are removed."""
    clean, flags = [], []
    for line in text.splitlines():
        hit = next((rx.pattern for rx in _RX if rx.search(line)), None)
        if hit:
            flags.append({"flag": "ignored_injected_instruction", "pattern": hit, "excerpt": line.strip()[:200]})
        else:
            clean.append(line)
    return "\n".join(clean), flags
