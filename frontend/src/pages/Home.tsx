import { useRef } from 'react'
import { useDecision } from '@/components/DecisionSheet'
import { List, NavBar, Row, Section, SeeAll, useCountUp } from '@/components/shell'
import { TaskRow } from '@/components/TaskRow'
import { Thumb, decisionLine } from '@/components/task-meta'
import { getApprovals, getFeed } from '@/lib/api'
import { useNow, usePoll } from '@/lib/hooks'
import { usd } from '@/lib/utils'

const DISMISSED = new Set(['kept', 'ignored', 'dismissed'])

export default function Home() {
  const now = useNow(15_000)
  const openDecision = useDecision()
  const { data: feed, error } = usePoll(getFeed, 1500)
  const { data: approvals } = usePoll(getApprovals, 1500)
  const taps = useRef<number[]>([])

  const tasks = feed ?? []
  const byId = new Map(tasks.map((t) => [t.task_id, t]))
  const pending = (approvals ?? []).filter((a) => !a.choice && byId.has(a.task_id))
  const pendingIds = new Set(pending.map((a) => a.task_id))
  const handled = tasks.filter((t) => t.status !== 'awaiting_user' && !pendingIds.has(t.task_id) && !DISMISSED.has(t.decision ?? ''))
  const done = handled.filter((t) => t.status === 'done')
  const monthStart = new Date(new Date(now).getFullYear(), new Date(now).getMonth(), 1).getTime()
  const back = done.filter((t) => new Date(t.updated_at).getTime() >= monthStart).reduce((s, t) => s + (t.amount_usd ?? 0), 0)
  const count = useCountUp(back)

  // Triple-tap the title opens demo controls (no keyboard on a phone).
  const onTitleTap = () => {
    const t = Date.now()
    taps.current = [...taps.current.filter((x) => t - x < 600), t]
    if (taps.current.length >= 3) {
      taps.current = []
      window.dispatchEvent(new Event('snapback:demo'))
    }
  }

  return (
    <div>
      <NavBar title="Snapback" onTitleTap={onTitleTap} />

      <div className="px-4">
        <div className="bg-card rounded-2xl px-5 py-5">
          <div className="text-green text-[44px] leading-none font-bold tracking-[-0.03em] tabular-nums">{usd(Math.round(count))}</div>
          <div className="mt-1.5 text-[17px] font-medium">back to you this month</div>
          <div className="text-ink-2 mt-3 text-[15px]">
            {done.length} handled
            {pending.length > 0 && (
              <>
                {' · '}
                <span className="text-amber">{pending.length} need you</span>
              </>
            )}
          </div>
        </div>
        {error && !feed && <p className="text-red mt-3 px-1 text-[14px]">Can’t reach the backend: {error}</p>}
      </div>

      {pending.length > 0 && (
        <Section title="Needs you" action={pending.length > 2 ? <SeeAll to="/inbox" /> : null} className="mt-7">
          <List inset={76}>
            {pending.slice(0, 2).map((a) => {
              const t = byId.get(a.task_id)!
              return (
                <Row
                  key={a.approval_id}
                  onClick={() => openDecision(a, t)}
                  leading={<Thumb src={t.order?.image_url} />}
                  title={decisionLine(a, t)}
                  trailing={<span className="bg-amber size-2 shrink-0 rounded-full" />}
                  chevron
                />
              )
            })}
          </List>
        </Section>
      )}

      <Section title="Recent" action={<SeeAll to="/activity" />} className="mt-7">
        <List inset={76}>
          {handled.slice(0, 3).map((t) => (
            <TaskRow key={t.task_id} task={t} now={now} />
          ))}
        </List>
        {feed && handled.length === 0 && <p className="text-ink-2 px-1 text-[15px]">Nothing yet.</p>}
      </Section>
    </div>
  )
}
