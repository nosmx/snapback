// Mock world for the frontend. Mirrors the backend seed (mock/emails/orders.yaml, mock/policies/*.md):
// same order numbers, prices and policy clauses, so switching USE_MOCK off changes data, not meaning.
// All audit entries live in ONE global hash chain ordered by seq, like backend/audit.py.
import type {
  Approval, AuditEntry, DemoTrigger, Order, RejectedOption, RuleCheck, Source, Task, TaskStatus,
} from './types'
import { GENESIS, computeEntryHash, verifyEntries } from './chain'

export const MOCK_WORLD = 'http://localhost:8001'
const MIN = 60_000
const DAY = 86_400_000
const iso = (t: number) => new Date(t).toISOString()
const img = (sku: string) => `/products/${sku.toLowerCase()}.png`

type MockTask = Task & { hidden?: boolean }
interface MockDb {
  version: number
  orders: Order[]
  tasks: MockTask[]
  approvals: Approval[]
  audit: AuditEntry[]
  nextEntryId: number
  counter: number
}

interface Draft {
  step: string
  decision: string
  reason: string
  sources?: Omit<Source, 'retrieved_at'>[]
  rejected_options?: RejectedOption[]
  rules_checked?: RuleCheck[]
  authorized_by?: string | null
  model?: string | null
  cost_usd?: number | null
  latency_ms?: number | null
  verified?: boolean | null
}

// ---------- sources ----------
const POLICY_DOC: Record<string, string> = {
  'northwind-audio': 'Northwind Audio — Returns, Price Adjustment and Warranty Policy',
  'juniper-home': 'Juniper Home — Returns, Price Adjustment and Warranty Policy',
  'kestrel-outdoors': 'Kestrel Outdoors — Returns, Pricing and Guarantee Policy',
}
const policy = (store: string, section: string) => ({
  doc: `${POLICY_DOC[store]} (Senso)`,
  section,
  url: `${MOCK_WORLD}/s/${store}/policy`,
})
const email = (id: string, section: string) => ({ doc: `Order confirmation email ${id}`, section, url: `${MOCK_WORLD}/inbox/${id}` })
const bank = (section: string) => ({ doc: 'Bank transactions (read-only)', section, url: `${MOCK_WORLD}/bank` })
const portal = (store: string, section: string) => ({ doc: `${storeLabel(store)} returns portal`, section, url: `${MOCK_WORLD}/s/${store}/returns` })
const priceFeed = (store: string, sku: string, section: string) => ({
  doc: `${storeLabel(store)} live price`, section, url: `${MOCK_WORLD}/s/${store}/api/price/${sku}`,
})
function storeLabel(s: string) {
  return ({ 'northwind-audio': 'Northwind Audio', 'juniper-home': 'Juniper Home', 'kestrel-outdoors': 'Kestrel Outdoors' } as Record<string, string>)[s] ?? s
}

// ---------- chain ----------
function append(db: MockDb, task_id: string, d: Draft, at: number): AuditEntry {
  const last = db.audit[db.audit.length - 1]
  const created_at = iso(at)
  const e: AuditEntry = {
    entry_id: db.nextEntryId++,
    seq: (last?.seq ?? 0) + 1,
    task_id,
    step: d.step,
    decision: d.decision,
    reason: d.reason,
    sources: (d.sources ?? []).map((s) => ({ ...s, retrieved_at: created_at })),
    rejected_options: d.rejected_options ?? [],
    rules_checked: d.rules_checked ?? [],
    authorized_by: d.authorized_by ?? null,
    model: d.model ?? null,
    cost_usd: d.cost_usd ?? null,
    latency_ms: d.latency_ms ?? null,
    verified: d.verified ?? null,
    created_at,
    prev_hash: last?.entry_hash ?? GENESIS,
    entry_hash: '',
  }
  e.entry_hash = computeEntryHash(e.prev_hash, e)
  db.audit.push(e)
  return e
}

function appendRun(db: MockDb, task_id: string, drafts: Draft[], start: number) {
  let t = start
  for (const d of drafts) {
    t += (d.latency_ms ?? 200) + 350
    append(db, task_id, d, t)
  }
  return t
}

