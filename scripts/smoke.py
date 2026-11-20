"""End-to-end smoke test against the RUNNING backend (:8000) and mock world (:8001).

  .venv/bin/python -m scripts.smoke

Flows (each must reach "done" with a valid audit chain, in < 30 s):
  g) background loop: missing package + minor price drop, no user input (checked right after reset)
  a) photo -> return + replacement + refund
  b) major price drop -> price match -> adjustment + refund verified
  e) the same approval answered twice -> identical result, nothing re-executed
  c) major price drop -> return & rebuy -> new order placed BEFORE the return is filed
  d) return window -> return completed autonomously (no replacement)
  f) tamper -> /api/audit/verify ok:false; demo reset -> ok:true
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

API = "http://localhost:8000"
ROOT = Path(__file__).resolve().parent.parent
LIMIT_S = 30.0
c = httpx.Client(base_url=API, timeout=60)
results: List[Tuple[str, bool, float, str]] = []


class Fail(Exception):
    pass


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise Fail(msg)


def wait_task(tid: str, until=("done",), timeout: float = 45) -> Dict[str, Any]:
    t0 = time.time()
    while time.time() - t0 < timeout:
        t = c.get(f"/api/tasks/{tid}").json()
        if t["status"] in until or t["status"] in ("failed", "expired"):
            return t
        time.sleep(0.5)
    return c.get(f"/api/tasks/{tid}").json()


def steps(tid: str) -> List[Dict[str, Any]]:
    return sorted(c.get("/api/audit", params={"task_id": tid}).json(), key=lambda e: e["seq"])


def chain_ok() -> bool:
    return c.get("/api/audit/verify").json()["ok"]


def pending(kind: str) -> Dict[str, Any]:
    for _ in range(40):
        for a in c.get("/api/approvals", params={"pending": "true"}).json():
            if (kind == "price" and a.get("price_math")) or (kind == "deadline" and a.get("deadline")):
                return a
        time.sleep(0.5)
    raise Fail(f"no pending {kind} card")


def run(name: str, fn: Callable[[], str]) -> None:
    t0 = time.time()
    try:
        detail = fn()
        dt = time.time() - t0
        ok = dt <= LIMIT_S
        results.append((name, ok, dt, detail if ok else f"too slow ({dt:.1f}s > {LIMIT_S:.0f}s) · {detail}"))
    except Exception as e:
        results.append((name, False, time.time() - t0, f"{type(e).__name__}: {e}"))


# ---------------- flows ----------------

def flow_g() -> str:
    r = c.post("/api/demo/reset").json()
    check(r.get("ok"), f"reset did not stage: {r}")
    feed = c.get("/api/feed").json()
    auto = {t["trigger_type"]: t for t in feed if t["trigger_type"] in ("missing_package", "price_drop_minor")}
    check(len(auto) == 2, f"expected missing_package + price_drop_minor, got {list(auto)}")
    for t in auto.values():
        check(t["status"] == "done", f"{t['trigger_type']} status {t['status']}")
        st = steps(t["task_id"])
        check(not any(e["step"] == "user_approved" for e in st), f"{t['trigger_type']} needed user input")
        check(any(e["step"] == "refund_received" for e in st), f"{t['trigger_type']} has no refund_received")
    check(chain_ok(), "audit chain broken")
    return f"reset {r['seconds']}s · claim + adjustment done with no user input · {r['pending_approvals']} cards pending"


def flow_a() -> str:
    with open(ROOT / "mock" / "photos" / "demo_broken_headphones.png", "rb") as f:
        tid = c.post("/api/photo", files={"file": ("broken_headphones.png", f, "image/png")}).json()["task_id"]
    t = wait_task(tid)
    check(t["status"] == "done", f"status {t['status']}: {t.get('summary')}")
    names = [e["step"] for e in steps(tid)]
    for s in ("photo_identified", "order_matched", "policy_retrieved", "decision_made", "return_filed",
              "replacement_ranked", "order_placed", "verified", "refund_received"):
        check(s in names, f"missing step {s}")
    check(t["decision"] == "return_and_replace", f"decision {t['decision']}")
    check(t["order"]["image_url"].startswith("http://localhost:8001/"), "order image_url not absolute")
    check(chain_ok(), "audit chain broken")
    return t.get("outcome") or ""


_b_answer: Dict[str, Any] = {}


def flow_b() -> str:
    a = pending("price")
    r = c.post(f"/api/approvals/{a['approval_id']}/answer", json={"option_id": "price_match"}).json()
    _b_answer.update(r, approval_id=a["approval_id"])
    check(r.get("persona_inquiry_id"), "no persona_inquiry_id recorded")
    t = wait_task(r["task_id"])
    check(t["status"] == "done", f"status {t['status']}: {t.get('summary')}")
    names = [e["step"] for e in steps(r["task_id"])]
    for s in ("user_approved", "price_rechecked", "adjustment_filed", "verified", "refund_received"):
        check(s in names, f"missing step {s}")
    check(chain_ok(), "audit chain broken")
    return t.get("outcome") or ""


def flow_e() -> str:
    check(bool(_b_answer), "flow b did not run")
    again = c.post(f"/api/approvals/{_b_answer['approval_id']}/answer", json={"option_id": "price_match"}).json()
    check(again.get("replayed") is True, f"second answer not marked replayed: {again}")
    check(again["persona_inquiry_id"] == _b_answer["persona_inquiry_id"], "persona inquiry changed on replay")
    st = steps(_b_answer["task_id"])
    check(sum(e["step"] == "user_approved" for e in st) == 1, "user_approved written twice")
    check(sum(e["step"] == "adjustment_filed" for e in st) == 1, "adjustment executed twice")
    return "second call replayed the first result; one user_approved, one adjustment"


def flow_c() -> str:
    tid = c.post("/api/demo/trigger", json={"kind": "major_price_drop", "price": 85}).json()["task_id"]
    a = None
    for _ in range(40):
        a = next((x for x in c.get("/api/approvals", params={"task_id": tid}).json() if not x.get("choice")), None)
        if a:
            break
        time.sleep(0.5)
    check(a is not None, "no card for the $85 drop")
    r = c.post(f"/api/approvals/{a['approval_id']}/answer", json={"option_id": "return_rebuy"}).json()
    t = wait_task(r["task_id"])
    check(t["status"] == "done", f"status {t['status']}: {t.get('summary')}")
    st = steps(r["task_id"])
    seq = {e["step"]: e["seq"] for e in st if e["step"] in ("order_placed", "return_filed")}
    check(len(seq) == 2, f"missing order_placed/return_filed: {seq}")
    check(seq["order_placed"] < seq["return_filed"], f"return filed before the new order: {seq}")
    check(chain_ok(), "audit chain broken")
    return f"order_placed #{seq['order_placed']} < return_filed #{seq['return_filed']} · {t.get('outcome')}"


def flow_d() -> str:
    a = pending("deadline")
    r = c.post(f"/api/approvals/{a['approval_id']}/answer", json={"option_id": "return"}).json()
    t = wait_task(r["task_id"])
    check(t["status"] == "done", f"status {t['status']}: {t.get('summary')}")
    names = [e["step"] for e in steps(r["task_id"])]
    for s in ("user_approved", "return_filed", "reminder_added", "verified", "refund_received"):
        check(s in names, f"missing step {s}")
    check("order_placed" not in names, "a replacement was bought for a non-defective return")
    check(chain_ok(), "audit chain broken")
    return t.get("outcome") or ""


def flow_f() -> str:
    r = c.post("/api/demo/trigger", json={"kind": "tamper"}).json()
    v = c.get("/api/audit/verify").json()
    check(v["ok"] is False and v["broken_at_seq"] == r["tampered_seq"], f"tamper not detected: {v}")
    rr = c.post("/api/demo/reset").json()
    check(c.get("/api/audit/verify").json()["ok"] is True, "reset did not restore the chain")
    return f"broken at seq {v['broken_at_seq']} → reset ({rr['seconds']}s) → chain ok"


def main() -> int:
    try:
        health = c.get("/api/health").json()
    except Exception as e:
        print(f"backend not reachable at {API}: {e}")
        return 2
    print("integrations:", health["integrations"])
    for name, fn in (("g  background loop (no user input)", flow_g), ("a  photo → return + replacement", flow_a),
                     ("b  major drop → price match", flow_b), ("e  same approval answered twice", flow_e),
                     ("c  major drop → return & rebuy", flow_c), ("d  return window → return", flow_d),
                     ("f  tamper → broken; reset → ok", flow_f)):
        run(name, fn)
        n, ok, dt, detail = results[-1]
        print(f"  {'PASS' if ok else 'FAIL'}  {dt:5.1f}s  {n:36} {detail}", flush=True)
    passed = sum(1 for r in results if r[1])
    print(f"\n{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
