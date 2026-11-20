# Snapback

A post-purchase autopilot for the Personal Agents Hackathon. Snapback watches your orders and handles everything after checkout: returns, warranty claims, price drops, missing packages and replacement purchases. Every step is backed by cited context and recorded in a tamper-evident audit trail.

> Built against a mock environment with fictional stores (Northwind Audio, Juniper Home, Kestrel Outdoors). Checkout is mocked, and the agent never sees card data.

## Run it

```bash
make setup     # venv + deps + Chromium + frontend packages; copies .env.example -> .env
make reset     # reset the mock world (with demo staging) and seed the database
make dev       # mock world :8001 · backend :8000 · app :5173
```

Every sponsor integration falls back to a labeled mock when its credentials are missing, so the full demo runs with an empty `.env`. `GET /api/health` shows which integrations are real and which are mock.

## Layout

- `backend/`: FastAPI orchestrator: rules, audit hash chain, sponsor integrations (`integrations/`), flows, triggers.
- `mock/`: fictional merchant world on :8001: stores, returns portal (order # + ZIP), checkout, carrier, the user's inbox and bank ledger, and a demo admin panel at `/admin`.
- `frontend/`: Vite + React + Tailwind app.
- `scripts/`: seed, Senso loader, dev runner.

## Sponsor tools

Senso (cited policy context) · Superlinked SIE (image embedding, extraction, rerank) · SingleStore (orders, vectors, tasks, approvals, audit log) · Persona (mandate and approval verification) · Amplitude + Statsig (events and the replacement-strategy flag) · Claude (explanations only; rules decide).