// ---------- step drafts ----------
function headphoneDrafts(o: Order, photoUrl: string, photoName: string): Draft[] {
  return [
    {
      step: 'photo_identified',
      decision: 'Identified over-ear headphones with a cracked headband',
      reason: 'Image embedding computed; OCR read “ARC ANC” printed on the left earcup.',
      sources: [{ doc: 'Your photo', section: photoName, url: photoUrl }],
      rules_checked: [
        { rule: 'Photo is usable', passed: true, evidence: 'Item fills 62% of frame, sharpness 0.81 ≥ 0.40' },
        { rule: 'Visible damage detected', passed: true, evidence: 'Crack across the headband hinge' },
      ],
      authorized_by: 'mandate.auto_return_defective',
      model: 'SIE · google/siglip-so400m-patch14-384',
      cost_usd: 0.00018,
      latency_ms: 840,
    },
    {
      step: 'order_matched',
      decision: `Matched Northwind Audio order ${o.order_id} · 94% confidence`,
      reason: 'Closest product image across all your order emails, far ahead of the runner-up.',
      sources: [
        email('e01', `Item image + fields extracted at ingestion: ${o.order_id}, $179.00, ZIP 94110`),
        { doc: 'SingleStore · orders.image_embedding', section: 'DOT_PRODUCT vector search, top 3 of 15 orders', url: '' },
      ],
      rejected_options: [
        { option: 'Northwind Pulse Earbuds · NWA-10388', reason: 'Similarity 0.20 — different product shape' },
        { option: 'Northwind Shelf Speaker · NWA-10502', reason: 'Similarity 0.11 — not delivered yet' },
      ],
      rules_checked: [
        { rule: 'Match confidence ≥ 0.80', passed: true, evidence: '0.94' },
        { rule: 'Margin over runner-up ≥ 0.15', passed: true, evidence: '0.94 vs 0.20' },
        { rule: 'Order fields complete', passed: true, evidence: 'order #, date, price, ship ZIP all present in email' },
        { rule: 'Store in allowed_stores', passed: true, evidence: 'northwind-audio' },
      ],
      authorized_by: 'mandate.auto_return_defective',
      model: 'SingleStore vector search + SIE · fastino/gliner2-large-v1',
      cost_usd: 0.00009,
      latency_ms: 310,
    },
    {
      step: 'policy_retrieved',
      decision: 'Retrieved Northwind Audio return and warranty policy',
      reason: '30-day window from delivery; defective items return free with no restocking fee.',
      sources: [
        policy('northwind-audio', '§1 Returns — “within 30 days of the delivery date”'),
        policy('northwind-audio', '§2 Fees — “Defective or damaged items: return shipping is free and no restocking fee applies”'),
        policy('northwind-audio', '§4 Warranty — “1-year limited warranty from the delivery date”'),
        { doc: 'Arc ANC review summary (Senso)', section: '412 reviews · 3.1★ · hinge cracks in 18% of reviews', url: `${MOCK_WORLD}/s/northwind-audio` },
      ],
      rules_checked: [
        { rule: 'Verified policy exists in Senso', passed: true, evidence: 'Effective Sep 1, 2026 · 5 chunks' },
        { rule: 'Policy retrieved within 24h', passed: true, evidence: 'Retrieved just now' },
      ],
      authorized_by: 'mandate.auto_return_defective',
      model: 'Senso · context search',
      cost_usd: 0.002,
      latency_ms: 1180,
    },
    {
      step: 'decision_made',
      decision: 'Return for a full refund, then buy a replacement',
      reason: 'Delivered 12 days ago — inside the 30-day window — and visibly defective, so a free return beats a warranty repair.',
      rejected_options: [
        { option: 'Warranty claim', reason: 'Repair or replace at Northwind’s discretion takes 2–3 weeks; a return refunds $179 now' },
        { option: 'Do nothing', reason: 'You would be left with broken headphones and no refund' },
      ],
      rules_checked: [
        { rule: 'Within return window', passed: true, evidence: 'Delivered 12 days ago ≤ 30 days' },
        { rule: 'Defect reported', passed: true, evidence: 'Photo shows a cracked hinge' },
        { rule: 'Verified policy cited', passed: true, evidence: '§1 Returns, §2 Fees' },
        { rule: 'mandate.auto_return_defective', passed: true, evidence: 'true' },
        { rule: 'mandate.replacement.enabled', passed: true, evidence: 'true' },
      ],
      authorized_by: 'mandate.auto_return_defective',
      model: 'rules engine → claude-sonnet-5-5 (explanation)',
      cost_usd: 0.0042,
      latency_ms: 2100,
    },
    {
      step: 'return_filed',
      decision: 'Return RMA-NWA-88213 filed · prepaid label saved',
      reason: 'Looked up the order with ZIP 94110, chose “Defective”, refund to original payment. Drop-off reminder set for tomorrow.',
      sources: [
        portal('northwind-audio', 'Confirmation page · RMA-NWA-88213 · refund $179.00'),
        { doc: 'Return label (PDF)', section: 'RMA-NWA-88213', url: `${MOCK_WORLD}/s/northwind-audio/returns/label/RMA-NWA-88213` },
      ],
      rules_checked: [
        { rule: 'Idempotency key unused', passed: true, evidence: `return:${o.order_id}` },
        { rule: 'Confirmation page shows an RMA', passed: true, evidence: 'RMA-NWA-88213' },
        { rule: 'Refund method = original payment', passed: true, evidence: 'mandate.refund_method' },
        { rule: 'No restocking fee charged', passed: true, evidence: '$0.00 (defective)' },
      ],
      authorized_by: 'mandate.auto_return_defective',
      model: 'Playwright (scripted)',
      cost_usd: 0,
      latency_ms: 6400,
    },
    {
      step: 'replacement_ranked',
      decision: 'Chose Arc ANC 2 ($199) as the replacement',
      reason: 'Reviews flag the original’s hinge (3.1★), so the mandate picks the best-rated option within +$30.',
      sources: [
        { doc: 'Arc ANC review summary (Senso)', section: '“Hinge cracks mentioned in 18% of reviews”', url: `${MOCK_WORLD}/s/northwind-audio` },
        { doc: 'Arc ANC 2 review summary (Senso)', section: '289 reviews · 4.6★ · “metal hinge, no failures reported”', url: `${MOCK_WORLD}/s/northwind-audio` },
      ],
      rejected_options: [
        { option: 'Same item — Arc ANC ($179)', reason: 'Poor reviews: 3.1★, recurring hinge failures' },
        { option: 'Arc ANC Pro ($249)', reason: '+$70 exceeds the +$30 limit and the $200 approval cap' },
        { option: 'Studio MH ($149)', reason: 'No noise cancelling; 3.9★' },
      ],
      rules_checked: [
        { rule: 'Strategy: same item unless poor reviews', passed: true, evidence: 'Arc ANC 3.1★ < 3.5★ → best rated' },
        { rule: 'Extra spend ≤ $30', passed: true, evidence: '+$20.00' },
        { rule: 'In stock', passed: true, evidence: 'Northwind catalog: 34 units' },
        { rule: 'Statsig replacement_strategy logged', passed: true, evidence: 'variant best_rated (mandate is authoritative)' },
      ],
      authorized_by: 'mandate.replacement.strategy',
      model: 'SIE · Qwen/Qwen3-Reranker-0.6B',
      cost_usd: 0.00021,
      latency_ms: 380,
    },
    {
      step: 'order_placed',
      decision: 'Ordered Arc ANC 2 · order NWA-10611 · $199.00',
      reason: 'Placed on Northwind checkout with a stored payment token — the agent never sees card numbers.',
      sources: [{ doc: 'Northwind Audio checkout', section: 'Order confirmation NWA-10611', url: `${MOCK_WORLD}/s/northwind-audio/checkout` }],
      rules_checked: [
        { rule: 'Total ≤ $200 approval cap', passed: true, evidence: '$199.00' },
        { rule: 'Extra spend ≤ $30', passed: true, evidence: '+$20.00 over the original' },
        { rule: 'Store in allowed_stores', passed: true, evidence: 'northwind-audio' },
        { rule: 'Idempotency key unused', passed: true, evidence: `replace:${o.order_id}` },
      ],
      authorized_by: 'mandate.replacement.max_extra_spend_usd',
      model: 'Playwright (scripted)',
      cost_usd: 0,
      latency_ms: 4800,
    },
    {
      step: 'verified',
      decision: 'Verified: $179.00 refund posted · replacement confirmed',
      reason: 'Checked the bank record and both confirmation emails, not the portal’s own success message.',
      sources: [
        bank('Credit +$179.00 · Northwind Audio · Refund RMA-NWA-88213'),
        { doc: 'Return confirmation email', section: 'RMA-NWA-88213 · refund $179.00', url: `${MOCK_WORLD}/inbox` },
        { doc: 'Order confirmation email', section: 'NWA-10611 · Arc ANC 2 · arriving Mon', url: `${MOCK_WORLD}/inbox` },
      ],
      rules_checked: [
        { rule: 'Refund amount matches', passed: true, evidence: '$179.00 = $179.00' },
        { rule: 'Refund to original payment', passed: true, evidence: 'Card ending ••42 (from bank feed)' },
        { rule: 'Replacement confirmation received', passed: true, evidence: 'Email from orders@northwind-audio.example' },
      ],
      authorized_by: 'verifier',
      model: 'Verifier (email + bank)',
      cost_usd: 0,
      latency_ms: 900,
      verified: true,
    },
  ]
}

