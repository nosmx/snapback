// The ONLY data-access module. Flip USE_MOCK to switch between the in-browser mock world and the FastAPI backend.
// (Override without editing: VITE_USE_MOCK=false npm run dev)
import type { Approval, AuditEntry, ChainCheck, DemoTrigger, Mandate, Order, Task } from './types'
import { mockApi } from './mock'
import { MOCK_MANDATE } from './mock-mandate'
import { verifyEntries } from './chain'

export const USE_MOCK: boolean = (import.meta.env.VITE_USE_MOCK ?? 'true') !== 'false'

// Empty base = same origin; vite.config.ts proxies /api → http://localhost:8000.
const BASE: string = import.meta.env.VITE_API_URL ?? ''

export const CHANGED_EVENT = 'snapback:changed'
export const notifyChange = () => window.dispatchEvent(new Event(CHANGED_EVENT))

// ---------------- live client ----------------
async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(BASE + path, init)
  if (!r.ok) throw new Error(`${init?.method ?? 'GET'} ${path} → ${r.status}`)
  return r.json() as Promise<T>
}
const postJson = <T,>(path: string, body: unknown) =>
  http<T>(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

type Raw = Record<string, unknown>
const parse = (v: unknown): unknown => {
  if (typeof v !== 'string') return v
  try {
    return JSON.parse(v)
  } catch {
    return v
  }
}
const num = (v: unknown): number | null => (v === null || v === undefined || v === '' ? null : Number(v))
const arr = <T,>(v: unknown): T[] => {
  const p = parse(v)
  return Array.isArray(p) ? (p as T[]) : []
}
const str = (v: unknown, d = ''): string => (v === null || v === undefined ? d : String(v))

/** Backend timestamps are UTC without a zone ("2026-11-20 20:00:40.024017"); DATE columns are "2026-12-01". */
function ts(v: unknown): string {
  const s = str(v)
  if (!s) return s
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return `${s}T12:00:00` // date only: noon local, so it never shifts a day
  let t = s.replace(' ', 'T').replace(/(\.\d{3})\d+/, '$1')
  if (!/[zZ]|[+-]\d{2}:?\d{2}$/.test(t)) t += 'Z'
  return t
}
const tsOrNull = (v: unknown) => (v ? ts(v) : null)

function normOrder(r: Raw | undefined | null): Order | undefined {
  if (!r) return undefined
  return {
    order_id: str(r.order_id),
    store: str(r.store),
    item_name: str(r.item_name),
    sku: r.sku ? str(r.sku) : undefined,
    price: num(r.price) ?? 0,
    ordered_at: ts(r.ordered_at),
    delivered_at: tsOrNull(r.delivered_at),
    return_by: tsOrNull(r.return_by),
    status: str(r.status, 'active'),
    image_url: str(r.image_url),
  }
}

function normTask(r: Raw): Task {
  const d = (parse(r.details) as Raw | null) ?? {}
  const pick = (k: string) => r[k] ?? d[k]
  return {
    task_id: str(r.task_id),
    trigger_type: str(r.trigger_type) as Task['trigger_type'],
    order_id: str(r.order_id),
    status: str(r.status, 'detected') as Task['status'],
    decision: (pick('decision') as string) ?? null,
    title: str(pick('title'), str(r.trigger_type).replace(/_/g, ' ')),
    summary: str(pick('summary')),
    amount_usd: num(pick('amount_usd')),
    created_at: ts(r.created_at),
    updated_at: ts(r.updated_at ?? r.created_at),
    outcome: pick('outcome') ? str(pick('outcome')) : undefined,
    order: normOrder((r.order as Raw) ?? (d.order as Raw)),
  }
}

function normAudit(r: Raw): AuditEntry {
  const inputs = (parse(r.inputs) as Raw | null) ?? {}
  return {
    entry_id: Number(r.entry_id),
    seq: r.seq === undefined || r.seq === null ? undefined : Number(r.seq),
    task_id: str(r.task_id),
    step: str(r.step),
    decision: str(r.decision),
    reason: str(r.reason ?? inputs.reason),
    sources: arr<Raw>(r.sources).map((s) => ({ doc: str(s.doc), section: str(s.section), url: str(s.url), retrieved_at: ts(s.retrieved_at ?? r.created_at) })),
    rejected_options: arr(r.rejected_options),
    rules_checked: arr<Raw>(r.rules_checked).map((x) => ({ rule: str(x.rule), passed: Boolean(x.passed), evidence: str(x.evidence) })),
    authorized_by: r.authorized_by ? str(r.authorized_by) : null,
    model: r.model ? str(r.model) : null,
    cost_usd: num(r.cost_usd),
    latency_ms: num(r.latency_ms),
    verified: r.verified === null || r.verified === undefined ? null : Boolean(Number(r.verified)),
    created_at: ts(r.created_at),
    prev_hash: str(r.prev_hash),
    entry_hash: str(r.entry_hash),
  }
}

function normApproval(r: Raw): Approval {
  return {
    ...(r as unknown as Approval),
    options: arr(r.options),
    asked_at: tsOrNull(r.asked_at) ?? undefined,
    price_math: parse(r.price_math) as Approval['price_math'],
    deadline: (() => {
      const d = parse(r.deadline) as Approval['deadline']
      return d ? { ...d, return_by: ts(d.return_by) } : undefined
    })(),
    persona_verified: r.persona_verified === undefined ? Boolean(r.persona_inquiry_id) : Boolean(r.persona_verified),
  }
}

const liveApi = {
  async getFeed(): Promise<Task[]> {
    return (await http<Raw[]>('/api/feed')).map(normTask)
  },
  async getTask(id: string): Promise<Task | null> {
    try {
      return normTask(await http<Raw>(`/api/tasks/${encodeURIComponent(id)}`))
    } catch {
      return null
    }
  },
  async getAudit(taskId: string): Promise<AuditEntry[]> {
    const rows = (await http<Raw[]>(`/api/audit?task_id=${encodeURIComponent(taskId)}`)).map(normAudit)
    return rows.sort((a, b) => (a.seq ?? a.entry_id) - (b.seq ?? b.entry_id))
  },
  async getApprovals(): Promise<Approval[]> {
    return (await http<Raw[]>('/api/approvals?pending=true')).map(normApproval)
  },
  async getApprovalForTask(taskId: string): Promise<Approval | null> {
    const rows = (await http<Raw[]>(`/api/approvals?task_id=${encodeURIComponent(taskId)}`)).map(normApproval)
    return rows[0] ?? null
  },
  async answerApproval(approvalId: string, optionId: string) {
    return postJson<{ task_id: string; status: string; persona_inquiry_id?: string }>(
      `/api/approvals/${encodeURIComponent(approvalId)}/answer`,
      { option_id: optionId },
    )
  },
  async uploadPhoto(file: File): Promise<string> {
    const fd = new FormData()
    fd.append('file', file)
    const r = await http<{ task_id: string }>('/api/photo', { method: 'POST', body: fd })
    return r.task_id
  },
  async demoReset() {
    await postJson('/api/demo/reset', {})
  },
  async demoTrigger(kind: DemoTrigger) {
    await postJson('/api/demo/trigger', { kind })
  },
}

// ---------------- public API ----------------
export async function getFeed(): Promise<Task[]> {
  return USE_MOCK ? mockApi.getFeed() : liveApi.getFeed()
}
export async function getTask(id: string): Promise<Task | null> {
  return USE_MOCK ? mockApi.getTask(id) : liveApi.getTask(id)
}
export async function getAudit(taskId: string): Promise<AuditEntry[]> {
  return USE_MOCK ? mockApi.getAudit(taskId) : liveApi.getAudit(taskId)
}
export async function getApprovals(): Promise<Approval[]> {
  return USE_MOCK ? mockApi.getApprovals() : liveApi.getApprovals()
}
export async function getApprovalForTask(taskId: string): Promise<Approval | null> {
  return USE_MOCK ? mockApi.getApprovalForTask(taskId) : liveApi.getApprovalForTask(taskId)
}

/**
 * Chain check for one task's entries.
 * Mock: re-derives every hash in the global chain. Live: checks prev_hash links between entries
 * that are adjacent in the global chain (seq n → n+1) AND asks the backend to re-hash the whole chain.
 */
export async function verifyChain(taskId: string, entries: AuditEntry[]): Promise<ChainCheck> {
  if (USE_MOCK) return mockApi.verifyChain(taskId)
  const local = verifyEntries(entries, false)
  if (!local.ok) return local
  try {
    // backend/audit.py → {ok, entries, broken_at_seq, head}
    const server = await http<{ ok: boolean; entries?: number; broken_at_seq?: number | null }>('/api/audit/verify')
    if (!server.ok) {
      const hit = entries.find((e) => e.seq === Number(server.broken_at_seq))
      return {
        ok: false,
        checked_links: local.checked_links,
        broken_at: hit?.entry_id,
        detail: hit
          ? `Entry #${hit.seq} (${hit.step}) was modified after it was sealed`
          : `Global chain broken at seq ${server.broken_at_seq} (another task’s entry)`,
      }
    }
    return { ok: true, checked_links: local.checked_links, detail: `${entries.length} entries · server re-hashed ${server.entries ?? 'all'} chain entries` }
  } catch {
    return { ...local, detail: `${local.detail} · server verify unreachable` }
  }
}

/** One tap → Persona verification → execution. Resolves once the choice is recorded (execution continues async). */
export async function answerApproval(approvalId: string, optionId: string) {
  const res = USE_MOCK
    ? await mockApi.answerApproval(approvalId, optionId, mockInquiryId())
    : await liveApi.answerApproval(approvalId, optionId)
  notifyChange()
  return res as { task_id: string; status: string; persona_inquiry_id?: string }
}

export async function uploadPhoto(file: File | null): Promise<string> {
  if (USE_MOCK) {
    const id = await mockApi.uploadPhoto(file)
    notifyChange()
    return id
  }
  if (!file) throw new Error('No photo selected')
  return liveApi.uploadPhoto(file)
}

export async function demoReset() {
  await (USE_MOCK ? mockApi.demoReset() : liveApi.demoReset())
  notifyChange()
}
export async function demoTrigger(kind: DemoTrigger) {
  await (USE_MOCK ? mockApi.demoTrigger(kind) : liveApi.demoTrigger(kind))
  notifyChange()
}

/** Standing rules (read-only in the UI). Live: GET /api/mandate → {user_id, rules, verified_by, persona_inquiry_id, verified_at}. */
export async function getMandate(): Promise<Mandate> {
  if (USE_MOCK) return MOCK_MANDATE
  const r = await http<Raw>('/api/mandate')
  return {
    user_id: str(r.user_id),
    verified_by: r.verified_by ? str(r.verified_by) : null,
    persona_inquiry_id: r.persona_inquiry_id ? str(r.persona_inquiry_id) : null,
    verified_at: tsOrNull(r.verified_at),
    rules: parse(r.rules) as Mandate['rules'],
  }
}

let lastInquiry = ''
function mockInquiryId() {
  lastInquiry = 'inq_' + Math.random().toString(36).slice(2, 10) + Math.random().toString(36).slice(2, 8)
  return lastInquiry
}
export const getLastMockInquiry = () => lastInquiry
