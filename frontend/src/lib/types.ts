// Shapes mirror generalcontext.md §8. Optional fields are UI conveniences the backend may embed.

export type TriggerType =
  | 'photo'
  | 'chat'
  | 'price_drop_minor'
  | 'price_drop_major'
  | 'return_window'
  | 'missing_package'
  | 'duplicate'

export type TaskStatus =
  | 'detected'
  | 'awaiting_user'
  | 'planned'
  | 'executing'
  | 'verifying'
  | 'awaiting_refund'
  | 'done'
  | 'expired'
  | 'failed'

export type OrderStatus = 'active' | 'returned' | 'kept' | 'claimed'

export interface Order {
  order_id: string
  store: string // store slug, e.g. "northwind-audio"
  item_name: string
  sku?: string
  price: number
  ordered_at: string
  delivered_at: string | null
  return_by: string | null
  status: OrderStatus | string
  image_url: string
}

export interface Task {
  task_id: string
  trigger_type: TriggerType
  order_id: string
  status: TaskStatus
  decision: string | null
  title: string
  summary: string
  amount_usd: number | null // money recovered (refund / adjustment / covered value)
  created_at: string
  updated_at: string
  order?: Order // embedded by GET /api/feed and GET /api/tasks/{id}
  outcome?: string // one-line result, e.g. "Refund $179 posted · replacement arriving Thu"
}

export interface ApprovalOption {
  id: string
  label: string
  detail: string
  net_savings_usd?: number | null
  action?: 'execute' | 'dismiss' | 'snooze' // dismiss/snooze close the card without running anything
}

export interface Approval {
  approval_id: string
  task_id: string
  question: string
  options: ApprovalOption[]
  recommended: string | null
  choice?: string | null
  persona_verified?: boolean
  asked_at?: string
  // Pre-computed facts for the card. Either price math or a deadline.
  price_math?: { paid_usd: number; current_usd: number; drop_pct: number }
  deadline?: { return_by: string; days_left: number; price_usd: number }
}

export interface Source {
  doc: string
  section: string
  url: string
  retrieved_at: string
}

export interface RuleCheck {
  rule: string
  passed: boolean
  evidence: string
}

export interface RejectedOption {
  option: string
  reason: string
}

export interface AuditEntry {
  entry_id: number
  seq?: number // backend global chain order; prev_hash links seq-1 → seq
  task_id: string
  step: string
  decision: string
  reason: string
  sources: Source[]
  rejected_options: RejectedOption[]
  rules_checked: RuleCheck[]
  authorized_by: string | null
  model: string | null
  cost_usd: number | null
  latency_ms: number | null
  verified: boolean | null
  created_at: string
  prev_hash: string
  entry_hash: string
}

export interface ChainCheck {
  ok: boolean
  checked_links: number
  broken_at?: number // entry_id where the chain broke
  detail: string
}

export interface TaskBundle {
  task: Task
  audit: AuditEntry[]
  approval: Approval | null
}

export interface MandateRules {
  auto_return_defective: boolean
  auto_missing_package_claim: boolean
  price_drop: { auto_adjust_minor: boolean; major_if: { min_percent: number; min_usd: number } }
  return_window_alert_days: number
  replacement: { enabled: boolean; strategy: string; poor_review_threshold?: number; max_extra_spend_usd: number }
  require_approval_over_usd: number
  refund_method: string
  allowed_stores: string[]
}

export interface Mandate {
  user_id: string
  verified_by: string | null
  persona_inquiry_id?: string | null
  verified_at?: string | null
  rules: MandateRules
}

export type DemoTrigger ='major_price_drop' | 'return_window' | 'tamper'

export interface ProgressStep {
  key: string
  label: string
  result?: string
  state: 'pending' | 'active' | 'done' | 'failed'
}
