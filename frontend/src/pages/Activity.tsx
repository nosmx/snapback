import { useState } from 'react'
import { motion } from 'framer-motion'
import { FeedRow } from '@/components/FeedRow'
import { isActive } from '@/components/task-meta'
import { getFeed } from '@/lib/api'
import { useNow, usePoll } from '@/lib/hooks'
import { cn, usd } from '@/lib/utils'
import type { Task } from '@/lib/types'

const FILTERS = [
  { key: 'all', label: 'All', test: () => true },
  { key: 'money', label: 'Recovered', test: (t: Task) => t.status === 'done' && (t.amount_usd ?? 0) > 0 },
  { key: 'you', label: 'Needs you', test: (t: Task) => t.status === 'awaiting_user' },
  { key: 'live', label: 'In progress', test: (t: Task) => isActive(t.status) },
] as const

function dayLabel(iso: string, now: number) {
  const d = new Date(iso)
  const today = new Date(now)
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime()
  if (d.getTime() >= start) return 'Today'
  if (d.getTime() >= start - 86_400_000) return 'Yesterday'
  return d.toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' })
}

export default function Activity() {
  const now = useNow(15_000)
  const { data: feed } = usePoll(getFeed, 1500)
  const [filter, setFilter] = useState<(typeof FILTERS)[number]['key']>('all')
  const f = FILTERS.find((x) => x.key === filter)!
  const tasks = (feed ?? []).filter(f.test)
  const total = (feed ?? []).filter((t) => t.status === 'done').reduce((s, t) => s + (t.amount_usd ?? 0), 0)

  const groups: { label: string; items: Task[] }[] = []
  for (const t of tasks) {
    const label = dayLabel(t.updated_at ?? t.created_at, now)
    const g = groups.find((x) => x.label === label)
    if (g) g.items.push(t)
    else groups.push({ label, items: [t] })
  }

  return (
    <div>
      <header className="bg-bg/85 sticky top-0 z-30 px-5 pt-3 pb-3 backdrop-blur-xl">
        <div className="flex items-end justify-between">
          <h1 className="text-[28px] leading-tight font-bold tracking-[-0.03em]">Activity</h1>
          <div className="text-right">
            <div className="text-money text-[18px] font-bold tabular-nums">{usd(total, { sign: true })}</div>
            <div className="text-faint text-[12px]">all time</div>
          </div>
        </div>
        <div className="no-scrollbar -mx-5 mt-3 flex gap-2 overflow-x-auto px-5">
          {FILTERS.map((x) => (
            <button
              key={x.key}
              onClick={() => setFilter(x.key)}
              className={cn(
                'tap relative shrink-0 rounded-full px-4 py-2 text-[14px] font-semibold',
                filter === x.key ? 'text-money-ink' : 'bg-surface text-muted ring-1 ring-white/8',
              )}
            >
              {filter === x.key && <motion.span layoutId="filter-pill" className="bg-money absolute inset-0 rounded-full" transition={{ type: 'spring', stiffness: 500, damping: 35 }} />}
              <span className="relative">{x.label}</span>
            </button>
          ))}
        </div>
      </header>

      <div className="space-y-6 px-4 pt-2">
        {groups.map((g) => (
          <section key={g.label}>
            <h2 className="text-faint mb-2 px-1 text-[13px] font-bold tracking-wider uppercase">{g.label}</h2>
            <div className="space-y-2.5">
              {g.items.map((t) => (
                <FeedRow key={t.task_id} task={t} now={now} />
              ))}
            </div>
          </section>
        ))}
        {feed && tasks.length === 0 && <div className="text-muted py-16 text-center text-[15px]">Nothing here yet.</div>}
      </div>
    </div>
  )
}
