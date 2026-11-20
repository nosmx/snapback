"""Snapback orchestrator API (FastAPI, :8000).

Block 1 surface: health (sponsor modes), orders, mandate, audit trail + chain verification.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend import audit
from backend.config import MOCK_DIR, integration_modes, settings
from backend.integrations.singlestore import COLUMNS, db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(title="Snapback")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/photos", StaticFiles(directory=str(MOCK_DIR / "photos")), name="photos")


@app.on_event("startup")
def _startup() -> None:
    db().start_keepalive()  # SingleStore workspace auto-suspends after ~20 min idle


@app.get("/api/health")
def health():
    d = db()
    modes = integration_modes()
    modes["db"] = "real" if d.backend == "singlestore" else "mock"
    return {
        "ok": True,
        "integrations": modes,
        "db_backend": d.backend,
        "db_fallback_reason": getattr(d, "fallback_reason", None),
        "llm_model": settings.llm_model,
        "counts": {t: d.count(t) for t in COLUMNS},
    }


@app.get("/api/orders")
def orders():
    return db().select("orders", order_by="ordered_at DESC")


@app.get("/api/orders/{order_id}")
def order(order_id: str):
    o = db().get("orders", "order_id", order_id)
    if not o:
        raise HTTPException(404, "order not found")
    return o


@app.get("/api/mandate")
def mandate():
    rows = db().select("mandates", limit=1)
    return rows[0] if rows else {}


@app.get("/api/audit")
def audit_entries(task_id: str = None, limit: int = 200):
    if task_id:
        return audit.entries_for_task(task_id)
    return db().select("audit_log", order_by="seq DESC", limit=limit)


@app.get("/api/audit/verify")
def audit_verify():
    return audit.verify_chain()
