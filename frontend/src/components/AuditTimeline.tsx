import type { ReactNode } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Check, Loader2, ShieldCheck, X } from 'lucide-react'
import { List, Row, Sheet } from '@/components/shell'
import { authorizedLabel, stepMeta } from '@/components/task-meta'
import { cn, fmtMs, shortHash } from '@/lib/utils'
import type { AuditEntry, ChainCheck } from '@/lib/types'

const hm = (iso: string) => new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })

/** One quiet row: "Every step verified" (green) or "Record was altered" (red). Tap → chain details. */
export function TrustRow({ check, steps, onClick }: { check: ChainCheck | null; steps: number; onClick: () => void }) {
  const icon = !check ? (
    <Loader2 className="text-ink-3 size-6 animate-spin" />
  ) : check.ok ? (
    <span className="bg-green flex size-7 items-center justify-center rounded-full text-white">
      <Check className="size-4" strokeWidth={2.6} />
    </span>
  ) : (
    <span className="bg-red flex size-7 items-center justify-center rounded-full text-white">
      <X className="size-4" strokeWidth={2.6} />
    </span>
  )
  return (
    <List>
      <Row
        onClick={onClick}
        leading={<span className="flex size-7 items-center justify-center">{icon}</span>}
        title={!check ? 'Checking record…' : check.ok ? 'Every step verified' : <span className="text-red font-medium">Record was altered</span>}
        subtitle={!check ? undefined : check.ok ? `${steps} steps · tamper-evident record` : 'A step changed after it was recorded'}
        chevron
      />
    </List>
  )
}

export function ChainSheet({ open, onClose, check, entries, onRecheck }: { open: boolean; onClose: () => void; check: ChainCheck | null; entries: AuditEntry[]; onRecheck: () => void }) {
  const broken = check && !check.ok ? entries.find((e) => e.entry_id === check.broken_at) : undefined
  const last = entries[entries.length - 1]
  return (
    <Sheet open={open} onClose={onClose}>
      <div className="flex flex-col items-center pt-2 text-center">
        <span className={cn('flex size-14 items-center justify-center rounded-full text-white', check?.ok === false ? 'bg-red' : 'bg-green')}>
          {check?.ok === false ? <X className="size-7" strokeWidth={2.4} /> : <ShieldCheck className="size-7" strokeWidth={2} />}
        </span>
        <h2 className="mt-3 text-[20px] font-semibold">{check?.ok === false ? 'Record was altered' : 'Every step verified'}</h2>
        <p className="text-ink-2 mt-1.5 text-[15px] leading-snug">
          Each step is sealed with a SHA-256 hash that includes the step before it. Changing anything breaks every hash after it.
        </p>
      </div>
      <List className="bg-bg mt-5">
        <Row title="Steps in this record" trailing={<span className="text-ink-2 tabular-nums">{entries.length}</span>} />
        <Row title="Check" subtitle={check?.detail} />
        {broken && <Row title={<span className="text-red">Altered step</span>} trailing={<span className="text-red">{stepMeta(broken.step).label}</span>} />}
        {last && <Row title="Latest hash" trailing={<span className="text-ink-2 font-mono text-[13px]">{shortHash(last.entry_hash)}</span>} />}
      </List>
      <button onClick={onRecheck} className="tap bg-fill mt-4 h-12 w-full rounded-xl text-[17px] font-semibold">
        Check again
      </button>
    </Sheet>
  )
}

function Block({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="text-ink-3 mb-1 text-[12px] font-medium tracking-wide uppercase">{label}</div>
      {children}
    </div>
  )
}