// ---------- seed ----------
function seed(): MockDb {
  const now = Date.now()
  const db: MockDb = { version: 3, orders: [], tasks: [], approvals: [], audit: [], nextEntryId: 1001, counter: 0 }

  const order = (o: Omit<Order, 'ordered_at' | 'delivered_at' | 'return_by'> & { ordered: number; delivered: number | null; window: number | null }) => {
    const delivered_at = o.delivered === null ? null : iso(now - o.delivered * DAY)
    const return_by = o.delivered === null || o.window === null ? null : iso(now - o.delivered * DAY + o.window * DAY)
    const { ordered, delivered, window, ...rest } = o
    void delivered
    void window
    const full: Order = { ...rest, ordered_at: iso(now - ordered * DAY), delivered_at, return_by }
    db.orders.push(full)
    return full
  }

  const headphones = order({ order_id: 'NWA-10421', store: 'northwind-audio', item_name: 'Arc ANC Headphones', sku: 'NWA-ARC-ANC', price: 179, status: 'returned', image_url: img('NWA-ARC-ANC'), ordered: 15, delivered: 12, window: 30 })
  const blender = order({ order_id: 'JNH-58213', store: 'juniper-home', item_name: 'Vortex Blender', sku: 'JNH-VORTEX-BL', price: 119, status: 'active', image_url: img('JNH-VORTEX-BL'), ordered: 9, delivered: 6, window: 30 })
  const dac = order({ order_id: 'NWA-10466', store: 'northwind-audio', item_name: 'USB-C DAC Cable', sku: 'NWA-DAC-USBC', price: 49, status: 'active', image_url: img('NWA-DAC-USBC'), ordered: 11, delivered: 8, window: 30 })
  const jacket = order({ order_id: 'KSO-77120', store: 'kestrel-outdoors', item_name: 'Ridge Rain Jacket', sku: 'KSO-RIDGE-JKT', price: 140, status: 'active', image_url: img('KSO-RIDGE-JKT'), ordered: 46, delivered: 42, window: 45 })
  const tent = order({ order_id: 'KSO-77215', store: 'kestrel-outdoors', item_name: 'Basecamp 2P Tent', sku: 'KSO-BASECAMP-2P', price: 239, status: 'claimed', image_url: img('KSO-BASECAMP-2P'), ordered: 11, delivered: null, window: 45 })
  const oldBlender = order({ order_id: 'JNH-49870', store: 'juniper-home', item_name: 'Vortex Pro Blender', sku: 'JNH-VORTEX-PRO', price: 159, status: 'claimed', image_url: img('JNH-VORTEX-PRO'), ordered: 430, delivered: 426, window: 30 })

  const task = (t: Omit<Task, 'updated_at'>) => {
    const full: MockTask = { ...t, updated_at: t.created_at }
    db.tasks.push(full)
    return full
  }
  const finish = (t: MockTask, end: number) => {
    t.updated_at = iso(end)
  }

  // 6. Warranty claim (chat) — yesterday
  {
    const start = now - 26 * 60 * MIN
    const t = task({
      task_id: 'tsk_warranty_blender', trigger_type: 'chat', order_id: oldBlender.order_id, status: 'done', decision: 'warranty_claim',
      title: 'Warranty claim filed', summary: '“My blender died” → 14 months old, return window closed → 2-year warranty claim filed',
      amount_usd: 159, created_at: iso(start), outcome: 'Claim WC-JNH-2207 approved · replacement unit ships tomorrow',
    })
    const end = appendRun(db, t.task_id, [
      {
        step: 'intent_classified', decision: 'Matched “my blender died” to Juniper Home order JNH-49870',
        reason: 'Intent is “defective item”; this is the only blender in your order history.',
        sources: [{ doc: 'Your chat message', section: '“ugh my blender died after a year, won’t turn on at all”', url: '' },{ doc: 'Order confirmation email', section: 'JNH-49870 · Vortex Pro Blender · $159.00', url: `${MOCK_WORLD}/inbox` }],
        rejected_options: [{ option: 'Vortex Blender · JNH-58213', reason: 'Delivered 6 days ago — you said it died “after a year”' }],
        rules_checked: [{ rule: 'Intent confidence ≥ 0.85', passed: true, evidence: 'defective_item 0.97' }, { rule: 'Single matching order', passed: true, evidence: '1 blender delivered > 30 days ago' }],
        authorized_by: 'mandate.auto_return_defective', model: 'claude-haiku-5-5', cost_usd: 0.00041, latency_ms: 620,
      },
      {
        step: 'policy_retrieved', decision: 'Retrieved Juniper Home return and warranty policy',
        reason: 'Returns close 30 days after delivery; small kitchen appliances carry a 2-year warranty.',
        sources: [policy('juniper-home', '§1 Returns — “within 30 days of delivery for a full refund”'), policy('juniper-home', '§4 Warranty — “Small kitchen appliances (blenders, kettles, toasters) include a 2-year limited warranty from delivery”')],
        rules_checked: [{ rule: 'Verified policy exists in Senso', passed: true, evidence: 'Effective Aug 15, 2026' }],
        authorized_by: 'mandate.auto_return_defective', model: 'Senso · context search', cost_usd: 0.002, latency_ms: 1040,
      },
      {
        step: 'decision_made', decision: 'File a warranty claim',
        reason: 'Delivered 14 months ago: the return window is long closed, but the 2-year appliance warranty still covers it.',
        rejected_options: [
          { option: 'Return for refund', reason: 'Window closed 13 months ago (30-day limit)' },
          { option: 'Buy a new Vortex Pro ($159)', reason: 'Warranty covers a replacement at $0' },
        ],
        rules_checked: [
          { rule: 'Within return window', passed: false, evidence: 'Delivered 426 days ago > 30 days' },
          { rule: 'Under warranty', passed: true, evidence: '426 days ≤ 730 days' },
          { rule: 'Defect reported', passed: true, evidence: '“won’t turn on at all”' },
          { rule: 'Verified policy cited', passed: true, evidence: '§4 Warranty' },
        ],
        authorized_by: 'mandate.auto_return_defective', model: 'rules engine → claude-sonnet-5-5 (explanation)', cost_usd: 0.0038, latency_ms: 1900,
      },
      {
        step: 'claim_filed', decision: 'Warranty claim WC-JNH-2207 filed · free label saved',
        reason: 'Filed on the Juniper portal with order # and your description; defective items get a prepaid label.',
        sources: [portal('juniper-home', 'Warranty claim confirmation · WC-JNH-2207')],
        rules_checked: [{ rule: 'Idempotency key unused', passed: true, evidence: 'warranty:JNH-49870' }, { rule: 'Confirmation number shown', passed: true, evidence: 'WC-JNH-2207' }],
        authorized_by: 'mandate.auto_return_defective', model: 'Playwright (scripted)', cost_usd: 0, latency_ms: 5600,
      },
      {
        step: 'verified', decision: 'Verified: claim approved, replacement unit ships tomorrow',
        reason: 'Confirmed from Juniper’s approval email, not from the portal response.',
        sources: [{ doc: 'Juniper Home email', section: '“Your warranty claim WC-JNH-2207 is approved”', url: `${MOCK_WORLD}/inbox` }],
        rules_checked: [{ rule: 'Approval email received', passed: true, evidence: 'support@juniper-home.example' }, { rule: 'Replacement cost to you', passed: true, evidence: '$0.00' }],
        authorized_by: 'verifier', model: 'Verifier (email)', cost_usd: 0, latency_ms: 700, verified: true,
      },
    ], start)
    finish(t, end)
  }

  // 3. Headphones photo flow — yesterday
  {
    const start = now - 20 * 60 * MIN
    const t = task({
      task_id: 'tsk_photo_headphones', trigger_type: 'photo', order_id: headphones.order_id, status: 'done', decision: 'return_and_replace',
      title: 'Return + replacement', summary: 'Photo of cracked headphones → return filed, better-rated replacement ordered',
      amount_usd: 179, created_at: iso(start), outcome: '$179.00 refunded · Arc ANC 2 arriving Monday',
    })
    finish(t, appendRun(db, t.task_id, headphoneDrafts(headphones, '/demo/demo_broken_headphones.png', 'demo_broken_headphones.png · 640×640'), start))
  }

  // 1. Missing package — 5h ago
  {
    const start = now - 5 * 60 * MIN
    const t = task({
      task_id: 'tsk_missing_tent', trigger_type: 'missing_package', order_id: tent.order_id, status: 'done', decision: 'missing_package_claim',
      title: 'Missing package claim', summary: 'Carrier lost your tent → claim filed, Kestrel shipped a replacement at no cost',
      amount_usd: 239, created_at: iso(start), outcome: 'Replacement shipped · tracking KSO4T81877 · arriving Saturday',
    })
    finish(t, appendRun(db, t.task_id, [
      {
        step: 'task_detected', decision: 'Carrier marked the package lost',
        reason: 'Tracking KSO4T81602 flipped to “lost” 6 days after the promised delivery date.',
        sources: [{ doc: 'Carrier tracking', section: 'KSO4T81602 · status “lost” · ETA was Nov 14', url: `${MOCK_WORLD}/carrier/track/KSO4T81602` }, { doc: 'Order confirmation email', section: 'KSO-77215 · shipping details · $239.00 · ZIP 94110', url: `${MOCK_WORLD}/inbox` }],
        rules_checked: [
          { rule: 'Carrier status lost/exception, or ETA + 3 days passed', passed: true, evidence: 'lost · ETA + 6 days' },
          { rule: 'No open claim for this order', passed: true, evidence: 'claim:KSO-77215 unused' },
        ],
        authorized_by: 'background_loop', model: 'Background loop (30 s poll)', cost_usd: 0, latency_ms: 140,
      },
      {
        step: 'policy_retrieved', decision: 'Retrieved Kestrel Outdoors policy',
        reason: 'No lost-package clause; the conservative reading is to claim through the returns portal named in §1.',
        sources: [policy('kestrel-outdoors', '§1 Returns — “Start a return at our returns portal with your order number and shipping ZIP code”')],
        rules_checked: [
          { rule: 'Verified policy exists in Senso', passed: true, evidence: 'Effective Jul 1, 2026' },
          { rule: 'Explicit lost-package clause', passed: false, evidence: 'Not found — used the portal channel from §1' },
        ],
        authorized_by: 'mandate.auto_missing_package_claim', model: 'Senso · context search', cost_usd: 0.002, latency_ms: 990,
      },
      {
        step: 'decision_made', decision: 'File a missing-package claim and ask for a reship',
        reason: 'The carrier confirmed the loss and you still want the tent, so a free reship beats a refund.',
        rejected_options: [
          { option: 'Wait 3 more days', reason: 'Carrier already declared it lost; waiting only delays recovery' },
          { option: 'Refund to card', reason: 'You’d have to re-buy; the tent is no longer on sale' },
        ],
        rules_checked: [
          { rule: 'mandate.auto_missing_package_claim', passed: true, evidence: 'true' },
          { rule: 'No new spending', passed: true, evidence: '$0.00 — reship at merchant’s cost' },
        ],
        authorized_by: 'mandate.auto_missing_package_claim', model: 'rules engine → claude-sonnet-5-5 (explanation)', cost_usd: 0.0031, latency_ms: 1750,
      },
      {
        step: 'claim_filed', decision: 'Claim CLM-KSO-30418 filed on Kestrel portal',
        reason: 'Order KSO-77215 + ZIP 94110 → “Item not received” → reship requested.',
        sources: [portal('kestrel-outdoors', 'Claim confirmation · CLM-KSO-30418')],
        rules_checked: [{ rule: 'Idempotency key unused', passed: true, evidence: 'claim:KSO-77215' }, { rule: 'Confirmation number shown', passed: true, evidence: 'CLM-KSO-30418' }],
        authorized_by: 'mandate.auto_missing_package_claim', model: 'Playwright (scripted)', cost_usd: 0, latency_ms: 5900,
      },
      {
        step: 'verified', decision: 'Verified: replacement shipped · new tracking KSO4T81877',
        reason: 'Confirmed from Kestrel’s shipment email and live carrier tracking.',
        sources: [{ doc: 'Kestrel Outdoors email', section: '“Your replacement is on the way”', url: `${MOCK_WORLD}/inbox` }, { doc: 'Carrier tracking', section: 'KSO4T81877 · in transit · ETA Sat', url: `${MOCK_WORLD}/carrier/track/KSO4T81877` }],
        rules_checked: [{ rule: 'Shipment email received', passed: true, evidence: 'orders@kestrel-outdoors.example' }, { rule: 'New tracking is active', passed: true, evidence: 'in_transit' }],
        authorized_by: 'verifier', model: 'Verifier (email + carrier)', cost_usd: 0, latency_ms: 820, verified: true,
      },
    ], start))
  }

  // 2. Minor price drop — 3h ago
  {
    const start = now - 3 * 60 * MIN
    const t = task({
      task_id: 'tsk_minor_dac', trigger_type: 'price_drop_minor', order_id: dac.order_id, status: 'done', decision: 'price_adjustment',
      title: 'Price adjusted', summary: 'USB-C DAC Cable dropped $49 → $43 → adjustment claimed automatically',
      amount_usd: 6, created_at: iso(start), outcome: '$6.00 refunded to your card',
    })
    finish(t, appendRun(db, t.task_id, [
      {
        step: 'task_detected', decision: 'Price dropped $49.00 → $43.00 (−12%)',
        reason: 'Background price check, 8 days after delivery.',
        sources: [priceFeed('northwind-audio', 'NWA-DAC-USBC', 'Current price $43.00 · regular (not clearance)'), email('e10', 'Paid $49.00 · NWA-10466')],
        rules_checked: [
          { rule: 'Minor drop (< 15% and < $20)', passed: true, evidence: '−12.2%, −$6.00 → auto' },
          { rule: 'Not clearance / open-box', passed: true, evidence: 'price_type: regular' },
        ],
        authorized_by: 'background_loop', model: 'Background loop (30 s poll)', cost_usd: 0, latency_ms: 160,
      },
      {
        step: 'policy_retrieved', decision: 'Retrieved Northwind Audio price-adjustment policy',
        reason: 'Northwind refunds the difference once per item within 14 days of delivery.',
        sources: [policy('northwind-audio', '§3 Price adjustments — “within 14 days of delivery, we will refund the difference once per item”'), policy('northwind-audio', '§2 Fees — “a 15% restocking fee is deducted” (opened, non-defective)')],
        rules_checked: [{ rule: 'Within adjustment window', passed: true, evidence: '8 of 14 days' }, { rule: 'First adjustment for this item', passed: true, evidence: 'none on file' }],
        authorized_by: 'mandate.price_drop.auto_adjust_minor', model: 'Senso · context search', cost_usd: 0.002, latency_ms: 1010,
      },
      {
        step: 'decision_made', decision: 'Claim a $6.00 price adjustment',
        reason: 'Allowed by policy and inside your mandate for minor drops.',
        rejected_options: [
          { option: 'Return and rebuy', reason: 'Opened non-defective items pay a 15% restocking fee ($7.35), so net would be −$1.35' },
          { option: 'Ignore', reason: 'Free money inside policy and mandate' },
        ],
        rules_checked: [{ rule: 'mandate.price_drop.auto_adjust_minor', passed: true, evidence: 'true' }, { rule: 'Policy allows adjustment', passed: true, evidence: 'price_adjustment_allowed: true' }],
        authorized_by: 'mandate.price_drop.auto_adjust_minor', model: 'rules engine → claude-sonnet-5-5 (explanation)', cost_usd: 0.0029, latency_ms: 1600,
      },
      {
        step: 'adjustment_filed', decision: 'Adjustment ADJ-NWA-5521 requested by support email',
        reason: 'The portal needs a ship ZIP and that field is missing from the order email; the agent fell back to support email instead of guessing.',
        sources: [{ doc: 'Sent email to support@northwind-audio.example', section: 'Price adjustment request · NWA-10466 · $6.00', url: `${MOCK_WORLD}/inbox` }],
        rules_checked: [
          { rule: 'Ship ZIP present in email', passed: false, evidence: 'Missing — portal lookup skipped, value not invented' },
          { rule: 'Fallback channel available', passed: true, evidence: 'Support email (§3 “or by contacting support”)' },
          { rule: 'Idempotency key unused', passed: true, evidence: 'adjust:NWA-10466' },
        ],
        authorized_by: 'mandate.price_drop.auto_adjust_minor', model: 'Mock mail API', cost_usd: 0, latency_ms: 450,
      },
      {
        step: 'refund_received', decision: 'Verified: $6.00 refund posted',
        reason: 'Matched a bank credit from Northwind Audio for the exact amount.',
        sources: [bank('Credit +$6.00 · Northwind Audio · Price adjustment ADJ-NWA-5521')],
        rules_checked: [{ rule: 'Refund amount matches', passed: true, evidence: '$6.00 = $6.00' }, { rule: 'Refund to original payment', passed: true, evidence: 'Card ending ••42' }],
        authorized_by: 'verifier', model: 'Verifier (bank)', cost_usd: 0, latency_ms: 610, verified: true,
      },
    ], start))
  }

  addMajorDrop(db, blender, now - 42 * MIN)
  addReturnWindow(db, jacket, now - 18 * MIN)
  return db
}

