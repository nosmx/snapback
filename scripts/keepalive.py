"""Keep the SingleStore workspace awake (it auto-suspends after ~20 min idle).

  make keepalive     # run in a spare terminal when the backend isn't running (lunch, recording)
"""
from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.integrations.singlestore import db  # noqa: E402

if __name__ == "__main__":
    d = db()
    if d.backend != "singlestore":
        sys.exit(f"SingleStore not reachable (using {d.backend}): resume the workspace in the portal, then retry.")
    while True:
        n = d.count("orders")
        print(f"{datetime.now():%H:%M:%S} SingleStore awake ({n} orders)", flush=True)
        time.sleep(240)
