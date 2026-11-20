# NOTES

Conflicts between `generalcontext.md` and sponsor docs, plus build decisions. Sponsor docs win.

## Build decisions (block 1)
- Approval cap (`require_approval_over_usd`) applies to the gross charge of any new order. Demo headphones are $179; the better-rated replacement is $199.
- The mandate is authoritative over the Statsig `replacement_strategy` variant. The variant is logged either way.
- Missing-package auto claim triggers on carrier `lost` / `exception` or ETA + N days. "Delivered but missing" comes through chat.
- Rules read numeric policy facts from the "Policy summary" section of the Senso response, never from local files.
- Fields are extracted and images embedded at email ingestion. The photo flow cites the stored extraction and the email URL.
- `audit_log` gets a `seq` column, because SingleStore AUTO_INCREMENT is not guaranteed sequential. Canonical JSON for hashing: sorted keys, Decimal→str, ISO-8601 UTC timestamps.
- Playwright only (no Browser Use). Frontend is Vite + React + Tailwind.
- System Python is 3.9 and Homebrew installs were blocked in the build session, so the code stays 3.9-compatible inside a project `.venv`.

## Sponsor integration findings (verified against live APIs)
- **SingleStore** 10.9 (workspace, `snapback` database). VECTOR + `DOT_PRODUCT(col, '[..]' :> VECTOR(n))` work. The audit hash chain re-verifies after the DECIMAL/JSON/DATETIME round trip.
- **Superlinked SIE** hosted at `https://api.superlinked.com`, `Authorization: Bearer sk-sie-…`, `POST /v1/{encode|score|extract}/{url-encoded model}`.
  - Image: `google/siglip-so400m-patch14-384` (1152-d). Text: `BAAI/bge-m3` (1024-d). Rerank: `Qwen/Qwen3-Reranker-0.6B`. `BAAI/bge-reranker-v2-m3` from the docs is not offered to our key. Extract: `fastino/gliner2-large-v1`.
  - Cold start: the first image call took ~5 s. 429/503 responses include `Retry-After`.
  - Extraction: GLiNER2 spans are validated against the email text. `sku` and `delivered_on` come from the labeled email lines (`field_sources` records which).
  - Real SigLIP does NOT match our Pillow placeholder "photo" to the right card (0.55 vs 0.59 for the decoy). **Real photos are required for the live photo demo.**
- **Senso** Org API at `https://apiv2.senso.ai/api/v1`, `X-API-Key: tgr_…`.
  - Ingest: `POST /org/kb/raw` (async, ~20 s to `complete`; poll `GET /org/kb/nodes/{id}` → `content.processing_status`).
  - Search: `POST /org/search/context` with `content_ids` scoped to the store's doc. It returns chunks with no AI answer. Each doc is ~5 chunks, and one chunk can span two sections, so we cite the best-matching section inside the chunk.
  - Registry of ingested docs: `data/senso_docs.json` (idempotent re-runs).
- **Amplitude** HTTP V2 `https://api2.amplitude.com/2/httpapi`. The US endpoint accepts our key (`events_ingested: 1`).

## Demo-proofing decisions (block 3)
- **Photo matching is margin-based** (top1 − top2 ≥ 0.04): SigLIP cosine scores sit around 0.4–0.8, so a fixed 0.80 threshold never fires. Confidence % = softmax over the top-5 scores (τ = 0.05).
- **Reset stages the demo by running real flows:** a loop pass plus a chat message. There are no hand-written audit rows. `REFUND_DELAY_SECONDS=3` for the demo. Senso lookups are warmed in parallel with the seed. Identical Senso queries within 120 s reuse the result, and citations keep their original `retrieved_at`.
- **SingleStore connection pool** (max 6): per-thread connections cost ~1–7 s each over TLS to us-east and leaked.
- **Persona** (per docs.withpersona.com "Creating inquiries"):
  - `POST https://api.withpersona.com/api/v1/inquiries` needs `inquiry-template-id` (`itmpl_…`).
  - `meta.auto-create-inquiry-session` returns `meta.session-token`.
  - New inquiries are `created`; only `completed`/`approved` count as verified.
  - The audit records which one happened (`persona_verified` vs `persona_inquiry_created`).
  - `PERSONA_REQUIRE_COMPLETED=true` makes execution wait for the embedded flow.
- **Statsig:** the server key works, but `replacement_strategy` returns `{}` (not configured). Console setup:
  1. Experiments → Create. Name: `replacement_strategy`. ID type: User ID.
  2. Add one parameter, `strategy` (String): Control = `same_item`, Test = `best_rated`.
  3. Allocate 100%, split 50/50, then Start.