function Expanded({ e, broken }: { e: AuditEntry; broken: boolean }) {
  const auth = authorizedLabel(e.authorized_by)
  const foot = [e.model, e.cost_usd !== null ? `$${e.cost_usd.toFixed(4)}` : null, e.latency_ms !== null ? fmtMs(e.latency_ms) : null].filter(Boolean).join(' · ')
  return (
    <div className="space-y-3.5 pt-0.5 pb-4 pl-10">
      {e.reason && <p className="text-ink-2 text-[14px] leading-snug">{e.reason}</p>}
      {broken && <p className="text-red text-[14px] font-medium">This step was changed after it was recorded.</p>}

      {e.sources.length > 0 && (
        <Block label="Sources">
          <ul className="space-y-1.5">
            {e.sources.map((s, i) => (
              <li key={i} className="text-[14px] leading-snug">
                {s.url ? (
                  <a href={s.url} target="_blank" rel="noreferrer" className="decoration-ink-3 underline underline-offset-2">
                    {s.doc}
                  </a>
                ) : (
                  <span>{s.doc}</span>
                )}
                <span className="text-ink-2"> — {s.section}</span>
              </li>
            ))}
          </ul>
        </Block>
      )}

      {e.rules_checked.length > 0 && (
        <Block label="Rules checked">
          <ul className="space-y-1">
            {e.rules_checked.map((r, i) => (
              <li key={i} className="flex items-start gap-2 text-[14px] leading-snug">
                {r.passed ? <Check className="text-green mt-0.5 size-4 shrink-0" strokeWidth={2.4} /> : <X className="text-red mt-0.5 size-4 shrink-0" strokeWidth={2.4} />}
                <span>
                  {r.rule}
                  <span className="text-ink-2"> — {r.evidence}</span>
                </span>
              </li>
            ))}
          </ul>
        </Block>
      )}

      {e.rejected_options.length > 0 && (
        <Block label="Options rejected">
          <ul className="space-y-1">
            {e.rejected_options.map((r, i) => (
              <li key={i} className="text-[14px] leading-snug">
                {r.option}
                <span className="text-ink-2"> — {r.reason}</span>
              </li>
            ))}
          </ul>
        </Block>
      )}

      <Block label="Approved by">
        <div className="text-[14px]">
          {auth.title}
          {auth.detail && <span className="text-ink-2"> · {auth.detail}</span>}
        </div>
      </Block>

      {foot && <div className="text-ink-3 text-[12px]">{foot}</div>}
    </div>
  )
}

export function Timeline({ entries, chain, open, onToggle, working }: { entries: AuditEntry[]; chain: ChainCheck | null; open: Set<number>; onToggle: (id: number) => void; working?: string | null }) {
  return (
    <div className="bg-card rounded-2xl px-4 py-1">
      {entries.map((e, i) => {
        const m = stepMeta(e.step)
        const Icon = m.icon
        const broken = chain?.ok === false && chain.broken_at === e.entry_id
        const isOpen = open.has(e.entry_id)
        const last = i === entries.length - 1 && !working
        return (
          <div key={e.entry_id} className="relative">
            {!last && <span className="bg-sep absolute top-[42px] bottom-0 left-[13.5px] w-px" />}
            <button onClick={() => onToggle(e.entry_id)} className="flex w-full items-start gap-3 py-3 text-left">
              <span
                className={cn(
                  'relative flex size-7 shrink-0 items-center justify-center rounded-full',
                  broken ? 'bg-red text-white' : e.verified ? 'bg-green text-white' : 'bg-fill text-ink-2',
                )}
              >
                <Icon className="size-[15px]" strokeWidth={1.8} />
              </span>
              <span className={cn('min-w-0 flex-1 pt-[3px] text-[15px] leading-snug', !isOpen && 'truncate', broken && 'text-red')}>{e.decision}</span>
              <span className="text-ink-3 shrink-0 pt-[4px] text-[13px] tabular-nums">{hm(e.created_at)}</span>
            </button>
            <AnimatePresence initial={false}>
              {isOpen && (
                <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.2, ease: 'easeOut' }} className="overflow-hidden">
                  <Expanded e={e} broken={broken} />
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )
      })}
      {working && (
        <div className="flex items-center gap-3 py-3">
          <span className="flex size-7 items-center justify-center">
            <Loader2 className="text-ink-2 size-4 animate-spin" />
          </span>
          <span className="text-ink-2 text-[15px]">{working}</span>
        </div>
      )}
    </div>
  )
}