function addMajorDrop(db: MockDb, o: Order, start: number) {
  const id = db.counter === 0 ? 'tsk_major_blender' : `tsk_major_blender_${db.counter}`
  db.counter++
  const t: MockTask = {
    task_id: id, trigger_type: 'price_drop_major', order_id: o.order_id, status: 'awaiting_user', decision: null,
    title: 'Major price drop', summary: 'Vortex Blender dropped $119 → $89 (−25%). Pick how to claim it.',
    amount_usd: 30, created_at: iso(start), updated_at: iso(start),
  }
  db.tasks.push(t)
  appendRun(db, id, [
    {
      step: 'task_detected', decision: 'Price dropped $119.00 → $89.00 (−25%)',
      reason: 'Background price check, 6 days after delivery.',
      sources: [priceFeed('juniper-home', 'JNH-VORTEX-BL', 'Current price $89.00 · regular'), email('e03', 'Paid $119.00 · JNH-58213')],
      rules_checked: [
        { rule: 'Major drop (≥ 15% or ≥ $20)', passed: true, evidence: '−25.2%, −$30.00 → ask you' },
        { rule: 'Within adjustment window', passed: true, evidence: '6 of 14 days' },
        { rule: 'Within return window', passed: true, evidence: '6 of 30 days' },
      ],
      authorized_by: 'background_loop', model: 'Background loop (30 s poll)', cost_usd: 0, latency_ms: 150,
    },
    {
      step: 'policy_retrieved', decision: 'Retrieved Juniper Home price and return policy',
      reason: 'Price adjustments allowed within 14 days; non-defective returns pay $7.95 shipping.',
      sources: [
        policy('juniper-home', '§3 Price adjustments — “goes down in price … within 14 days of delivery, we will refund the difference”'),
        policy('juniper-home', '§2 Fees — “Non-defective returns: a $7.95 return shipping fee is deducted”'),
        policy('juniper-home', '§1 Returns — “Used small appliances may be returned only if defective”'),
      ],
      rules_checked: [{ rule: 'Verified policy exists in Senso', passed: true, evidence: 'Effective Aug 15, 2026' }],
      authorized_by: 'mandate.price_drop', model: 'Senso · context search', cost_usd: 0.002, latency_ms: 1020,
    },
    {
      step: 'options_computed', decision: 'Price match +$30.00 vs return & rebuy +$22.05',
      reason: 'Same discount either way, but rebuying loses $7.95 to return shipping and needs a drop-off.',
      rejected_options: [{ option: 'Adjust automatically', reason: 'Drop is major (−25%) — mandate says ask you first' }],
      rules_checked: [
        { rule: 'Price match allowed', passed: true, evidence: 'price_adjustment_allowed: true · 8 days left' },
        { rule: 'Return & rebuy net > 0', passed: true, evidence: '$30.00 − $7.95 = $22.05' },
        { rule: 'Return allowed for used blender', passed: false, evidence: 'Only if unused (§1) — flagged on the option' },
      ],
      authorized_by: 'mandate.price_drop.major_if', model: 'rules engine → claude-sonnet-5-5 (explanation)', cost_usd: 0.0035, latency_ms: 1700,
    },
    {
      step: 'user_notified', decision: 'Asked you to choose (one tap)',
      reason: 'Needs your preference: a no-hassle refund or a drop-off.',
      authorized_by: 'mandate.price_drop.major_if', model: null, cost_usd: 0, latency_ms: 90,
    },
  ], start)
  db.approvals.push({
    approval_id: id.replace('tsk_', 'apr_'), task_id: id,
    question: 'Your Vortex Blender dropped from $119 to $89. Want the difference back?',
    options: [
      { id: 'price_match', label: 'Price match', detail: 'Juniper refunds the difference. No hassle.', net_savings_usd: 30, action: 'execute' },
      { id: 'return_rebuy', label: 'Return & rebuy', detail: 'Needs a drop-off · $7.95 return shipping · only if unused', net_savings_usd: 22.05, action: 'execute' },
      { id: 'ignore', label: 'Ignore', detail: 'Keep paying $119', net_savings_usd: 0, action: 'dismiss' },
    ],
    recommended: 'price_match', choice: null, asked_at: iso(start),
    price_math: { paid_usd: 119, current_usd: 89, drop_pct: 25.2 },
  })
}

