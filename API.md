# Snapback API (backend :8000)

This implements `frontend/API_NEEDS.md`. Every example below was captured from the running backend (SingleStore + real SIE + real Senso).

**Conventions**
- **Timestamps:** naive UTC (`2026-11-20 21:14:18.427796`). Dates are `YYYY-MM-DD`.
- **Async flows:** all flows run in background threads. Endpoints return immediately; poll the task and audit to watch progress.
- **When a task is `done`:** only after the verifier confirms from outside evidence (a confirmation email in the inbox and the refund posted in the bank ledger). Return and adjustment tasks wait in `awaiting_refund` until the refund lands (`REFUND_DELAY_SECONDS`, default 10).
- **`authorized_by` values:**
  - `mandate:<rule>` (e.g. `mandate:auto_return_defective`, `mandate:price_drop.auto_adjust_minor`, `mandate:price_drop.major_if`, `mandate:return_window_alert_days`, `mandate:replacement`, `mandate:auto_missing_package_claim`)
  - `approval:<approval_id>`
  - `verifier`
  - `background_loop`
  - `user`

---

## Feed and tasks

### `GET /api/feed` → `Task[]` (newest first)
Tasks whose `decision` is `kept` or `ignored` are hidden.

### `GET /api/tasks/{task_id}` → `Task` (404 if missing)
```json
{
  "task_id": "tsk_073225c59e86",
  "trigger_type": "price_drop_minor",
  "order_id": "JNH-58377",
  "status": "done",
  "decision": "price_adjustment",
  "idempotency_key": "pricedrop:JNH-58377:49.99",
  "created_at": "2026-11-20 21:14:18.427796",
  "updated_at": "2026-11-20 21:14:33.910021",
  "authorized_by": null,
  "details": { "title": "…", "summary": "…", "amount_usd": 5.0, "refund_ref": "ADJ-JNH-…", "…": "…" },
  "title": "Price adjustment: Pour-Over Kettle",
  "summary": "Pour-Over Kettle price drop → $5.00 adjustment claimed",
  "outcome": "$5.00 price adjustment refunded",
  "amount_usd": 5.0,
  "order": {
    "order_id": "JNH-58377", "store": "juniper-home", "item_name": "Pour-Over Kettle", "sku": "JNH-POUR-KTL",
    "price": 54.99, "ordered_at": "2026-11-12 00:00:00.000000", "delivered_at": "2026-11-15 00:00:00.000000",
    "return_by": "2026-12-15", "status": "active",
    "image_url": "http://localhost:8001/static/products/jnh-pour-ktl.png"
  }
}
```

**`trigger_type` values:** `photo` · `chat` · `price_drop_minor` · `price_drop_major` · `return_window` · `missing_package` · `duplicate`.

**Status lifecycle:**
- `detected`/`planned` → `executing` → `verifying` → `awaiting_refund` → `done`
- Decision flows pause in `awaiting_user` until the card is answered.
- `failed` covers flow errors and the "no verified policy, did not act" case.
- `expired` means the lower price disappeared before Snapback could act.

---

## Approvals (decision cards)

### `GET /api/approvals?pending=true` and `GET /api/approvals?task_id=…` → `Approval[]`
- `price_math` appears on major price-drop cards.
- `deadline` appears on return-window cards.
- Option `action` is one of:
  - `execute`: Persona verification, then autonomous execution.
  - `dismiss`: the card closes and nothing runs.
  - `snooze`: the card closes and one reminder comes tomorrow.

```json
{
  "approval_id": "apr_7ad14ee2243c",
  "task_id": "tsk_433dcf1b67e7",
  "question": "Your Vortex Blender dropped from $119.00 to $89.00. Want the difference back?",
  "options": [
    { "id": "price_match",  "label": "Price match",    "detail": "The store refunds the $30.00 difference. No hassle.", "net_savings_usd": 30.0,  "action": "execute" },
    { "id": "return_rebuy", "label": "Return & rebuy", "detail": "Needs a drop-off · $7.95 return shipping",            "net_savings_usd": 22.05, "action": "execute" },
    { "id": "ignore",       "label": "Ignore",         "detail": "Keep paying $119.00",                                  "net_savings_usd": null,  "action": "dismiss" }
  ],
  "recommended": "price_match",
  "choice": null, "persona_inquiry_id": null, "persona_verified": false,
  "asked_at": "2026-11-20 21:08:41.120533", "answered_at": null,
  "price_math": { "paid_usd": 119.0, "current_usd": 89.0, "drop_pct": 25.2 }
}
```

