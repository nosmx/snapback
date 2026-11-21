"""Demo-reset state shared by the API, the browser agent and the calendar.

While a reset is staging the demo, background work must not show up on stage: the browser agent
runs headless and drop-off reminders go to the mock calendar, never to Apple Calendar. Only live
user actions open the visible browser or create real calendar events.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

RESET_LOCK = threading.Lock()        # one reset at a time; a second press joins the running one
_staging = False
_last: Optional[Dict[str, Any]] = None
_started_at: Optional[float] = None


def is_staging() -> bool:
    return _staging


def begin() -> None:
    global _staging, _started_at
    _staging, _started_at = True, time.time()


def end(result: Dict[str, Any]) -> None:
    global _staging, _last
    _staging, _last = False, result


def last_result() -> Optional[Dict[str, Any]]:
    return _last


def started_at() -> Optional[float]:
    return _started_at
