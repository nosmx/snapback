"""Run tests/scenarios/*.yaml against the running backend (:8000) + mock world (:8001); print a pass rate.

  .venv/bin/python -m scripts.run_scenarios            # all scenarios
  .venv/bin/python -m scripts.run_scenarios S05 S09    # a subset

Scenario format (YAML):
  id, name, reset (default true), setup: [actions], steps: [actions], expect: {checks}, max_seconds
Actions: merchant {path, data} · photo <path> · chat <message> · trigger {kind, price?} · loop
         wait {status: [...], timeout} · wait_trigger {trigger_type, status: [...]} · answer {option, twice?}
         checkout {store, sku, zip} · sleep <seconds>
Checks: status · decision · steps_include · steps_exclude · step_order · rule_failed · rule_passed
        decision_contains {step: text} · inputs_contain {step: text} · chain_ok · replayed
        order_status {order_id: status} · no_task {trigger_type} · tasks_done [trigger_type...]
        ingest_flag {order_id} · no_purchase · hidden_from_feed

If FIREDRILL_API_KEY is set the scenarios are meant to run through Firedrill; that integration has not
been verified, so they run locally either way and the output says so.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
API, MERCHANT = "http://localhost:8000", "http://localhost:8001"
api = httpx.Client(base_url=API, timeout=90)
shop = httpx.Client(base_url=MERCHANT, timeout=30)


class Fail(Exception):
    pass


class Ctx:
    def __init__(self) -> None:
        self.task_id: Optional[str] = None
        self.answers: List[Dict[str, Any]] = []


def _task(tid: str) -> Dict[str, Any]:
    return api.get(f"/api/tasks/{tid}").json()


def _steps(tid: str) -> List[Dict[str, Any]]:
    return sorted(api.get("/api/audit", params={"task_id": tid}).json(), key=lambda e: e["seq"])


def _wait(tid: str, statuses: List[str], timeout: float) -> Dict[str, Any]:
    t0 = time.time()
    while time.time() - t0 < timeout:
        t = _task(tid)
        if t["status"] in statuses:
            return t
        time.sleep(0.5)
    raise Fail(f"task {tid} stayed '{_task(tid)['status']}' (wanted {statuses})")


def do(action: Dict[str, Any], ctx: Ctx) -> None:
    (kind, arg), = action.items()
    if kind == "merchant":
        r = shop.post(arg["path"], data={k: str(v) for k, v in (arg.get("data") or {}).items()})
        if r.status_code >= 400:
            raise Fail(f"merchant {arg['path']} -> {r.status_code}")
    elif kind == "photo":
        with open(ROOT / arg, "rb") as f:
            ctx.task_id = api.post("/api/photo", files={"file": (Path(arg).name, f, "image/png")}).json()["task_id"]
    elif kind == "chat":
        ctx.task_id = api.post("/api/chat", json={"message": arg}).json()["task_id"]
    elif kind == "trigger":
        r = api.post("/api/demo/trigger", json=arg).json()
        ctx.task_id = r.get("task_id") or ctx.task_id
    elif kind == "loop":
        api.post("/api/loop/run")
    elif kind == "wait":
        _wait(ctx.task_id, arg.get("status", ["done"]), arg.get("timeout", 45))
    elif kind == "wait_trigger":
        t0 = time.time()
        while time.time() - t0 < arg.get("timeout", 30):
            hit = next((t for t in api.get("/api/feed").json() if t["trigger_type"] == arg["trigger_type"]), None)
            if hit:
                ctx.task_id = hit["task_id"]
                break
            time.sleep(0.5)
        if not ctx.task_id:
            raise Fail(f"no {arg['trigger_type']} task appeared")
        _wait(ctx.task_id, arg.get("status", ["done"]), arg.get("timeout", 30))
    elif kind == "answer":
        apr = None
        for _ in range(40):
            rows = api.get("/api/approvals", params={"task_id": ctx.task_id}).json() if ctx.task_id else []
            if not rows and arg.get("card"):
                rows = [a for a in api.get("/api/approvals", params={"pending": "true"}).json()
                        if (arg["card"] == "price" and a.get("price_math")) or (arg["card"] == "deadline" and a.get("deadline"))]
            apr = next((a for a in rows if not a.get("choice")), None)
            if apr:
                break
            time.sleep(0.5)
        if not apr:
            raise Fail("no pending approval to answer")
        ctx.task_id = apr["task_id"]
        for _ in range(2 if arg.get("twice") else 1):
            ctx.answers.append(api.post(f"/api/approvals/{apr['approval_id']}/answer", json={"option_id": arg["option"]}).json())
    elif kind == "checkout":
        r = shop.post(f"/s/{arg['store']}/checkout", data={"sku": arg["sku"], "ship_zip": arg.get("zip", "94110")})
        if r.status_code >= 400:
            raise Fail(f"checkout -> {r.status_code}")
    elif kind == "sleep":
        time.sleep(float(arg))
    else:
        raise Fail(f"unknown action {kind}")


def _rules(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for e in steps:
        rc = e["rules_checked"] if isinstance(e["rules_checked"], list) else json.loads(e["rules_checked"] or "[]")
        out += rc
    return out


def verify(expect: Dict[str, Any], ctx: Ctx) -> List[str]:
    problems: List[str] = []
    t = _task(ctx.task_id) if ctx.task_id else {}
    steps = _steps(ctx.task_id) if ctx.task_id else []
    names = [e["step"] for e in steps]
    by_step = {e["step"]: e for e in steps}
    for key, want in expect.items():
        if key == "status" and t.get("status") not in ([want] if isinstance(want, str) else want):
            problems.append(f"status {t.get('status')} != {want}")
        elif key == "decision" and t.get("decision") != want:
            problems.append(f"decision {t.get('decision')} != {want}")
        elif key == "steps_include":
            problems += [f"missing step {s}" for s in want if s not in names]
        elif key == "steps_exclude":
            problems += [f"unexpected step {s}" for s in want if s in names]
        elif key == "step_order":
            seqs = [next((e["seq"] for e in steps if e["step"] == s), None) for s in want]
            if None in seqs or seqs != sorted(seqs):
                problems.append(f"step order {want} -> {seqs}")
        elif key == "rule_failed" and not any(r["rule"] == want and not r["passed"] for r in _rules(steps)):
            problems.append(f"rule {want} did not fail")
        elif key == "rule_passed" and not any(r["rule"] == want and r["passed"] for r in _rules(steps)):
            problems.append(f"rule {want} did not pass")
        elif key == "decision_contains":
            for s, text in want.items():
                if text.lower() not in (by_step.get(s, {}).get("decision") or "").lower():
                    problems.append(f"{s} decision lacks '{text}': {by_step.get(s, {}).get('decision')}")
        elif key == "inputs_contain":
            for s, text in want.items():
                if text.lower() not in json.dumps(by_step.get(s, {}).get("inputs") or {}).lower():
                    problems.append(f"{s} inputs lack '{text}'")
        elif key == "chain_ok" and api.get("/api/audit/verify").json()["ok"] != want:
            problems.append(f"chain ok != {want}")
        elif key == "replayed":
            if len(ctx.answers) < 2 or ctx.answers[1].get("replayed") is not True or \
                    ctx.answers[0].get("persona_inquiry_id") != ctx.answers[1].get("persona_inquiry_id"):
                problems.append(f"second answer not a replay: {ctx.answers}")
            if names.count("user_approved") != 1:
                problems.append(f"user_approved written {names.count('user_approved')} times")
        elif key == "order_status":
            for oid, st in want.items():
                got = api.get(f"/api/orders/{oid}").json().get("status")
                if got != st:
                    problems.append(f"order {oid} status {got} != {st}")
        elif key == "no_task" and any(x["trigger_type"] == want for x in api.get("/api/feed").json()):
            problems.append(f"unexpected {want} task")
        elif key == "tasks_done":
            feed = api.get("/api/feed").json()
            for tt in want:
                hit = next((x for x in feed if x["trigger_type"] == tt), None)
                if not hit or hit["status"] != "done":
                    problems.append(f"{tt} not done ({hit and hit['status']})")
                elif "user_approved" in [e["step"] for e in _steps(hit["task_id"])]:
                    problems.append(f"{tt} needed user input")
        elif key == "ingest_flag":
            entries = api.get("/api/audit", params={"task_id": "ingest"}).json()
            hit = [e for e in entries if want in (e.get("decision") or "")]
            if not hit or not any(r["rule"] == "fetched_text_is_data" for r in _rules(hit)):
                problems.append(f"no ignored-injection flag for {want}")
        elif key == "no_purchase":
            audit = api.get("/api/audit", params={"limit": 1000}).json()
            if any(e["step"] == "order_placed" for e in audit):
                problems.append("an order was placed")
        elif key == "hidden_from_feed" and any(x["task_id"] == ctx.task_id for x in api.get("/api/feed").json()):
            problems.append("task still visible in the feed")
    return problems


def run_one(path: Path) -> Tuple[str, str, bool, float, str]:
    sc = yaml.safe_load(path.read_text())
    ctx = Ctx()
    t0 = time.time()
    try:
        if sc.get("reset", True):
            r = api.post("/api/demo/reset").json()
            if not r.get("ok"):
                raise Fail(f"reset failed: {r}")
        t1 = time.time()
        for a in (sc.get("setup") or []) + (sc.get("steps") or []):
            do(a, ctx)
        problems = verify(sc.get("expect") or {}, ctx)
        flow_s = time.time() - t1
        if flow_s > sc.get("max_seconds", 45):
            problems.append(f"too slow: {flow_s:.1f}s")
        return sc["id"], sc["name"], not problems, flow_s, "; ".join(problems) or "ok"
    except Exception as e:
        return sc["id"], sc["name"], False, time.time() - t0, f"{type(e).__name__}: {e}"


def main(argv: List[str]) -> int:
    from backend.config import settings
    files = sorted((ROOT / "tests" / "scenarios").glob("*.yaml"))
    if argv:
        files = [f for f in files if any(f.name.startswith(a) for a in argv)]
    runner = "local"
    if settings.firedrill_api_key:
        print("FIREDRILL_API_KEY found, but the Firedrill integration is not verified yet: running locally.")
    print(f"Running {len(files)} scenarios ({runner}) against {API}\n")
    results = []
    for f in files:
        sid, name, ok, dt, detail = run_one(f)
        results.append((sid, ok))
        print(f"  {'PASS' if ok else 'FAIL'}  {sid}  {dt:5.1f}s  {name:52} {'' if ok else detail}", flush=True)
    passed = sum(ok for _, ok in results)
    print(f"\nPass rate: {passed}/{len(results)} ({passed / max(len(results), 1):.0%})")
    # leave the demo in its staged state
    api.post("/api/demo/reset")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