function addReturnWindow(db: MockDb, o: Order, start: number) {
  const id = db.counter <= 1 ? 'tsk_window_jacket' : `tsk_window_jacket_${db.counter}`
  db.counter++
  const t: MockTask = {
    task_id: id, trigger_type: 'return_window', order_id: o.order_id, status: 'awaiting_user', decision: null,
    title: 'Return window closing', summary: `Ridge Rain Jacket ($140) can be returned for 3 more days.`,
    amount_usd: 133.05, created_at: iso(start), updated_at: iso(start),
  }
  db.tasks.push(t)
  const by = o.return_by ? new Date(o.return_by).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : ''
  appendRun(db, id, [
    {
      step: 'task_detected', decision: `Return window closes ${by} (3 days left)`,
      reason: 'Delivered 42 days ago; Kestrel allows 45 days. Not returned or marked kept.',
      sources: [email('e05', 'Ridge Rain Jacket · $140.00 · KSO-77120'), policy('kestrel-outdoors', '§1 Returns — “within 45 days of delivery”')],
      rules_checked: [
        { rule: 'Window closes within 3 days', passed: true, evidence: `${by} · return_window_alert_days: 3` },
        { rule: 'Not already returned or kept', passed: true, evidence: 'order status: active' },
      ],
      authorized_by: 'background_loop', model: 'Background loop (30 s poll)', cost_usd: 0, latency_ms: 130,
    },
    {
      step: 'policy_retrieved', decision: 'Retrieved Kestrel Outdoors return policy',
      reason: 'Unworn items with tags; non-defective returns pay $6.95 shipping, no restocking fee.',
      sources: [
        policy('kestrel-outdoors', '§1 Returns — “Unworn, unwashed items with original tags may be returned within 45 days”'),
        policy('kestrel-outdoors', '§2 Fees — “Non-defective returns: a $6.95 return shipping fee is deducted”'),
      ],
      rules_checked: [{ rule: 'Verified policy exists in Senso', passed: true, evidence: 'Effective Jul 1, 2026' }],
      authorized_by: 'mandate.return_window_alert_days', model: 'Senso · context search', cost_usd: 0.002, latency_ms: 980,
    },
    {
      step: 'user_notified', decision: 'Asked you: return, keep, or remind tomorrow',
      reason: 'Only you know whether you still want it — no recommendation forced.',
      authorized_by: 'mandate.return_window_alert_days', model: null, cost_usd: 0, latency_ms: 80,
    },
  ], start)
  db.approvals.push({
    approval_id: id.replace('tsk_', 'apr_'), task_id: id,
    question: `Your Kestrel Outdoors Ridge Rain Jacket can be returned until ${by}. Return it?`,
    options: [
      { id: 'return', label: 'Return it', detail: 'Refund $133.05 ($6.95 shipping) · must be unworn with tags', net_savings_usd: 133.05, action: 'execute' },
      { id: 'keep', label: 'Keep', detail: 'Stop alerts for this item', action: 'dismiss' },
      { id: 'remind', label: 'Remind me tomorrow', detail: 'One more nudge before it closes', action: 'snooze' },
    ],
    recommended: null, choice: null, asked_at: iso(start),
    deadline: { return_by: o.return_by ?? iso(Date.now() + 3 * DAY), days_left: 3, price_usd: 140 },
  })
}

