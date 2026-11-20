# API the frontend needs

The frontend runs fully on mock data today. To switch to the backend, set `USE_MOCK` in `frontend/src/lib/api.ts` to false, or run `VITE_USE_MOCK=false npm run dev`. All calls are relative (`/api/...`), and Vite proxies them to `:8000`.

Live-mode code for every endpoint below is already written (`liveApi` in `src/lib/api.ts`). Match these shapes and the UI works unchanged.

## Already working (no change needed)
| Endpoint | Used for |
|---|---|
| `GET /api/audit?task_id=…` | Audit timeline. The UI sorts by `seq`. |
| `GET /api/audit/verify` → `{ok, entries, broken_at_seq}` | "Audit chain verified ✓" / "Chain broken" badge |

The frontend also checks `prev_hash` links between a task's entries that are adjacent in the global chain (seq n → n+1).

## Needed

### 1. `GET /api/feed` → `Task[]` (newest first)
### 2. `GET /api/tasks/{task_id}` → `Task` (404 if missing)
```jsonc
{
  "task_id": "tsk_…",
  "trigger_type": "photo|chat|price_drop_minor|price_drop_major|return_window|missing_package|duplicate",
  "order_id": "NWA-10421",
  "status": "detected|awaiting_user|planned|executing|verifying|awaiting_refund|done|expired|failed",
  "decision": "return_and_replace",          // free text; "kept"/"ignored" hides it from the feed
  "title": "Return + replacement",           // short card title
  "summary": "Photo of cracked headphones → return filed, replacement ordered",
  "outcome": "$179.00 refunded · Arc ANC 2 arriving Monday",   // optional, shown when done
  "amount_usd": 179.0,                        // money recovered (or at stake while awaiting_user)
  "created_at": "…", "updated_at": "…",
  "order": { "order_id", "store", "item_name", "sku", "price", "ordered_at", "delivered_at", "return_by", "status", "image_url" }
}
```
- `title`, `summary`, `outcome` and `amount_usd` can be top-level or inside the existing `tasks.details` JSON. The frontend reads both.
- Please embed `order`. Its `image_url` must load in the browser, so use an absolute `http://localhost:8001/static/products/…png` URL (only `/api` and `/photos` are proxied).
- Set `status` to `done` only after the verifier confirms. The UI shows a spinner for `detected/planned/executing/verifying/awaiting_refund`.

### 3. `GET /api/approvals?pending=true` and `GET /api/approvals?task_id=…` → `Approval[]`
```jsonc
{
  "approval_id": "apr_…", "task_id": "tsk_…",
  "question": "Your Vortex Blender dropped from $119 to $89. Want the difference back?",
  "options": [
    { "id": "price_match",  "label": "Price match",    "detail": "Juniper refunds the difference. No hassle.", "net_savings_usd": 30.0,  "action": "execute" },
    { "id": "return_rebuy", "label": "Return & rebuy", "detail": "Needs a drop-off · $7.95 return shipping",   "net_savings_usd": 22.05, "action": "execute" },
    { "id": "ignore",       "label": "Ignore",         "detail": "Keep paying $119",                            "action": "dismiss" }
  ],
  "recommended": "price_match",            // or null
  "choice": null, "persona_inquiry_id": null, "asked_at": "…",
  "price_math": { "paid_usd": 119, "current_usd": 89, "drop_pct": 25.2 },          // major price drop cards
  "deadline":   { "return_by": "2026-11-23", "days_left": 3, "price_usd": 140 }    // return-window cards
}
```
- `action` is `execute` (Persona modal, then live progress), `dismiss` (toast, card closes) or `snooze` (toast, "remind me tomorrow").
- Note: Juniper charges $7.95 return shipping on non-defective returns (policy §2), so return & rebuy nets **$22.05**, not $30.

### 4. `POST /api/approvals/{approval_id}/answer` with body `{ "option_id": "price_match" }` → `{ task_id, status, persona_inquiry_id }`
- Must be idempotent: a second call returns the same result and never re-executes.
- The UI shows a ~1.5 s "Verifying it's you…" Persona screen *before* calling this, then shows "Verified by Persona ✓" plus the returned `persona_inquiry_id`.
- Write a `user_approved` audit entry with `authorized_by: "approval:{approval_id}"`. Execute asynchronously and return right away. The modal polls the task and audit every 0.7 s until `done`.
- For `dismiss`/`snooze` options there's no Persona step. Use `authorized_by: "user"`.

### 5. `POST /api/photo` (multipart, field `file`) → `{ task_id }`
Return immediately and run the flow asynchronously. The `/snap` stepper polls `GET /api/tasks/{id}` and `GET /api/audit?task_id=` every 0.8 s and maps step names onto its stages by keyword:

| Stage | Step names matched |
|---|---|
| Identifying item | `photo_identified` (anything with identif/embed/photo_/ocr) |
| Matching order | `order_matched` (match/extract). Put `NN%` in `decision` and the UI shows a confidence badge |
| Checking store policy | `policy_retrieved` (policy/senso/context/review) |
| Deciding | `decision_made` |
| Filing return | `return_filed` / `claim_filed` |
| Ordering replacement | `replacement_ranked`, `order_placed` |
| Verifying | `verified` / `refund_received` |

### 6. Demo helpers
- `POST /api/demo/reset`
- `POST /api/demo/trigger` with body `{ "kind": "major_price_drop" | "return_window" | "tamper" }`
  - `tamper` edits one sealed `audit_log` row without re-hashing, so the UI shows "Chain broken". Optional, but it's a strong demo moment.

## Audit entry conventions (the frontend has nice labels and icons for these)
- **Step names:** `task_detected`, `intent_classified`, `photo_identified`, `order_matched`, `policy_retrieved`, `options_computed`, `decision_made`, `user_notified`, `user_approved`, `price_rechecked`, `return_filed`, `claim_filed`, `adjustment_filed`, `replacement_ranked`, `order_placed`, `reminder_added`, `verified`, `refund_received`. Unknown names still render, humanized.
- **`decision`:** one short line (it doubles as the stepper's result text).
- **`reason`:** one plain-language sentence. Either a top-level field or `inputs.reason`.
- **`authorized_by`:** `mandate.<rule>` or `mandate:<rule>` · `approval:<approval_id>` · `verifier` · `background_loop` · `user`.
- **Formats that are fine as-is:** naive UTC timestamps (`2026-11-20 20:00:40.024017`), DATE strings, Decimals as strings, JSON columns as strings, 0/1 booleans. The frontend normalizes all of them.
