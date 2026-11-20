import { useState } from 'react'
import { motion } from 'framer-motion'
import { List, NavBar } from '@/components/shell'
import { TaskRow } from '@/components/TaskRow'
import { categoryOf } from '@/components/task-meta'
import { getFeed } from '@/lib/api'
import { useNow, usePoll } from '@/lib/hooks'
import { cn } from '@/lib/utils'
import type { Task } from '@/lib/types'

const SEGMENTS = [
  { key: 'all', label: 'All' },
  { key: 'returns', label: 'Returns' },
  { key: 'price', label: 'Price' },
  { key: 'claims', label: 'Claims' },
] as const
type Seg = (typeof SEGMENTS)[number]['key']

function bucket(iso: string, now: number) {
  const d = new Date(now)
  const start = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  const t = new Date(iso).getTime()
  if (t >= start) return 'Today'
  if (t >= start - 86_400_000) return 'Yesterday'
  return 'Earlier'
}

export default function Activity() {
  const now = useNow(15_000)
  const { data: feed } = usePoll(getFeed, 1500)
  const [seg, setSeg] = useState<Seg>('all')
  const tasks = (feed ?? []).filter((t) => seg === 'all' || categoryOf(t) === seg)

  const groups: { label: string; items: Task[] }[] = []
  for (const t of tasks) {
    const label = bucket(t.updated_at ?? t.created_at, now)
    const g = groups.find((x) => x.label === label)
    if (g) g.items.push(t)
    else groups.push({ label, items: [t] })
  }

  return (
    <div>
      <NavBar title="Activity" />
      <div className="px-4">
        <div className="bg-fill grid grid-cols-4 rounded-[9px] p-[2px]">
          {SEGMENTS.map((s) => (
            <button key={s.key} onClick={() => setSeg(s.key)} className="relative h-8 text-[13px] font-medium">
              {seg === s.key && <motion.span layoutId="seg" transition={{ duration: 0.2 }} className="bg-card absolute inset-0 rounded-[7px] shadow-[0_1px_3px_rgba(0,0,0,0.12)]" />}
              <span className={cn('relative', seg === s.key ? 'text-ink' : 'text-ink-2')}>{s.label}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="mt-5 space-y-6 px-4">
        {groups.map((g) => (
          <section key={g.label}>
            <h2 className="text-ink-2 mb-1.5 px-4 text-[13px] uppercase">{g.label}</h2>
            <List inset={76}>
              {g.items.map((t) => (
                <TaskRow key={t.task_id} task={t} now={now} />
              ))}
            </List>
          </section>
        ))}
        {feed && tasks.length === 0 && <p className="text-ink-2 py-16 text-center text-[15px]">Nothing here yet.</p>}
      </div>
    </div>
  )
}