Return-window card:
```json
{
  "approval_id": "apr_513b2e788107",
  "task_id": "tsk_1f81b8bab2ca",
  "question": "Your Kestrel Outdoors Ridge Rain Jacket ($140.00) can be returned until Nov 23. Return it?",
  "options": [
    { "id": "return", "label": "Return it",          "detail": "Snapback files it, refund to your card · $6.95 return shipping", "net_savings_usd": 133.05, "action": "execute" },
    { "id": "keep",   "label": "Keep",               "detail": "Stop alerts for this item",        "action": "dismiss" },
    { "id": "snooze", "label": "Remind me tomorrow", "detail": "One more reminder before Nov 23",  "action": "snooze" }
  ],
  "recommended": null,
  "deadline": { "return_by": "2026-11-23", "days_left": 3, "price_usd": 140.0 }
}
```

### `POST /api/approvals/{approval_id}/answer`
**Request:** `{ "option_id": "price_match" }`, optionally with `"persona_inquiry_id": "inq_…"` when the frontend has already run Persona's embedded flow. In that case the backend checks that inquiry's real status instead of creating one.

**Response:**
```json
{ "task_id": "tsk_433dcf1b67e7", "status": "executing", "persona_inquiry_id": "inq_mock_3ebd50bb3fa1", "choice": "price_match" }
```

**Idempotent:** a second call returns the first result with `"replayed": true` and never re-executes. The audit log keeps exactly one `user_approved` entry.