- **Duplicate detection:** same SKU on the same day, ignoring orders Snapback placed itself. The seeded bottle pair is now on different days (a negative test), so a fresh reset shows exactly two cards.

## Block 4: live stream + calendar
- **`/api/stream` (SSE) uses an in-process ring buffer** fed by `audit.append` and task status changes. Ids are microsecond timestamps, so they stay monotonic across `--reload`. A stale `Last-Event-ID` → `resync` → the client refetches `/api/audit?since_seq=N`. Streams end when uvicorn starts shutting down (read through the installed SIGTERM handler's `should_exit`); otherwise an open EventSource would block every reload.
- **`provider` is derived, not stored:** a pure function of sealed fields (step, model label, inputs, sources), so no schema or hash change, and the stream and `/api/audit` agree.
- **Fixed: chat tasks reuse the photo flow** after the match, but their approvals had no handler, so an over-cap buy from chat sat in `executing` forever. The `chat` handler is now registered, and an `execute` answer with no handler fails the task loudly.
- **Calendar:**
  - Apple Calendar via `osascript - <argv>`: calendar created if missing, idempotent per task id (searched in the notes).
  - Slot: the next half-hour at least 1 h out (so the alert is still ahead), 9:00–18:00, no Sundays, on or before the deadline; otherwise ASAP.
  - The first call triggers the macOS Automation (TCC) prompt for the app hosting the dev servers, and the 15 s timeout falls back to the mock calendar until it's allowed.

## Block 5: real earbuds photo is the primary photo demo
- **Photo calibration** (real SIE `google/siglip-so400m-patch14-384`, 16 seeded orders, 2026-11-20). The true match for `mock/photos/demo_broken_earbuds.jpg` is NWA-10388:

  | Photo | Top | Score | Runner-up | Margin |
  |---|---|---|---|---|
  | `demo_broken_earbuds.jpg` (real photo) | NWA-10388 Pulse | **0.5461** | NWA-10421 Arc ANC 0.3969 | **0.1492** |
  | `demo_broken_headphones.png` (placeholder) | NWA-10421 Arc ANC | 0.7901 | NWA-09877 Studio 0.6434 | 0.1467 |
  | `fixtures/unrelated_photo.png` | NWA-10388 | 0.4361 | NWA-09877 0.4146 | 0.0215 |

  The rest of the earbuds photo's scores: DAC 0.397, Studio 0.381, speakers 0.373, lamp 0.350, everything else ≤ 0.29.
  - **`MATCH_FLOOR = 0.49`**: the midpoint between the unrelated photo's best score (0.436) and the real match (0.546), about ±0.05 either side. Below the floor → `no_match` (nothing filed, no top-3 card).
  - **`MATCH_MARGIN = 0.04`** is unchanged; the earbuds margin is 3.7× that.
- **Pulse product image** is a generated, generic white stem-style earbud card (no brand marks). It lives in `mock/product_images/` because `mock/static/` is being restyled separately; the mock server serves it at the same `/static/products/<name>` URL, and ingest reads the same lookup order.
- **damage_assessed:** Claude vision (`claude-opus-5-5`, image + JSON prompt) only DESCRIBES the damage. `rules.damage_evidence` reads the words (exposed/swollen/… battery) and ignores the model's own booleans. Without `ANTHROPIC_API_KEY` the description comes from the labeled sidecar for known demo photos (`mock/photos/labels.json`, audit model `mock:llm`).
- **Damaged batteries:** Northwind policy §5 plus summary keys (`damaged_battery_standard_mail: false`, `damaged_battery_methods`, refund timing). `rules.choose_return_method` picks in-store drop-off (refund at drop-off) over the battery-safe label (refund after inspection) and rejects standard mail. `decision_made` cites the Senso §5 chunk.
- **Portal:** the agent sends `return_method` as a form field (the merchant validates it and puts it in the confirmation email) and uses reason `damaged` ("Defective / damaged"). The portal and label templates don't show the method yet; that's a template change for the restyle owner.
- **Fixed: a staged-reset race.** The scheduled 30 s loop pass grabbed `LOOP_LOCK` the moment the re-seed released it, so the reset's own staging pass queued behind it (two ~3 s passes back to back), and the staged refunds landed after the 19 s cutoff. `background_loop.quiet()` now makes scheduled passes skip while a reset is staging. 5 resets in a row: 11.4–13.1 s.
- **Fixed:** continuation summary chunks were hard-labeled "5. Policy summary", which went stale once the summary moved to §6. They're now "Policy summary (continued)".

## Sponsor doc conflicts
- SIE `api.md` documents the self-hosted server (raw slashes in model paths, msgpack default). Hosted needs URL-encoded model IDs and JSON. We follow the hosted examples.
