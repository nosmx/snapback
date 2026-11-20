import { AnimatePresence, motion } from 'framer-motion'
import {
  BookOpen, CheckCircle2, ChevronDown, CircleSlash, Cpu, Database, ExternalLink, Fingerprint, Globe, Hash, ImageIcon,
  Landmark, Loader2, Mail, ScrollText, ShieldCheck, Timer, Wallet, XCircle, type LucideIcon,
} from 'lucide-react'
import { authorizedLabel, stepMeta } from '@/components/task-meta'
import { cn, fmtMs, fmtTime, shortHash } from '@/lib/utils'
import type { AuditEntry, ChainCheck, Source } from '@/lib/types'

export function ChainBadge({ check, onClick }: { check: ChainCheck | null; onClick?: () => void }) {
  if (!check) {
    return (
      <div className="bg-surface text-muted flex items-center gap-3 rounded-[22px] p-4 ring-1 ring-white/8">
        <Loader2 className="size-7 animate-spin" />
        <div className="text-[17px] font-semibold">Checking audit chain…</div>
      </div>
    )
  }
  return (
    <motion.button
      type="button"
      onClick={onClick}
      initial={{ scale: 0.97, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      className={cn(
        'tap flex w-full items-center gap-3 rounded-[22px] p-4 text-left ring-1',
        check.ok ? 'bg-money/12 ring-money/40' : 'bg-danger/14 ring-danger/50',
      )}
    >
      <span className={cn('flex size-11 shrink-0 items-center justify-center rounded-full', check.ok ? 'bg-money text-money-ink' : 'bg-danger text-white')}>
        {check.ok ? <ShieldCheck className="size-6" strokeWidth={2.4} /> : <XCircle className="size-6" strokeWidth={2.4} />}
      </span>
      <div className="min-w-0">
        <div className={cn('text-[18px] font-bold tracking-tight', check.ok ? 'text-money' : 'text-danger')}>
          {check.ok ? 'Audit chain verified ✓' : 'Chain broken'}
        </div>
        <div className={cn('text-[13px] leading-snug', check.ok ? 'text-money/75' : 'text-danger/90')}>{check.detail}</div>
      </div>
    </motion.button>
  )
}

function sourceChip(s: Source): { label: string; icon: LucideIcon } {
  const sec = s.section.split(' — ')[0]
  if (/senso/i.test(s.doc)) return { label: `Senso · ${sec.startsWith('§') ? sec : s.doc.replace(/\s*\(Senso\)/, '')}`, icon: BookOpen }
  if (/email/i.test(s.doc)) return { label: s.doc.replace(/^Order confirmation /, ''), icon: Mail }
  if (/bank/i.test(s.doc)) return { label: 'Bank record', icon: Landmark }
  if (/singlestore/i.test(s.doc)) return { label: 'SingleStore vectors', icon: Database }
  if (/photo/i.test(s.doc)) return { label: 'Your photo', icon: ImageIcon }
  return { label: s.doc, icon: Globe }
}

function Chip({ s }: { s: Source }) {
  const { label, icon: Icon } = sourceChip(s)
  const cls = 'inline-flex max-w-[220px] shrink-0 items-center gap-1.5 rounded-full bg-white/7 px-2.5 py-1 text-[12px] font-semibold text-ink/85 ring-1 ring-white/8'
  const body = (
    <>
      <Icon className="text-money size-3.5 shrink-0" />
      <span className="truncate">{label}</span>
    </>
  )
  return s.url ? (
    <a href={s.url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} className={cn(cls, 'active:bg-white/12')}>
      {body}
    </a>
  ) : (
    <span className={cls}>{body}</span>
  )
}

function Label({ icon: Icon, children }: { icon: LucideIcon; children: string }) {
  return (
    <div className="text-faint mb-2 flex items-center gap-1.5 text-[12px] font-bold tracking-wider uppercase">
      <Icon className="size-3.5" /> {children}
    </div>
  )
}

function Details({ e, broken }: { e: AuditEntry; broken: boolean }) {
  const auth = authorizedLabel(e.authorized_by)
  return (
    <div className="bg-bg/70 mt-3 space-y-5 rounded-[20px] p-4 ring-1 ring-white/6">
      {e.sources.length > 0 && (
        <div>
          <Label icon={BookOpen}>Sources</Label>
          <div className="space-y-2">
            {e.sources.map((s, i) => {
              const inner = (
                <>
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-[14px] leading-snug font-semibold">{s.doc}</span>
                    {s.url && <ExternalLink className="text-money mt-0.5 size-3.5 shrink-0" />}
                  </div>
                  <div className="text-ink/75 mt-0.5 text-[14px] leading-snug">{s.section}</div>
                  <div className="text-faint mt-1 text-[12px]">retrieved {fmtTime(s.retrieved_at)}</div>
                </>
              )
              return s.url ? (
                <a key={i} href={s.url} target="_blank" rel="noreferrer" className="bg-surface block rounded-2xl p-3 ring-1 ring-white/6 active:bg-surface-2">
                  {inner}
                </a>
              ) : (
                <div key={i} className="bg-surface rounded-2xl p-3 ring-1 ring-white/6">
                  {inner}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {e.rules_checked.length > 0 && (
        <div>
          <Label icon={ScrollText}>Rules checked</Label>
          <ul className="space-y-2">
            {e.rules_checked.map((r, i) => (
              <li key={i} className="flex items-start gap-2.5">
                {r.passed ? <CheckCircle2 className="text-money mt-px size-[18px] shrink-0" /> : <XCircle className="text-danger mt-px size-[18px] shrink-0" />}
                <div className="text-[14px] leading-snug">
                  <span className="font-semibold">{r.rule}</span>
                  <span className="text-muted"> — {r.evidence}</span>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {e.rejected_options.length > 0 && (
        <div>
          <Label icon={CircleSlash}>Rejected options</Label>
          <ul className="space-y-2">
            {e.rejected_options.map((r, i) => (
              <li key={i} className="flex items-start gap-2.5">
                <CircleSlash className="text-faint mt-px size-[18px] shrink-0" />
                <div className="text-[14px] leading-snug">
                  <span className="text-ink/90 font-semibold">{r.option}</span>
                  <span className="text-muted"> — {r.reason}</span>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="space-y-3 border-t border-white/6 pt-4">
        <div className="flex items-start gap-2.5">
          {auth.kind === 'approval' ? <Fingerprint className="text-money mt-0.5 size-5 shrink-0" /> : <ScrollText className="text-info mt-0.5 size-5 shrink-0" />}
          <div className="min-w-0">
            <div className="text-faint text-[12px] font-bold tracking-wider uppercase">Authorized by</div>
            <div className="text-[15px] font-semibold">
              {auth.title}
              {auth.kind === 'approval' && <span className="bg-money/15 text-money ml-2 rounded-full px-2 py-0.5 text-[11px] font-bold">PERSONA ✓</span>}
            </div>
            {auth.detail && <div className="text-muted font-mono text-[12px] break-all">{auth.detail}</div>}
          </div>
        </div>
        <div className="grid grid-cols-[1fr_auto_auto] gap-x-5 gap-y-1">
          <Meta icon={Cpu} label="Model / tool" value={e.model ?? '—'} />
          <Meta icon={Wallet} label="Cost" value={e.cost_usd === null ? '—' : `$${e.cost_usd.toFixed(5)}`} />
          <Meta icon={Timer} label="Latency" value={e.latency_ms === null ? '—' : fmtMs(e.latency_ms)} />
        </div>
      </div>

      <div className={cn('flex flex-wrap items-center gap-x-2 gap-y-0.5 font-mono text-[11px]', broken ? 'text-danger' : 'text-faint')}>
        <Hash className="size-3.5" />#{e.seq ?? e.entry_id}
        <span>prev {shortHash(e.prev_hash)}</span>→<span className={broken ? 'font-bold' : 'text-muted'}>{shortHash(e.entry_hash)}</span>
        {broken && <span className="w-full font-sans text-[13px] font-semibold">Hash mismatch — edited after it was sealed</span>}
      </div>
    </div>
  )
}

function Meta({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="text-faint flex items-center gap-1 text-[12px] font-bold tracking-wider uppercase">
        <Icon className="size-3.5" /> {label}
      </div>
      <div className="text-[14px] leading-snug font-semibold tabular-nums">{value}</div>
    </div>
  )
}

export function AuditTimeline({
  entries,
  chain,
  open,
  onToggle,
  working,
}: {
  entries: AuditEntry[]
  chain: ChainCheck | null
  open: Set<number>
  onToggle: (id: number) => void
  working?: string | null
}) {
  return (
    <ol>
      {entries.map((e, i) => {
        const m = stepMeta(e.step)
        const Icon = m.icon
        const broken = chain?.ok === false && chain.broken_at === e.entry_id
        const isOpen = open.has(e.entry_id)
        const last = i === entries.length - 1 && !working
        const passed = e.rules_checked.filter((r) => r.passed).length
        return (
          <motion.li key={e.entry_id} layout="position" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="relative pb-5 pl-12">
            {!last && <span className={cn('absolute top-10 bottom-0 left-[17px] w-[2px] rounded-full', e.verified ? 'bg-money/40' : 'bg-white/8')} />}
            <span
              className={cn(
                'absolute top-0 left-0 flex size-9 items-center justify-center rounded-full',
                broken ? 'bg-danger text-white' : e.verified ? 'bg-money text-money-ink' : 'bg-surface-2 text-ink/85 ring-1 ring-white/10',
              )}
            >
              {broken ? <XCircle className="size-[18px]" /> : <Icon className="size-[18px]" strokeWidth={2.2} />}
            </span>

            <button type="button" onClick={() => onToggle(e.entry_id)} className={cn('w-full text-left', broken && 'bg-danger/10 ring-danger/40 -m-2 rounded-2xl p-2 ring-1')}>
              <div className="flex items-center gap-2">
                <span className="text-faint text-[12px] font-bold tracking-wider uppercase">{m.label}</span>
                <span className="text-faint text-[12px] tabular-nums">· {fmtTime(e.created_at)}</span>
                {e.verified && <span className="bg-money/15 text-money rounded-full px-1.5 py-px text-[11px] font-bold">VERIFIED</span>}
                <ChevronDown className={cn('text-faint ml-auto size-4 shrink-0 transition-transform', isOpen && 'rotate-180')} />
              </div>
              <div className="mt-1 text-[16px] leading-snug font-semibold">{e.decision}</div>
              {e.reason && <div className={cn('text-muted mt-0.5 text-[14px] leading-snug', !isOpen && 'line-clamp-2')}>{e.reason}</div>}
              {!isOpen && (
                <div className="mt-2 flex items-center gap-1.5 overflow-hidden">
                  {e.sources.slice(0, 2).map((s, k) => (
                    <Chip key={k} s={s} />
                  ))}
                  {e.sources.length > 2 && <span className="text-faint shrink-0 text-[12px] font-semibold">+{e.sources.length - 2}</span>}
                  {e.rules_checked.length > 0 && (
                    <span className={cn('shrink-0 text-[12px] font-semibold', passed === e.rules_checked.length ? 'text-money' : 'text-warn')}>
                      {e.sources.length > 0 && '· '}
                      {passed}/{e.rules_checked.length} rules
                    </span>
                  )}
                </div>
              )}
            </button>

            <AnimatePresence initial={false}>
              {isOpen && (
                <motion.div
                  key="d"
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
                  className="overflow-hidden"
                >
                  <Details e={e} broken={broken} />
                </motion.div>
              )}
            </AnimatePresence>
          </motion.li>
        )
      })}
      {working && (
        <li className="relative pl-12">
          <span className="bg-money/15 text-money absolute top-0 left-0 flex size-9 items-center justify-center rounded-full">
            <Loader2 className="size-[18px] animate-spin" />
          </span>
          <div className="text-money pt-1.5 text-[16px] font-semibold">{working}</div>
        </li>
      )}
    </ol>
  )
}