**On `execute`:**
1. Persona: a sandbox inquiry is created (or the client's one is checked). Its id is recorded. The audit rule is `persona_verified` when the status is `completed`/`approved`, or `persona_inquiry_created` (status `created`) otherwise. With `PERSONA_REQUIRE_COMPLETED=true`, an unfinished verification blocks execution.
2. A `user_approved` entry with `authorized_by: "approval:<id>"`.
3. The flow runs in the background.

**On `dismiss`/`snooze`:** no Persona step. The `user_approved` entry has `authorized_by: "user"`. The returned `status` is the task's status after the choice is applied (`done` for keep, ignore and snooze).

**Errors:** 404 for an unknown approval, 400 for an unknown `option_id`.

---

## Photo trigger

### `POST /api/photo` (multipart, field `file`) → `{ "task_id": "tsk_…" }`
Returns immediately. iPhone `.heic` files are converted to JPEG. Steps, in order:

| # | step | decision (example) |
|---|---|---|
| 1 | `task_detected` | Photo received |
| 2 | `photo_identified` | Photo embedded · compared with 15 order images |
| 3 | `order_matched` | Matched Arc ANC Wireless Headphones · NWA-10421 · 88% |
| 4 | `policy_retrieved` | Northwind Audio policy: 30-day returns · 1-year warranty |
| 5 | `decision_made` | Return + replacement |
| 6 | `return_filed` | Return RMA-NWA-620425 filed · refund $179.00 |
| 7 | `reminder_added` | Drop-off reminder for 2026-11-26 (deadline 2026-11-27) |
| 8 | `replacement_ranked` | Chose Arc ANC 2 Wireless Headphones · $199.00 · ★4.6 |
| 9 | `order_placed` | Ordered Arc ANC 2 Wireless Headphones · NWA-39612 · $199.00 |
| 10–11 | `verified` ×2 | Return … confirmed by email / Replacement order … confirmed by email |
| 12 | `refund_received` | $179.00 posted to original payment |

**Matching rule:** the photo is accepted when the top cosine score beats the next by at least 0.04. The `NN%` figure is a softmax over the top-5 scores (τ = 0.05). For near-ties, a recent delivery breaks the tie. If it's still ambiguous, the task goes to `awaiting_user` with a top-3 card ("Which of your orders is in the photo?").

**Other branches:**
- Past the return window but under warranty: `claim_filed`.
- Not covered at all: a "Buy a replacement?" card.
- No verified Senso policy: `failed` with "did not act".

### Other cards
- **Over-cap replacement:** the return is done, and the best replacement is over `require_approval_over_usd`. Options are `buy` (execute) or `skip` (dismiss).
- **Duplicate order:** options are `cancel_extra` (execute; cancels the newer order, or returns it if already delivered) or `keep_both` (dismiss).
- **Ambiguous photo:** the top-3 orders (execute; continues the flow with that order) or `none` (dismiss).

---

## Chat trigger

### `POST /api/chat` with `{ "message": "My old Vortex Pro blender just died" }` → `{ "task_id": "tsk_…" }`
**Steps:** `task_detected` → `intent_classified` → `order_matched` (item-name overlap checked by code, `NN%`) → the same policy → rules → act path as the photo flow. For example, a 14-month-old blender gets a warranty claim:
`policy_retrieved` → `decision_made` ("Warranty claim") → `claim_filed` → `verified`.

---

## Persona

### `GET /api/persona/config`
Everything the frontend needs for `new Persona.Client({ templateId, environmentId, … })`:
```json
{ "mode": "mock", "environment_id": null, "template_id": null, "environment": "sandbox", "verified_statuses": ["completed", "approved"] }
```
`mode` turns `real` once `PERSONA_TEMPLATE_ID_APPROVAL` (`itmpl_…`) is set alongside the sandbox key.

---

## Audit
- **`GET /api/audit?task_id=…`:** that task's entries in chain order. Without `task_id`, it returns the latest entries (`limit`, default 200).
- **`GET /api/audit/verify`** → `{ "ok": true, "entries": 57, "broken_at_seq": null, "head": "…" }`
- **`GET /api/audit/export?task_id=…`:** JSON export with the chain status.

Entry shape (`reason` is in `inputs.reason`):
```json
{
  "entry_id": 1125899906842675, "seq": 24, "task_id": "tsk_b8f19634fa2c", "step": "options_computed",
  "decision": "Price match +$30.00 · return & rebuy +$22.05",
  "inputs": { "reason": "Net savings computed from the cited policy: …", "options": ["…"], "recommended": "price_match" },
  "sources": [ { "doc": "…", "section": "3. Price adjustments", "url": "http://localhost:8001/s/juniper-home/policy#price-adjustments", "retrieved_at": "…", "quote": "…", "source": "senso" } ],
  "rejected_options": [ { "option": "…", "reason": "…" } ],
  "rules_checked": [ { "rule": "policy.price_adjustment", "passed": true, "evidence": "price_adjustment_allowed=True, window 14 days from 2026-11-14 -> until 2026-11-28; today 2026-11-20" } ],
  "authorized_by": "mandate:price_drop.major_if", "model": "", "cost_usd": null, "latency_ms": null, "verified": null,
  "created_at": "2026-11-20 21:14:25.039497", "prev_hash": "ece3…", "entry_hash": "bba2…"
}
```
`entry_id` values from SingleStore are large (~1e15) but below 2^53, so they're safe as JS numbers. Sort by `seq`.

---

## Demo helpers
- **`POST /api/demo/reset`:** resets the mock world, re-seeds the DB, and **stages the demo by running the real flows**:
  - a background-loop pass: the minor drop is claimed and the lost package gets a claim, then the major-drop and return-window cards appear
  - the chat message "My old Vortex Pro blender just died…", which leads to a warranty claim

  The call returns once the 3 autonomous tasks are `done` and 2 cards are pending (typically 12–14 s, capped at `wait_s` = 19). `?stage=false` gives a plain seed.
  ```json
  { "ok": true, "seconds": 13.3, "seed_seconds": 3.3,
    "completed": [ { "task_id": "tsk_…", "trigger_type": "price_drop_minor", "outcome": "$5.00 price adjustment refunded" },
                   { "task_id": "tsk_…", "trigger_type": "missing_package",  "outcome": "$89.00 refunded for the lost package" },
                   { "task_id": "tsk_…", "trigger_type": "chat",             "outcome": "Warranty replacement ships by 2026-11-23" } ],
    "pending_approvals": 2, "audit_chain": { "ok": true, "entries": 43, "broken_at_seq": null },
    "orders": 16, "catalog": 21, "db_backend": "singlestore" }
  ```
- **`POST /api/demo/trigger`** with `{ "kind": "major_price_drop" | "return_window" | "tamper", "price": 85 }`:
  - `major_price_drop`: sets the Vortex Blender to `price` (default $89) and runs detection → `{ "ok": true, "task_id": "tsk_…" }`. This is idempotent per price level, so a new price creates a new card.
  - `return_window`: detection for the Kestrel jacket (3 days left) → `{ "ok": true, "task_id": "tsk_…" }`
  - `tamper`: edits the latest `decision_made` row without re-hashing → `{ "ok": true, "tampered_seq": 30, "task_id": "…", "verify": { "ok": false, "broken_at_seq": 30 } }`
- **`POST /api/loop/run`:** one background-loop pass now → `{ "tasks": 1, "refunds_closed": 0, "new_orders": 2 }`. It ingests new order emails (such as purchase confirmations), then detects price drops, closing windows, missing packages and duplicates, then follows up on refunds.

## Other
- **`GET /api/health`:** reports each sponsor as real or mock, plus table counts.
- **`GET /api/orders`**, **`GET /api/orders/{id}`**, **`GET /api/mandate`**
- **`GET /api/uploads/<file>`:** uploaded photos.
- **`GET /api/reminders/<task_id>.ics`:** drop-off reminders.
