"""Drop-off reminder as an .ics calendar event (served at /api/reminders/<task_id>.ics)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Dict

from backend import clock
from backend.config import DATA_DIR

REMINDERS = DATA_DIR / "reminders"


def add_dropoff_reminder(task_id: str, title: str, by: date, location: str = "Carrier drop-off point") -> Dict[str, str]:
    REMINDERS.mkdir(parents=True, exist_ok=True)
    remind_on = max(clock.today(), by - timedelta(days=1))
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    ics = "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Snapback//EN", "BEGIN:VEVENT",
        f"UID:{task_id}@snapback", f"DTSTAMP:{stamp}",
        f"DTSTART;VALUE=DATE:{remind_on:%Y%m%d}", f"DTEND;VALUE=DATE:{remind_on + timedelta(days=1):%Y%m%d}",
        f"SUMMARY:{title}", f"DESCRIPTION:Drop off by {by.isoformat()} (Snapback task {task_id})",
        f"LOCATION:{location}", "END:VEVENT", "END:VCALENDAR", ""])
    (REMINDERS / f"{task_id}.ics").write_text(ics)
    return {"ics_url": f"http://localhost:8000/api/reminders/{task_id}.ics", "remind_on": remind_on.isoformat(),
            "drop_off_by": by.isoformat()}
