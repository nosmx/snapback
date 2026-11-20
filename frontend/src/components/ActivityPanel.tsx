// Desktop-only "Agent activity" log beside the phone: every audit entry across all tasks, newest first.
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { Loader2 } from 'lucide-react'
import { STATUS_TEXT, isActive, stepMeta } from '@/components/task-meta'
import { getFeed, subscribeAudit, type FeedMode } from '@/lib/api'
import { usePoll } from '@/lib/hooks'
import { cn } from '@/lib/utils'
import type { AuditEntry } from '@/lib/types'

const MAX_ROWS = 80
const BACKLOG = 30

/** Which sponsor tool did this step use? Primary chip first, at most two. */
function chipsFor(e: AuditEntry): string[] {
  const model = (e.model ?? '').toLowerCase()
  const auth = (e.authorized_by ?? '').toLowerCase()
  const rules = e.rules_checked.map((r) => `${r.rule} ${r.evidence}`).join(' ').toLowerCase()
  const out: string[] = []
  const add = (c: string) => !out.includes(c) && out.push(c)
  // Chips show the tool a step used, not who authorized it (so "approved by you" steps don't all say Persona).
  if (/persona/.test(model) || auth.startsWith('persona') || ['user_approved', 'mandate_verified', 'mandate_updated'].includes(e.step)) add('Persona')
  if (/senso/.test(model)) add('Senso')
  if (/singlestore/.test(model) || ['order_matched', 'email_ingested'].includes(e.step)) add('SingleStore')
  if (/\bsie\b|siglip|gliner|fastino|reranker|qwen|bge|superlinked/.test(model)) add('Superlinked')
  if (/statsig/.test(model) || /statsig/.test(rules)) add('Statsig')
  if (/claude|anthropic|sonnet|opus|haiku|\bllm\b/.test(model)) add('Claude')
  if (/playwright|browser/.test(model)) add('Browser')
  if (!out.length) {
    if (auth === 'verifier') add('Verifier')
    else if (auth === 'background_loop') add('Monitor')
    else if (/merchant|http/.test(model)) add('Merchant')
    else if (/calendar/.test(model)) add('Calendar')
    else if (/mail/.test(model)) add('Email')
    else if (auth === 'user') add('You')
    else add('Rules')
  }
  return out.slice(0, 2)
}

const hms = (iso: string) => new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', second: '2-digit' })
const MODE_TITLE: Record<FeedMode, string> = {
  stream: 'Streaming from /api/stream',
  polling: 'Polling /api/audit every 0.7 s',
  demo: 'Demo data (in-browser)',
  offline: 'Can’t reach the backend',
}

function Chip({ name }: { name: string }) {
  return <span className="bg-fill text-ink-2 rounded-[5px] px-1.5 py-px text-[11px] font-medium whitespace-nowrap">{name}</span>
}

export function ActivityPanel() {
  const navigate = useNavigate()
  const [entries, setEntries] = useState<AuditEntry[]>([]) // newest first
  const [fresh, setFresh] = useState<Set<number>>(new Set())
  const [mode, setMode] = useState<FeedMode>('polling')
  const backlog = useRef(true)
  const listRef = useRef<HTMLDivElement>(null)
  const { data: feed } = usePoll(getFeed, 1500)
  const running = (feed ?? []).filter((t) => isActive(t.status))

  useEffect(
    () =>
      subscribeAudit({
        onMode: setMode,
        onReset: () => {
          backlog.current = true
          setEntries([])
        },
        onEntries: (batch) => {
          const isBacklog = backlog.current
          backlog.current = false
          const add = (isBacklog ? batch.slice(-BACKLOG) : batch).slice().reverse()
          setEntries((prev) => {
            const seen = new Set(prev.map((e) => e.entry_id))
            return [...add.filter((e) => !seen.has(e.entry_id)), ...prev].slice(0, MAX_ROWS)
          })
          if (isBacklog) return
          const ids = add.map((e) => e.entry_id)
          setFresh((s) => new Set([...s, ...ids]))
          window.setTimeout(() => setFresh((s) => new Set([...s].filter((i) => !ids.includes(i)))), 1800)
          const el = listRef.current
          if (el && el.scrollTop < 80) el.scrollTo({ top: 0, behavior: 'smooth' })
        },
      }),
    [],
  )

  const open = (taskId: string) => /^tsk_/.test(taskId) && navigate(`/tasks/${taskId}`)

  return (
    <div className="bg-card flex h-full w-full flex-col overflow-hidden rounded-[24px] ring-1 ring-black/5">
      <div className="flex shrink-0 items-center justify-between border-b px-5 py-4">
        <h2 className="text-[17px] font-semibold">Agent activity</h2>
        <span title={MODE_TITLE[mode]} className={cn('flex items-center gap-1.5 text-[13px] font-medium', mode === 'offline' ? 'text-ink-3' : 'text-green')}>
          <span className="relative flex size-2">
            {mode !== 'offline' && <span className="bg-green absolute inline-flex size-full animate-ping rounded-full opacity-50" />}
            <span className={cn('relative inline-flex size-2 rounded-full', mode === 'offline' ? 'bg-ink-3' : 'bg-green')} />
          </span>
          {mode === 'offline' ? 'Offline' : 'Live'}
        </span>
      </div>

      <div ref={listRef} className="no-scrollbar min-h-0 flex-1 overflow-y-auto">
        <AnimatePresence initial={false}>
          {running.map((t) => (
            <motion.button
              key={`run-${t.task_id}`}
              layout="position"
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              onClick={() => open(t.task_id)}
              className="press block w-full border-b px-5 py-3 text-left"
            >
              <div className="text-ink-3 flex items-center gap-1.5 text-[12px]">
                <Loader2 className="size-3 animate-spin" /> running now
              </div>
              <div className="mt-1 truncate text-[14px]">
                <span className="font-medium">{t.title}</span>
                <span className="text-ink-2"> · {STATUS_TEXT[t.status]}…</span>
              </div>
            </motion.button>
          ))}
          {entries.map((e) => {
            const clickable = /^tsk_/.test(e.task_id)
            return (
              <motion.button
                key={e.entry_id}
                layout="position"
                initial={{ opacity: 0, y: -10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.22, ease: 'easeOut' }}
                onClick={() => open(e.task_id)}
                disabled={!clickable}
                className={cn('relative block w-full border-b px-5 py-3 text-left', clickable ? 'press' : 'cursor-default')}
              >
                {fresh.has(e.entry_id) && (
                  <motion.span className="bg-green/10 pointer-events-none absolute inset-0" initial={{ opacity: 1 }} animate={{ opacity: 0 }} transition={{ duration: 1.6, ease: 'easeOut' }} />
                )}
                <div className="relative flex items-center gap-1.5 text-[12px]">
                  <span className="text-ink-3 mr-0.5 tabular-nums">{hms(e.created_at)}</span>
                  {chipsFor(e).map((c) => (
                    <Chip key={c} name={c} />
                  ))}
                </div>
                <div className="relative mt-1 truncate text-[14px]">
                  <span className={cn('font-medium', e.verified && 'text-green')}>{stepMeta(e.step).label}</span>
                  <span className="text-ink-2"> · {e.decision}</span>
                </div>
              </motion.button>
            )
          })}
        </AnimatePresence>
        {entries.length === 0 && running.length === 0 && <p className="text-ink-3 px-5 py-10 text-center text-[14px]">Waiting for the agent…</p>}
      </div>
    </div>
  )
}
