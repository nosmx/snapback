import type { ReactNode } from 'react'
import {
  BadgeDollarSign, BellRing, BookOpen, Calculator, CalendarClock, CalendarPlus, Camera, CircleAlert, Copy,
  FileCheck2, Fingerprint, Link2, ListOrdered, Loader2, MessageCircle, PackageX, Radar, Receipt, RefreshCw,
  Scale, ScanSearch, ShieldCheck, ShoppingCart, TrendingDown, Undo2, type LucideIcon,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import type { TaskStatus, TriggerType } from '@/lib/types'

export const TRIGGER: Record<TriggerType, { label: string; icon: LucideIcon; tone: string }> = {
  photo: { label: 'Photo', icon: Camera, tone: 'bg-info/15 text-info' },
  chat: { label: 'Chat', icon: MessageCircle, tone: 'bg-info/15 text-info' },
  price_drop_minor: { label: 'Price drop', icon: TrendingDown, tone: 'bg-money/15 text-money' },
  price_drop_major: { label: 'Major price drop', icon: TrendingDown, tone: 'bg-warn/15 text-warn' },
  return_window: { label: 'Return window', icon: CalendarClock, tone: 'bg-warn/15 text-warn' },
  missing_package: { label: 'Missing package', icon: PackageX, tone: 'bg-info/15 text-info' },
  duplicate: { label: 'Duplicate order', icon: Copy, tone: 'bg-white/8 text-muted' },
}

export type Tone = 'money' | 'warn' | 'danger' | 'info' | 'neutral'
const TONE: Record<Tone, string> = {
  money: 'bg-money/14 text-money',
  warn: 'bg-warn/14 text-warn',
  danger: 'bg-danger/14 text-danger',
  info: 'bg-info/14 text-info',
  neutral: 'bg-white/7 text-muted',
}

export function Pill({ tone = 'neutral', className, children }: { tone?: Tone; className?: string; children: ReactNode }) {
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[13px] font-semibold whitespace-nowrap [&>svg]:size-3.5', TONE[tone], className)}>
      {children}
    </span>
  )
}

const STATUS: Record<TaskStatus, { label: string; tone: Tone; spin?: boolean }> = {
  detected: { label: 'Detected', tone: 'info', spin: true },
  awaiting_user: { label: 'Needs you', tone: 'warn' },
  planned: { label: 'Planned', tone: 'info', spin: true },
  executing: { label: 'Working', tone: 'info', spin: true },
  verifying: { label: 'Verifying', tone: 'info', spin: true },
  awaiting_refund: { label: 'Awaiting refund', tone: 'info', spin: true },
  done: { label: 'Done', tone: 'money' },
  expired: { label: 'Expired', tone: 'neutral' },
  failed: { label: 'Failed', tone: 'danger' },
}

export function StatusBadge({ status, className }: { status: TaskStatus; className?: string }) {
  const s = STATUS[status] ?? STATUS.detected
  return (
    <Pill tone={s.tone} className={className}>
      {s.spin && <Loader2 className="animate-spin" />}
      {status === 'done' && <ShieldCheck />}
      {status === 'failed' && <CircleAlert />}
      {s.label}
    </Pill>
  )
}

export const isActive = (s: TaskStatus) => ['detected', 'planned', 'executing', 'verifying', 'awaiting_refund'].includes(s)

const STEPS: Record<string, { label: string; icon: LucideIcon }> = {
  task_detected: { label: 'Detected', icon: Radar },
  intent_classified: { label: 'Understood your message', icon: MessageCircle },
  photo_identified: { label: 'Identified the item', icon: ScanSearch },
  order_matched: { label: 'Matched the order', icon: Link2 },
  policy_retrieved: { label: 'Checked store policy', icon: BookOpen },
  options_computed: { label: 'Computed options', icon: Calculator },
  decision_made: { label: 'Decided', icon: Scale },
  user_notified: { label: 'Asked you', icon: BellRing },
  user_approved: { label: 'You decided', icon: Fingerprint },
  price_rechecked: { label: 'Re-checked the price', icon: RefreshCw },
  return_filed: { label: 'Filed the return', icon: Undo2 },
  claim_filed: { label: 'Filed the claim', icon: FileCheck2 },
  adjustment_filed: { label: 'Filed price adjustment', icon: Receipt },
  replacement_ranked: { label: 'Ranked replacements', icon: ListOrdered },
  order_placed: { label: 'Placed the order', icon: ShoppingCart },
  reminder_added: { label: 'Added a reminder', icon: CalendarPlus },
  verified: { label: 'Verified the outcome', icon: ShieldCheck },
  refund_received: { label: 'Refund received', icon: BadgeDollarSign },
}

export function stepMeta(step: string): { label: string; icon: LucideIcon } {
  if (STEPS[step]) return STEPS[step]
  const label = step.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
  return { label, icon: Radar }
}

export function authorizedLabel(a: string | null): { title: string; detail?: string; kind: 'approval' | 'mandate' | 'system' } {
  if (!a) return { title: 'System', kind: 'system' }
  if (a.startsWith('approval')) return { title: 'Your approval, Persona-verified', detail: a.replace(/^approval[.:]?/, ''), kind: 'approval' }
  if (a.startsWith('mandate')) return { title: 'Your standing rules', detail: a.replace(/^mandate[.:]?/, ''), kind: 'mandate' }
  if (a === 'user') return { title: 'You (one tap)', detail: 'no money moved, so no verification needed', kind: 'system' }
  if (a === 'verifier') return { title: 'Independent verifier', detail: 'checks outside evidence, never the executor’s claim', kind: 'system' }
  if (a === 'background_loop') return { title: 'Background monitor', detail: 'detection only — no action taken at this step', kind: 'system' }
  return { title: a, kind: 'system' }
}

export function ProductImage({ src, alt = '', className }: { src?: string | null; alt?: string; className?: string }) {
  return src ? (
    <img src={src} alt={alt} loading="lazy" className={cn('shrink-0 bg-white object-cover ring-1 ring-white/10', className)} />
  ) : (
    <div className={cn('bg-surface-3 shrink-0', className)} />
  )
}
