import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ChevronLeft, ChevronsDownUp, ChevronsUpDown, Clock, Download, Layers, Wallet } from 'lucide-react'
import { AuditTimeline, ChainBadge } from '@/components/AuditTimeline'
import { DecisionCard } from '@/components/DecisionCard'
import { useCountUp } from '@/components/shell'
import { ProductImage, StatusBadge, TRIGGER, isActive } from '@/components/task-meta'
import { getApprovalForTask, getAudit, getTask, verifyChain } from '@/lib/api'
import { usePoll } from '@/lib/hooks'
import { cn, fmtDate, fmtMs, storeName, usd } from '@/lib/utils'
import type { ChainCheck } from '@/lib/types'

const WORKING_LABEL: Record<string, string> = {
  detected: 'Planning next step…',
  planned: 'Planning next step…',
  executing: 'Working on it…',
  verifying: 'Verifying with outside evidence…',
  awaiting_refund: 'Waiting for the refund to post…',
}

export default function TaskDetail() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const { data: task, error } = usePoll(() => getTask(id), 1000, [id])
  const { data: audit } = usePoll(() => getAudit(id), 1000, [id])
  const { data: approval } = usePoll(() => getApprovalForTask(id), 1500, [id])
  const [chain, setChain] = useState<ChainCheck | null>(null)
  const [open, setOpen] = useState<Set<number>>(new Set())

  const entries = useMemo(() => audit ?? [], [audit])
  const auditKey = JSON.stringify(entries)
  useEffect(() => {
    if (!audit) return
    let alive = true
    verifyChain(id, audit).then((c) => alive && setChain(c))
    return () => {
      alive = false
    }
    // re-verify only when the entries actually change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auditKey, id])

  const totals = useMemo(() => {
    const cost = entries.reduce((s, e) => s + (e.cost_usd ?? 0), 0)
    const compute = entries.reduce((s, e) => s + (e.latency_ms ?? 0), 0)
    const wall = entries.length > 1 ? new Date(entries[entries.length - 1].created_at).getTime() - new Date(entries[0].created_at).getTime() : 0
    return { cost, compute, wall }
  }, [entries])

  const amount = useCountUp(task?.amount_usd ?? 0)

  if (task === null || (error && !task)) {
    return (
      <div className="px-5 py-24 text-center">
        <p className="text-xl font-semibold">Task not found</p>
        <Link to="/" className="text-money mt-3 inline-block font-semibold">
          Back home
        </Link>
      </div>
    )
  }
  if (!task) return <div className="text-muted py-24 text-center">Loading…</div>

  const o = task.order
  const pending = approval && !approval.choice ? approval : null
  const done = task.status === 'done'
  const allIds = entries.map((e) => e.entry_id)
  const allOpen = allIds.length > 0 && allIds.every((x) => open.has(x))
  const toggle = (eid: number) =>
    setOpen((s) => {
      const n = new Set(s)
      if (n.has(eid)) n.delete(eid)
      else n.add(eid)
      return n
    })

  const exportJson = () => {
    const blob = new Blob([JSON.stringify({ task, chain, audit: entries }, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `snapback-audit-${task.task_id}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div>
      <header className="bg-bg/85 sticky top-0 z-30 flex items-center gap-2 px-3 py-2.5 backdrop-blur-xl">
        <button onClick={() => (window.history.length > 1 ? navigate(-1) : navigate('/'))} className="tap bg-surface flex size-10 items-center justify-center rounded-full ring-1 ring-white/8" aria-label="Back">
          <ChevronLeft className="size-5" />
        </button>
        <div className="min-w-0 flex-1 text-center">
          <div className="truncate text-[16px] font-semibold">{task.title}</div>
          <div className="text-faint truncate text-[12px]">{TRIGGER[task.trigger_type]?.label ?? task.trigger_type}</div>
        </div>
        <button onClick={exportJson} className="tap bg-surface flex size-10 items-center justify-center rounded-full ring-1 ring-white/8" aria-label="Export JSON">
          <Download className="size-[18px]" />
        </button>
      </header>

      {/* Outcome */}
      <section className="relative px-5 pt-3 pb-5 text-center">
        <div className={cn('pointer-events-none absolute top-6 left-1/2 size-56 -translate-x-1/2 rounded-full blur-3xl', done ? 'bg-money/15' : 'bg-warn/10')} />
        <ProductImage src={o?.image_url} alt={o?.item_name} className="relative mx-auto size-[112px] rounded-[30px]" />
        <div className="relative mt-4 text-[24px] leading-tight font-bold tracking-[-0.02em]">{o?.item_name ?? task.title}</div>
        <div className="text-muted relative mt-1 text-[14px]">
          {o ? `${storeName(o.store)} · ${o.order_id} · paid ${usd(o.price)}` : task.order_id}
          {o?.delivered_at ? ` · delivered ${fmtDate(o.delivered_at)}` : ''}
        </div>
        {task.amount_usd !== null && (
          <div className="relative mt-4">
            <div className={cn('text-[52px] leading-none font-bold tracking-[-0.04em] tabular-nums', done ? 'text-money' : 'text-warn')}>
              {usd(Math.round(amount * 100) / 100, { sign: done })}
            </div>
            <div className="text-faint mt-1 text-[13px] font-bold tracking-wider uppercase">{done ? 'Recovered' : 'At stake'}</div>
          </div>
        )}
        <div className="relative mt-3 flex items-center justify-center gap-2">
          <StatusBadge status={task.status} />
        </div>
        <p className="text-ink/85 relative mx-auto mt-3 max-w-[320px] text-[15px] leading-snug">{task.outcome ?? task.summary}</p>
      </section>

      <div className="space-y-4 px-4">
        <ChainBadge check={chain} onClick={() => audit && verifyChain(id, audit).then(setChain)} />
        {pending && <DecisionCard approval={pending} task={task} className="w-full" />}
      </div>

      {/* Timeline */}
      <section className="mt-7 px-4">
        <div className="mb-4 flex items-center justify-between px-1">
          <div>
            <h2 className="text-[20px] font-bold tracking-[-0.02em]">Audit trail</h2>
            <p className="text-muted text-[13px]">Every step, its evidence, and who authorized it</p>
          </div>
          <button onClick={() => setOpen(allOpen ? new Set() : new Set(allIds))} className="tap bg-surface flex items-center gap-1.5 rounded-full px-3 py-2 text-[13px] font-semibold ring-1 ring-white/8">
            {allOpen ? <ChevronsDownUp className="size-4" /> : <ChevronsUpDown className="size-4" />}
            {allOpen ? 'Collapse' : 'Expand all'}
          </button>
        </div>
        <AuditTimeline entries={entries} chain={chain} open={open} onToggle={toggle} working={isActive(task.status) ? WORKING_LABEL[task.status] : null} />
      </section>

      {/* Totals */}
      <section className="mt-3 space-y-3 px-4">
        <div className="grid grid-cols-3 gap-2">
          <Stat icon={Wallet} label="Run cost" value={`$${totals.cost.toFixed(4)}`} />
          <Stat icon={Clock} label="Total time" value={fmtMs(totals.wall)} sub={`${fmtMs(totals.compute)} compute`} />
          <Stat icon={Layers} label="Steps" value={String(entries.length)} />
        </div>
        <button onClick={exportJson} className="tap bg-surface flex w-full items-center justify-center gap-2 rounded-[20px] py-4 text-[16px] font-semibold ring-1 ring-white/8">
          <Download className="size-5" /> Export audit JSON
        </button>
      </section>
    </div>
  )
}

function Stat({ icon: Icon, label, value, sub }: { icon: typeof Wallet; label: string; value: string; sub?: string }) {
  return (
    <div className="bg-surface rounded-[20px] p-3 ring-1 ring-white/6">
      <Icon className="text-faint size-4" />
      <div className="mt-2 text-[18px] leading-none font-bold tracking-tight tabular-nums">{value}</div>
      <div className="text-faint mt-1 text-[12px] font-semibold">{label}</div>
      {sub && <div className="text-faint text-[11px]">{sub}</div>}
    </div>
  )
}
