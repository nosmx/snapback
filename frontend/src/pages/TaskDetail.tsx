import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { ChainSheet, Timeline, TrustRow } from '@/components/AuditTimeline'
import { useDecision } from '@/components/DecisionSheet'
import { List, NavBar, Row, Section } from '@/components/shell'
import { STATUS_TEXT, Thumb, decisionLine, isActive } from '@/components/task-meta'
import { getApprovalForTask, getAudit, getTask, verifyChain } from '@/lib/api'
import { usePoll } from '@/lib/hooks'
import { cn, storeName, usd } from '@/lib/utils'
import type { ChainCheck } from '@/lib/types'

const WORKING: Record<string, string> = {
  detected: 'Planning the next step…',
  planned: 'Planning the next step…',
  executing: 'Working on it…',
  verifying: 'Confirming with outside evidence…',
  awaiting_refund: 'Waiting for the refund to post…',
}

export default function TaskDetail() {
  const { id = '' } = useParams()
  const openDecision = useDecision()
  const { data: task, error } = usePoll(() => getTask(id), 1000, [id])
  const { data: audit } = usePoll(() => getAudit(id), 1000, [id])
  const { data: approval } = usePoll(() => getApprovalForTask(id), 1500, [id])
  const [chain, setChain] = useState<ChainCheck | null>(null)
  const [open, setOpen] = useState<Set<number>>(new Set())
  const [chainOpen, setChainOpen] = useState(false)

  const entries = useMemo(() => audit ?? [], [audit])
  const auditKey = JSON.stringify(entries)
  const recheck = () => audit && verifyChain(id, audit).then(setChain)
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

  if (task === null || (error && !task)) {
    return (
      <>
        <NavBar title="" large={false} back />
        <div className="text-ink-2 py-24 text-center text-[17px]">This task doesn’t exist.</div>
      </>
    )
  }
  if (!task) return <NavBar title="" large={false} back />

  const o = task.order
  const pending = approval && !approval.choice ? approval : null
  const done = task.status === 'done'
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
    a.download = `snapback-record-${task.task_id}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div>
      <NavBar title={task.title} large={false} back />

      <header className="flex flex-col items-center px-6 pt-4 pb-6 text-center">
        <Thumb src={o?.image_url} className="size-24 rounded-[22px]" />
        <h1 className="mt-4 text-[22px] leading-tight font-semibold tracking-[-0.01em]">{task.title}</h1>
        <p className="text-ink-2 mt-1 text-[15px] leading-snug">
          {o ? `${o.item_name} · ${storeName(o.store)}` : task.order_id}
        </p>
        {task.amount_usd !== null && (
          <div className={cn('mt-4 text-[40px] leading-none font-bold tracking-[-0.02em] tabular-nums', done ? 'text-green' : pending ? 'text-amber' : 'text-ink')}>
            {usd(task.amount_usd, { sign: done })}
          </div>
        )}
        <p className="text-ink-2 mt-2 text-[15px] leading-snug">
          {done ? task.outcome ?? task.summary : pending ? 'Waiting for your decision' : `${STATUS_TEXT[task.status]}…`}
        </p>
      </header>

      <div className="space-y-3 px-4">
        {pending && (
          <List>
            <Row
              onClick={() => openDecision(pending, task)}
              leading={<span className="bg-amber size-2.5 shrink-0 rounded-full" />}
              title={decisionLine(pending, task)}
              subtitle="Needs your decision"
              chevron
            />
          </List>
        )}
        <TrustRow check={chain} steps={entries.length} onClick={() => setChainOpen(true)} />
      </div>

      <Section title="What happened" className="mt-7">
        <Timeline entries={entries} chain={chain} open={open} onToggle={toggle} working={isActive(task.status) ? WORKING[task.status] : null} />
      </Section>

      <div className="mt-6 text-center">
        <button onClick={exportJson} className="text-ink-2 text-[15px]">
          Export record
        </button>
      </div>

      <ChainSheet open={chainOpen} onClose={() => setChainOpen(false)} check={chain} entries={entries} onRecheck={recheck} />
    </div>
  )
}