// ---------- execution scripts (what runs after a tap / upload) ----------
interface ScriptStep {
  wait: number
  status?: TaskStatus
  draft?: Draft
}

function approvalScript(task: Task, approval: Approval, optionId: string, inquiry: string): { steps: ScriptStep[]; final: Partial<Task> } {
  const opt = approval.options.find((o) => o.id === optionId)!
  const auth = `approval:${approval.approval_id}`
  const approved: Draft = {
    step: 'user_approved',
    decision: `You chose: ${opt.label}${opt.net_savings_usd ? ` (+$${opt.net_savings_usd.toFixed(2)})` : ''}`,
    reason: `One tap, verified by Persona (inquiry ${inquiry}).`,
    rules_checked: [
      { rule: 'Persona verification passed', passed: true, evidence: `${inquiry} · selfie + device match` },
      { rule: 'Option allowed by policy', passed: true, evidence: opt.detail },
    ],
    authorized_by: auth, model: 'Persona · inquiry', cost_usd: 0, latency_ms: 1500,
  }

  if (task.trigger_type === 'price_drop_major' && optionId === 'price_match') {
    return {
      final: { status: 'done', decision: 'price_adjustment', title: 'Price matched', amount_usd: 30, summary: 'Vortex Blender dropped $119 → $89 → you chose price match', outcome: '$30.00 refunded to your card' },
      steps: [
        { wait: 200, status: 'executing', draft: approved },
        { wait: 1300, draft: { step: 'price_rechecked', decision: 'Price still $89.00 — safe to proceed', reason: 'Re-checked right before acting in case the sale ended while you decided.', sources: [priceFeed('juniper-home', 'JNH-VORTEX-BL', 'Current price $89.00')], rules_checked: [{ rule: 'Price unchanged since notification', passed: true, evidence: '$89.00 = $89.00' }], authorized_by: auth, model: 'HTTP check', cost_usd: 0, latency_ms: 210 } },
        { wait: 1700, draft: { step: 'adjustment_filed', decision: 'Adjustment ADJ-JNH-7731 filed on Juniper portal', reason: 'Looked up JNH-58213 with ZIP 94110 and requested the $30.00 difference.', sources: [portal('juniper-home', 'Confirmation · ADJ-JNH-7731 · $30.00')], rules_checked: [{ rule: 'Idempotency key unused', passed: true, evidence: 'adjust:JNH-58213' }, { rule: 'One adjustment per item', passed: true, evidence: 'first request' }, { rule: 'Confirmation number shown', passed: true, evidence: 'ADJ-JNH-7731' }], authorized_by: auth, model: 'Playwright (scripted)', cost_usd: 0, latency_ms: 5200 } },
        { wait: 400, status: 'verifying' },
        { wait: 1600, draft: { step: 'refund_received', decision: 'Verified: $30.00 refund posted', reason: 'Matched a bank credit, not just the portal’s success message.', sources: [bank('Credit +$30.00 · Juniper Home · ADJ-JNH-7731'), { doc: 'Juniper Home email', section: '“Your price adjustment is approved”', url: `${MOCK_WORLD}/inbox` }], rules_checked: [{ rule: 'Refund amount matches', passed: true, evidence: '$30.00 = $30.00' }, { rule: 'Refund to original payment', passed: true, evidence: 'Card ending ••42' }], authorized_by: 'verifier', model: 'Verifier (bank + email)', cost_usd: 0, latency_ms: 640, verified: true } },
      ],
    }
  }
  if (task.trigger_type === 'price_drop_major' && optionId === 'return_rebuy') {
    return {
      final: { status: 'done', decision: 'return_and_rebuy', title: 'Rebought at the lower price', amount_usd: 22.05, summary: 'Vortex Blender dropped $119 → $89 → bought new at $89, returned the original', outcome: 'Net +$22.05 · new blender arriving Tue' },
      steps: [
        { wait: 200, status: 'executing', draft: approved },
        { wait: 1200, draft: { step: 'price_rechecked', decision: 'Price still $89.00 — safe to proceed', reason: 'Re-checked before buying.', sources: [priceFeed('juniper-home', 'JNH-VORTEX-BL', 'Current price $89.00')], rules_checked: [{ rule: 'Price unchanged since notification', passed: true, evidence: '$89.00' }], authorized_by: auth, model: 'HTTP check', cost_usd: 0, latency_ms: 200 } },
        { wait: 1600, draft: { step: 'order_placed', decision: 'Bought a new Vortex Blender · JNH-58644 · $89.00', reason: 'Locked in the lower price first, before returning the original.', sources: [{ doc: 'Juniper Home checkout', section: 'Order confirmation JNH-58644', url: `${MOCK_WORLD}/s/juniper-home/checkout` }], rules_checked: [{ rule: 'Total ≤ $200 approval cap', passed: true, evidence: '$89.00' }, { rule: 'Card never exposed to agent', passed: true, evidence: 'Tokenized checkout' }], authorized_by: auth, model: 'Playwright (scripted)', cost_usd: 0, latency_ms: 4600 } },
        { wait: 1600, draft: { step: 'return_filed', decision: 'Return RMA-JNH-4410 filed for the original · label saved', reason: 'Reason “Price dropped — rebuying”; $7.95 return shipping deducted per §2. Drop-off reminder added.', sources: [portal('juniper-home', 'Confirmation · RMA-JNH-4410'), policy('juniper-home', '§2 Fees — “$7.95 return shipping fee”')], rules_checked: [{ rule: 'Idempotency key unused', passed: true, evidence: 'return:JNH-58213' }, { rule: 'Within return window', passed: true, evidence: '6 of 30 days' }], authorized_by: auth, model: 'Playwright (scripted)', cost_usd: 0, latency_ms: 6100 } },
        { wait: 300, status: 'awaiting_refund' },
        { wait: 1700, draft: { step: 'refund_received', decision: 'Verified: $111.05 refund posted', reason: '$119.00 − $7.95 shipping, matched in the bank feed.', sources: [bank('Credit +$111.05 · Juniper Home · RMA-JNH-4410')], rules_checked: [{ rule: 'Refund amount matches', passed: true, evidence: '$111.05' }], authorized_by: 'verifier', model: 'Verifier (bank)', cost_usd: 0, latency_ms: 600, verified: true } },
      ],
    }
  }
  if (task.trigger_type === 'return_window' && optionId === 'return') {
    return {
      final: { status: 'done', decision: 'return', title: 'Returned before the deadline', amount_usd: 133.05, summary: 'Ridge Rain Jacket returned 3 days before the window closed', outcome: '$133.05 refunded to your card' },
      steps: [
        { wait: 200, status: 'executing', draft: approved },
        { wait: 1800, draft: { step: 'return_filed', decision: 'Return RMA-KSO-6127 filed · label saved', reason: 'Reason inferred as “No longer needed” (portal accepted it); refund to original payment.', sources: [portal('kestrel-outdoors', 'Confirmation · RMA-KSO-6127 · refund $133.05'), policy('kestrel-outdoors', '§2 Fees — “$6.95 return shipping fee is deducted”')], rules_checked: [{ rule: 'Within return window', passed: true, evidence: '42 of 45 days' }, { rule: 'Idempotency key unused', passed: true, evidence: 'return:KSO-77120' }, { rule: 'Reason needed from you', passed: true, evidence: 'No — default “No longer needed”' }], authorized_by: auth, model: 'Playwright (scripted)', cost_usd: 0, latency_ms: 5800 } },
        { wait: 1100, draft: { step: 'reminder_added', decision: 'Drop-off reminder: tomorrow 10:00 AM', reason: 'Calendar event (.ics) a day before the deadline, nearest drop-off 0.4 mi.', sources: [{ doc: 'Calendar event', section: 'Drop off Kestrel return RMA-KSO-6127', url: '' }], authorized_by: auth, model: 'Calendar (.ics)', cost_usd: 0, latency_ms: 120 } },
        { wait: 300, status: 'awaiting_refund' },
        { wait: 1800, draft: { step: 'refund_received', decision: 'Verified: $133.05 refund posted', reason: '$140.00 − $6.95 shipping, matched in the bank feed.', sources: [bank('Credit +$133.05 · Kestrel Outdoors · RMA-KSO-6127')], rules_checked: [{ rule: 'Refund amount matches', passed: true, evidence: '$133.05' }, { rule: 'Refund to original payment', passed: true, evidence: 'Card ending ••42' }], authorized_by: 'verifier', model: 'Verifier (bank)', cost_usd: 0, latency_ms: 620, verified: true } },
      ],
    }
  }
  // dismiss / snooze
  const label = optionId === 'remind' ? 'Remind me tomorrow' : opt.label
  return {
    final: optionId === 'remind' ? {} : { status: 'done', decision: optionId === 'keep' ? 'kept' : 'ignored' },
    steps: [{
      wait: 50,
      draft: {
        step: 'user_approved', decision: `You chose: ${label}`,
        reason: optionId === 'remind' ? 'Will ask once more tomorrow, before the window closes.' : 'No action taken. Logged so the agent won’t ask again.',
        rules_checked: [{ rule: 'Money moved', passed: true, evidence: 'None — no verification needed' }],
        authorized_by: 'user', model: null, cost_usd: 0, latency_ms: 0,
      },
    }],
  }
}

