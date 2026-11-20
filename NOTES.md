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

## Sponsor doc conflicts
- SIE `api.md` documents the self-hosted server (raw slashes in model paths, msgpack default). Hosted needs URL-encoded model IDs and JSON. We follow the hosted examples.
