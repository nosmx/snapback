"""In-process event bus behind GET /api/stream (Server-Sent Events).

audit.append()/append_many() publish every sealed entry, orchestrator publishes task status
changes, and the demo reset publishes `reset`. Events sit in a bounded ring buffer. Ids are
strictly increasing microsecond timestamps, so they keep increasing across backend reloads: a
client resumes with Last-Event-ID, and if its id predates what the buffer still holds (overflow or
a reload), it gets a `resync` event and should refetch GET /api/audit?since_seq=N.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Tuple

BOOT_ID = time.time_ns() // 1000
_lock = threading.Lock()
_buf: Deque[Tuple[int, Dict[str, Any]]] = deque(maxlen=2000)
_last_id = BOOT_ID
_floor = BOOT_ID          # ids <= _floor are no longer in the buffer


def publish(data: Dict[str, Any]) -> int:
    global _last_id, _floor
    with _lock:
        _last_id = max(_last_id + 1, time.time_ns() // 1000)
        if len(_buf) == _buf.maxlen:
            _floor = _buf[0][0]
        _buf.append((_last_id, data))
        return _last_id


def current_id() -> int:
    with _lock:
        return _last_id


def since(cursor: int) -> Tuple[List[Tuple[int, Dict[str, Any]]], bool]:
    """Events after `cursor`, plus whether some were missed (cursor older than the buffer)."""
    with _lock:
        return [(i, d) for i, d in _buf if i > cursor], cursor < _floor
