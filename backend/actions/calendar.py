"""Drop-off reminder for a filed return.

1. A real event in macOS Calendar via AppleScript: calendar "Snapback" (created if missing), 30 min at
   the next reasonable slot before the return deadline, a 1-hour alert, notes with the RMA, label URL
   and task link. Then Calendar opens on that date.
2. If osascript fails (not macOS, no Automation permission, timeout): the mock calendar at
   :8001/calendar gets the event instead.
3. The .ics file is always written: the last fallback, and a download link for the frontend
   (/api/reminders/<task_id>.ics).

Mode (CALENDAR_MODE, or POST /api/demo/calendar at runtime): auto | mock (skip Apple Calendar; test
runs) | ics. Item names come from order emails (untrusted), so they reach AppleScript only as argv
and are escaped in the .ics, never spliced into script text.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional

import httpx

from backend import clock
from backend.config import DATA_DIR, settings

REMINDERS = DATA_DIR / "reminders"
DURATION_MIN = 30
ALARM_MIN = 60
DAY_START, DAY_END = 9, 18            # typical carrier drop-off hours
MODES = ("auto", "mock", "ics")
_override: Optional[str] = None


def current_mode() -> str:
    m = (_override or settings.calendar_mode or "auto").lower()
    return m if m in MODES else "auto"


def set_mode(mode: Optional[str]) -> str:
    global _override
    if mode is not None and mode not in MODES:
        raise ValueError(f"calendar mode must be one of {MODES}")
    _override = mode
    return current_mode()


def next_slot(by: date, now: datetime) -> datetime:
    """Next 30-minute slot at least an hour out (so the 1-hour alert is still ahead), inside drop-off
    hours, not on a Sunday, on or before the deadline. No such slot left -> as soon as possible."""
    t = now.replace(second=0, microsecond=0) + timedelta(minutes=60)
    if t.minute % 30:
        t += timedelta(minutes=30 - t.minute % 30)
    for _ in range(10):
        if t.weekday() == 6:
            t = datetime.combine(t.date() + timedelta(days=1), time(DAY_START))
            continue
        if t.hour < DAY_START:
            t = datetime.combine(t.date(), time(DAY_START))
        if t + timedelta(minutes=DURATION_MIN) > datetime.combine(t.date(), time(DAY_END)):
            t = datetime.combine(t.date() + timedelta(days=1), time(DAY_START))
            continue
        break
    if t.date() > by:
        t = now.replace(second=0, microsecond=0) + timedelta(minutes=15)
        t += timedelta(minutes=(5 - t.minute % 5) % 5)
    return t


# ---------------- Apple Calendar ----------------

APPLESCRIPT = r'''
on run argv
    set calName to item 1 of argv
    set evTitle to item 2 of argv
    set evNotes to item 3 of argv
    set evLoc to item 4 of argv
    set y to (item 5 of argv) as integer
    set mo to (item 6 of argv) as integer
    set d to (item 7 of argv) as integer
    set mins to (item 8 of argv) as integer
    set dur to (item 9 of argv) as integer
    set alarmMin to (item 10 of argv) as integer
    set taskKey to item 11 of argv
    set showIt to item 12 of argv
    set s to current date
    set day of s to 1
    set year of s to y
    set month of s to mo
    set day of s to d
    set time of s to mins * 60
    tell application "Calendar"
        if not (exists calendar calName) then
            make new calendar with properties {name:calName}
        end if
        set cal to calendar calName
        set existing to {}
        try
            set existing to (every event of cal whose description contains taskKey)
        end try
        if (count of existing) > 0 then
            set ev to item 1 of existing
            set already to "1"
        else
            set ev to make new event at end of events of cal with properties {summary:evTitle, start date:s, end date:(s + dur * minutes), description:evNotes, location:evLoc}
            tell ev to make new display alarm at end of display alarms with properties {trigger interval:(0 - alarmMin)}
            set already to "0"
        end if
        set evId to uid of ev
        set shown to "0"
        if showIt is "1" then
            try
                switch view to day view
                view calendar at s
                set shown to "1"
            end try
        end if
    end tell
    return evId & "|" & already & "|" & shown
end run
'''


def _apple(title: str, notes: str, location: str, start: datetime, task_id: str, show: bool) -> Dict[str, Any]:
    if sys.platform != "darwin" or not shutil.which("osascript"):
        raise RuntimeError("osascript not available (not macOS)")
    args = [settings.calendar_name, title, notes, location, str(start.year), str(start.month), str(start.day),
            str(start.hour * 60 + start.minute), str(DURATION_MIN), str(ALARM_MIN), task_id, "1" if show else "0"]
    r = subprocess.run(["osascript", "-", *args], input=APPLESCRIPT, capture_output=True, text=True, timeout=15)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "osascript failed").strip()[:300])
    uid, already, shown = (r.stdout.strip().split("|") + ["", "", ""])[:3]
    if show:
        subprocess.run(["open", "-a", "Calendar"], capture_output=True, timeout=10)
    return {"event_id": uid, "already_existed": already == "1", "view_switched": shown == "1"}


# ---------------- mock calendar (:8001/calendar) ----------------

def _mock(title: str, notes: str, location: str, start: datetime, end: datetime, task_id: str) -> Dict[str, Any]:
    r = httpx.post(f"{settings.merchant_base_url}/calendar/events", timeout=5, json={
        "task_id": task_id, "title": title, "notes": notes, "location": location,
        "start": start.isoformat(timespec="minutes"), "end": end.isoformat(timespec="minutes"),
        "alarm_minutes_before": ALARM_MIN, "calendar": settings.calendar_name})
    r.raise_for_status()
    ev = r.json()
    return {"event_id": ev["event_id"], "already_existed": ev.get("already", False), "calendar_url": ev["url"]}


# ---------------- .ics (always written) ----------------

def _ics_text(v: str) -> str:
    return (v.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", ""))


def _write_ics(task_id: str, title: str, notes: str, location: str, start: datetime, end: datetime) -> str:
    REMINDERS.mkdir(parents=True, exist_ok=True)
    fmt = "%Y%m%dT%H%M%S"                       # floating local time: shows at the same wall-clock time
    ics = "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Snapback//EN", "CALSCALE:GREGORIAN", "BEGIN:VEVENT",
        f"UID:{task_id}@snapback", f"DTSTAMP:{datetime.utcnow():%Y%m%dT%H%M%SZ}",
        f"DTSTART:{start:{fmt}}", f"DTEND:{end:{fmt}}",
        f"SUMMARY:{_ics_text(title)}", f"DESCRIPTION:{_ics_text(notes)}", f"LOCATION:{_ics_text(location)}",
        "BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_ics_text(title)}", f"TRIGGER:-PT{ALARM_MIN}M", "END:VALARM",
        "END:VEVENT", "END:VCALENDAR", ""])
    (REMINDERS / f"{task_id}.ics").write_text(ics)
    return f"http://localhost:{settings.backend_port}/api/reminders/{task_id}.ics"


def add_dropoff_reminder(task_id: str, *, item: str, store_name: str, rma: str, label_url: Optional[str],
                         by: date, location: str = "Carrier drop-off point") -> Dict[str, Any]:
    """Create the reminder (Apple Calendar -> mock calendar -> .ics) and describe what happened."""
    title = f"Drop off return: {item} ({store_name})"
    start = next_slot(by, clock.local_now())
    end = start + timedelta(minutes=DURATION_MIN)
    task_url = f"{settings.app_base_url.rstrip('/')}/tasks/{task_id}"
    notes = "\n".join([f"RMA: {rma}", f"Return label: {label_url or 'see the Snapback task'}",
                       f"Snapback task: {task_url}", f"Drop off by: {by:%a, %b} {by.day} (return deadline)"])
    ics_url = _write_ics(task_id, title, notes, location, start, end)
    out: Dict[str, Any] = {
        "method": "ics", "title": title, "start": start.isoformat(timespec="minutes"),
        "end": end.isoformat(timespec="minutes"), "date": start.date().isoformat(),
        "time_label": f"{start:%a, %b} {start.day} · {start:%I:%M %p}".replace(" 0", " "),
        "alarm_minutes_before": ALARM_MIN, "calendar": settings.calendar_name, "drop_off_by": by.isoformat(),
        "remind_on": start.date().isoformat(), "ics_url": ics_url, "calendar_url": None, "event_id": None,
        "task_url": task_url, "model": "ics",
    }
    attempts: List[Dict[str, Any]] = []
    mode = current_mode()
    if mode == "auto":
        try:
            out.update(_apple(title, notes, location, start, task_id, settings.calendar_show),
                       method="apple_calendar", model="osascript:Calendar")
            attempts.append({"method": "apple_calendar", "ok": True})
        except Exception as e:  # no permission / not macOS / timeout -> mock calendar
            attempts.append({"method": "apple_calendar", "ok": False, "error": str(e)[:200]})
    if out["method"] == "ics" and mode in ("auto", "mock"):
        try:
            out.update(_mock(title, notes, location, start, end, task_id), method="mock", model="mock:calendar")
            attempts.append({"method": "mock", "ok": True})
        except Exception as e:
            attempts.append({"method": "mock", "ok": False, "error": str(e)[:200]})
    out["attempts"] = attempts
    return out
