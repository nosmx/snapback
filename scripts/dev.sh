#!/usr/bin/env bash
# One command runs everything: mock merchant world (:8001), backend (:8000), frontend (:5173).
set -euo pipefail
cd "$(dirname "$0")/.."
trap 'kill 0' EXIT INT TERM
PY=.venv/bin
$PY/uvicorn mock.server:app --port 8001 --reload --reload-dir mock --log-level warning &
$PY/uvicorn backend.main:app --port 8000 --reload --reload-dir backend &
(cd frontend && npm run dev -- --port 5173 --strictPort) &
echo "Snapback: app http://localhost:5173 · api http://localhost:8000/api/health · mock world http://localhost:8001"
wait