const PHOTO_STEP_WAIT = [1300, 1500, 1600, 1400, 2200, 1300, 1700, 1500]

// ---------- persistence ----------
const KEY = 'snapback.mock.v3'
let db: MockDb = load()

function load(): MockDb {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as MockDb
      if (parsed.version === 3) return parsed
    }
  } catch {
    /* storage unavailable */
  }
  return seed()
}
function save() {
  try {
    localStorage.setItem(KEY, JSON.stringify(db))
  } catch {
    /* ignore */
  }
  window.dispatchEvent(new Event('snapback:changed')) // same as api.CHANGED_EVENT (avoids a circular import)
}

function runScript(taskId: string, steps: ScriptStep[], final: Partial<Task>) {
  let delay = 0
  steps.forEach((s) => {
    delay += s.wait
    setTimeout(() => {
      const t = db.tasks.find((x) => x.task_id === taskId)
      if (!t) return
      if (s.status) t.status = s.status
      if (s.draft) append(db, taskId, s.draft, Date.now())
      t.updated_at = iso(Date.now())
      save()
    }, delay)
  })
  setTimeout(() => {
    const t = db.tasks.find((x) => x.task_id === taskId)
    if (!t) return
    Object.assign(t, final, { updated_at: iso(Date.now()) })
    save()
  }, delay + 250)
}

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x))
const withOrder = (t: MockTask): Task => {
  const { hidden, ...rest } = t
  void hidden
  return { ...rest, order: db.orders.find((o) => o.order_id === t.order_id) }
}

