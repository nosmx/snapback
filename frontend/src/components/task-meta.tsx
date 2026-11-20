import {
  BadgeDollarSign, BellRing, BookOpen, Calculator, CalendarClock, CalendarPlus, Camera, Copy, FileCheck2, Fingerprint,
  Link2, ListOrdered, MessageCircle, PackageX, Radar, Receipt, RefreshCw, Scale, ScanSearch, ShieldCheck, ShoppingCart,
  TrendingDown, Undo2, type LucideIcon,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Approval, Task, TaskStatus, TriggerType } from '@/lib/types'

export const TRIGGER: Record<TriggerType, { label: string; icon: LucideIcon }> = {
  photo: { label: 'Photo', icon: Camera },
  chat: { label: 'Chat', icon: MessageCircle },
  price_drop_minor: { label: 'Price drop', icon: TrendingDown },
  price_drop_major: { label: 'Price drop', icon: TrendingDown },
  return_window: { label: 'Return window', icon: CalendarClock },
  missing_package: { label: 'Missing package', icon: PackageX },
  duplicate: { label: 'Duplicate order', icon: Copy },
}

export const isActive = (s: TaskStatus) => ['detected', 'planned', 'executing', 'verifying', 'awaiting_refund'].includes(s)

export const STATUS_TEXT: Record<TaskStatus, string> = {
  detected: 'Starting',
  awaiting_user: 'Needs you',
  planned: 'Planned',
  executing: 'In progress',
  verifying: 'Confirming',
  awaiting_refund: 'Waiting for refund',
  done: 'Done',
  expired: 'Expired',
  failed: 'Failed',
}

/** Activity segments. */
export function categoryOf(t: Task): 'returns' | 'price' | 'claims' {
  if (t.trigger_type.startsWith('price_drop')) return 'price'
  const d = t.decision ?? ''
  if (t.trigger_type === 'missing_package' || /claim|warranty/.test(d)) return 'claims'
  return 'returns'
}

const STEPS: Record<string, { label: string; icon: LucideIcon }> = {
  task_detected: { label: 'Detected', icon: Radar },
  intent_classified: { label: 'Understood your message', icon: MessageCircle },
  photo_identified: { label: 'Identified the item', icon: ScanSearch },
  order_matched: { label: 'Found your order', icon: Link2 },
  policy_retrieved: { label: 'Checked store policy', icon: BookOpen },
  options_computed: { label: 'Compared options', icon: Calculator },
  decision_made: { label: 'Decided', icon: Scale },
  user_notified: { label: 'Asked you', icon: BellRing },
  user_approved: { label: 'You approved', icon: Fingerprint },
  price_rechecked: { label: 'Re-checked the price', icon: RefreshCw },
  return_filed: { label: 'Filed the return', icon: Undo2 },
  claim_filed: { label: 'Filed the claim', icon: FileCheck2 },
  adjustment_filed: { label: 'Requested the refund', icon: Receipt },
  replacement_ranked: { label: 'Chose a replacement', icon: ListOrdered },
  order_placed: { label: 'Placed the order', icon: ShoppingCart },
  reminder_added: { label: 'Added a reminder', icon: CalendarPlus },
  verified: { label: 'Confirmed', icon: ShieldCheck },
  email_ingested: { label: 'Read an order email', icon: FileCheck2 },
  mandate_verified: { label: 'Rules verified', icon: Fingerprint },
  mandate_updated: { label: 'Rules updated', icon: Fingerprint },
  refund_received: { label: 'Refund received', icon: BadgeDollarSign },
}

export function stepMeta(step: string): { label: string; icon: LucideIcon } {
  if (STEPS[step]) return STEPS[step]
  return { label: step.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase()), icon: Radar }
}

export function authorizedLabel(a: string | null): { title: string; detail?: string; kind: 'approval' | 'mandate' | 'system' } {
  if (!a) return { title: 'System', kind: 'system' }
  if (a.startsWith('approval')) return { title: 'You, verified with Persona', detail: a.replace(/^approval[.:]?/, ''), kind: 'approval' }
  if (a.startsWith('mandate')) return { title: 'Your rules', detail: a.replace(/^mandate[.:]?/, ''), kind: 'mandate' }
  if (a === 'user') return { title: 'You (no money moved)', kind: 'system' }
  if (a === 'verifier') return { title: 'Independent check', detail: 'outside evidence, not the agent’s own claim', kind: 'system' }
  if (a === 'background_loop') return { title: 'Background monitor', detail: 'detection only', kind: 'system' }
  return { title: a, kind: 'system' }
}

/** Last word of the product name: "Vortex Blender" → "Blender". */
export const shortName = (name?: string) => (name ? name.split(' ').slice(-1)[0] : 'Item')

export function Thumb({ src, className }: { src?: string | null; className?: string }) {
  return src ? (
    <img src={src} alt="" loading="lazy" className={cn('size-12 shrink-0 rounded-[10px] bg-white object-cover ring-1 ring-black/5', className)} />
  ) : (
    <div className={cn('bg-fill size-12 shrink-0 rounded-[10px]', className)} />
  )
}

/** One-line summary of a pending decision, e.g. "Blender price dropped $30". */
export function decisionLine(a: Approval, t: Task) {
  const n = shortName(t.order?.item_name)
  if (a.price_math) return `${n} price dropped $${Math.round(a.price_math.paid_usd - a.price_math.current_usd)}`
  if (a.deadline) return `${n} return closes in ${a.deadline.days_left} days`
  return t.title
}