// ---------- mock API (same signatures as live) ----------
export const mockApi = {
  async getFeed(): Promise<Task[]> {
    return clone(db.tasks.filter((t) => !t.hidden).map(withOrder)).sort((a, b) => b.created_at.localeCompare(a.created_at))
  },
  async getTask(id: string): Promise<Task | null> {
    const t = db.tasks.find((x) => x.task_id === id)
    return t ? clone(withOrder(t)) : null
  },
  async getAudit(taskId: string): Promise<AuditEntry[]> {
    return clone(db.audit.filter((e) => e.task_id === taskId))
  },
  async getApprovals(): Promise<Approval[]> {
    return clone(db.approvals.filter((a) => !a.choice))
  },
  async getApprovalForTask(taskId: string): Promise<Approval | null> {
    const a = db.approvals.find((x) => x.task_id === taskId)
    return a ? clone(a) : null
  },
  /** Mock re-derives every hash in the global chain, so any tampered field is caught. */
  async verifyChain(taskId: string) {
    const all = verifyEntries(db.audit, true)
    const mine = db.audit.filter((e) => e.task_id === taskId)
    return { ...all, detail: all.ok ? `${mine.length} entries · all ${db.audit.length} chain hashes re-derived` : all.detail }
  },
  async answerApproval(approvalId: string, optionId: string, personaInquiryId: string) {
    const a = db.approvals.find((x) => x.approval_id === approvalId)
    if (!a) throw new Error('approval not found')
    if (a.choice) return { task_id: a.task_id, status: 'already_answered' } // idempotent
    const t = db.tasks.find((x) => x.task_id === a.task_id)!
    a.choice = optionId
    a.persona_verified = a.options.find((x) => x.id === optionId)?.action === 'execute'
    const { steps, final } = approvalScript(t, a, optionId, personaInquiryId)
    if (final.decision === 'kept' || final.decision === 'ignored') t.hidden = true
    save()
    runScript(t.task_id, steps, final)
    return { task_id: t.task_id, status: 'accepted' }
  },
  async uploadPhoto(file: File | null): Promise<string> {
    const o = db.orders.find((x) => x.order_id === 'NWA-10421')!
    // The live run replaces the seeded copy of this flow in the feed (audit entries stay in the chain).
    db.tasks.forEach((t) => {
      if (t.trigger_type === 'photo' && t.order_id === o.order_id) t.hidden = true
    })
    const id = `tsk_photo_${Date.now().toString(36)}`
    const now = Date.now()
    db.tasks.push({
      task_id: id, trigger_type: 'photo', order_id: o.order_id, status: 'executing', decision: null,
      title: 'Return + replacement', summary: 'Photo of cracked headphones → return filed, better-rated replacement ordered',
      amount_usd: 179, created_at: iso(now), updated_at: iso(now),
    })
    save()
    const name = file?.name ?? 'demo_broken_headphones.png'
    const drafts = headphoneDrafts(o, '/demo/demo_broken_headphones.png', `${name} · uploaded just now`)
    const steps: ScriptStep[] = drafts.map((d, i) => ({ wait: PHOTO_STEP_WAIT[i], draft: d, status: d.step === 'verified' ? 'verifying' : undefined }))
    runScript(id, steps, { status: 'done', decision: 'return_and_replace', outcome: '$179.00 refunded · Arc ANC 2 arriving Monday' })
    return id
  },
  async demoReset() {
    db = seed()
    save()
  },
  async demoTrigger(kind: DemoTrigger) {
    const now = Date.now()
    if (kind === 'major_price_drop') {
      db.approvals.filter((a) => !a.choice && a.task_id.startsWith('tsk_major')).forEach((a) => {
        a.choice = 'superseded'
        db.tasks.filter((t) => t.task_id === a.task_id).forEach((t) => (t.hidden = true))
      })
      addMajorDrop(db, db.orders.find((o) => o.order_id === 'JNH-58213')!, now)
    } else if (kind === 'return_window') {
      db.approvals.filter((a) => !a.choice && a.task_id.startsWith('tsk_window')).forEach((a) => {
        a.choice = 'superseded'
        db.tasks.filter((t) => t.task_id === a.task_id).forEach((t) => (t.hidden = true))
      })
      addReturnWindow(db, db.orders.find((o) => o.order_id === 'KSO-77120')!, now)
    } else if (kind === 'tamper') {
      // Edit a sealed entry without re-hashing: "any edit breaks it".
      const target = db.audit.find((e) => e.task_id === 'tsk_photo_headphones' && e.step === 'order_placed') ?? db.audit[Math.floor(db.audit.length / 2)]
      target.decision = target.decision.replace('$199.00', '$1,999.00')
      target.cost_usd = 0.5
    }
    save()
  },
}
