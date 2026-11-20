import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { BellRing, CheckCircle2, ChevronRight, Sparkles } from 'lucide-react'
import { DecisionCard } from '@/components/DecisionCard'
import { FeedRow } from '@/components/FeedRow'
import { LogoMark, SectionTitle, useCountUp } from '@/components/shell'
import { Pill } from '@/components/task-meta'
import { USE_MOCK, getApprovals, getFeed } from '@/lib/api'
import { useNow, usePoll } from '@/lib/hooks'
import { cn, usd } from '@/lib/utils'

const DISMISSED = new Set(['kept', 'ignored', 'dismissed'])

export default function Home() {
  const now = useNow(15_000)
  const { data: feed, error } = usePoll(getFeed, 1500)
  const { data: approvals } = usePoll(getApprovals, 1500)
  const [slide, setSlide] = useState(0)
  const taps = useRef<number[]>([])

  const tasks = feed ?? []
  const byId = new Map(tasks.map((t) => [t.task_id, t]))
  const pending = (approvals ?? []).filter((a) => !a.choice && byId.has(a.task_id))
  const pendingIds = new Set(pending.map((a) => a.task_id))
  const handled = tasks.filter((t) => t.status !== 'awaiting_user' && !pendingIds.has(t.task_id) && !DISMISSED.has(t.decision ?? ''))
  const done = handled.filter((t) => t.status === 'done')
  const monthStart = new Date(new Date(now).getFullYear(), new Date(now).getMonth(), 1).getTime()
  const recovered = done.filter((t) => new Date(t.updated_at).getTime() >= monthStart).reduce((s, t) => s + (t.amount_usd ?? 0), 0)
  const count = useCountUp(recovered, 1.2)

  // Triple-tap the logo opens demo controls (no keyboard on a phone).
  const onLogo = () => {
    const t = Date.now()
    taps.current = [...taps.current.filter((x) => t - x < 600), t]
    if (taps.current.length >= 3) {
      taps.current = []
      window.dispatchEvent(new Event('snapback:demo'))
    }
  }

  return (
    <div>
      <header className="bg-bg/85 sticky top-0 z-30 flex items-center justify-between px-5 py-3 backdrop-blur-xl">
        <button onClick={onLogo} className="flex items-center gap-2.5" aria-label="Snapback">
          <LogoMark />
          <span className="text-[20px] font-bold tracking-[-0.03em]">Snapback</span>
        </button>
        <div className="flex items-center gap-2">
          {USE_MOCK && <span className="text-faint rounded-full bg-white/6 px-2 py-0.5 text-[11px] font-semibold">demo data</span>}
          <span className="bg-surface-2 relative flex size-9 items-center justify-center rounded-full text-[13px] font-bold ring-1 ring-white/10">
            AM
            <span className="bg-money ring-bg absolute -right-0.5 -bottom-0.5 size-3 rounded-full ring-2" title="Verified by Persona" />
          </span>
        </div>
      </header>

      {/* Hero */}
      <section className="relative px-5 pt-5 pb-7">
        <div className="bg-money/20 pointer-events-none absolute -top-16 left-1/2 h-64 w-80 -translate-x-1/2 rounded-full blur-[80px]" />
        <div className="text-muted relative text-[15px] font-medium">Recovered this month</div>
        <div className="text-money relative mt-1 text-[68px] leading-[0.95] font-bold tracking-[-0.05em] tabular-nums">{usd(Math.round(count))}</div>
        <div className="relative mt-4 flex flex-wrap gap-2">
          <Pill tone="money">
            <CheckCircle2 /> {done.length} handled for you
          </Pill>
          {pending.length > 0 && (
            <Pill tone="warn">
              <BellRing /> {pending.length} need{pending.length === 1 ? 's' : ''} you
            </Pill>
          )}
        </div>
        {error && !feed && <div className="text-danger relative mt-4 text-[14px]">Can’t reach the backend: {error}</div>}
      </section>

      {/* Needs you */}
      <section className="mb-8">
        <SectionTitle
          right={
            pending.length > 0 && (
              <Link to="/inbox" className="text-muted flex items-center text-[14px] font-semibold">
                See all <ChevronRight className="size-4" />
              </Link>
            )
          }
        >
          Needs you
          {pending.length > 0 && <span className="bg-warn text-bg rounded-full px-2 py-px text-[13px] font-bold">{pending.length}</span>}
        </SectionTitle>
        {pending.length === 0 ? (
          <div className="bg-surface text-muted mx-5 flex items-center gap-3 rounded-[22px] p-4 text-[15px] ring-1 ring-white/6">
            <Sparkles className="text-money size-5 shrink-0" /> Nothing needs you. Snapback only asks when the choice is yours.
          </div>
        ) : (
          <>
            <div
              className="no-scrollbar flex snap-x snap-mandatory gap-3 overflow-x-auto scroll-smooth px-5 pb-1"
              onScroll={(e) => {
                const el = e.currentTarget
                const w = el.firstElementChild ? (el.firstElementChild as HTMLElement).offsetWidth + 12 : 1
                setSlide(Math.round(el.scrollLeft / w))
              }}
            >
              {pending.map((a) => (
                <DecisionCard
                  key={a.approval_id}
                  approval={a}
                  task={byId.get(a.task_id)!}
                  className={cn('shrink-0 snap-center', pending.length > 1 ? 'w-[88%]' : 'w-full')}
                />
              ))}
            </div>
            {pending.length > 1 && (
              <div className="mt-3 flex justify-center gap-1.5">
                {pending.map((a, i) => (
                  <motion.span key={a.approval_id} animate={{ width: i === slide ? 18 : 6, opacity: i === slide ? 1 : 0.35 }} className="bg-warn h-1.5 rounded-full" />
                ))}
              </div>
            )}
          </>
        )}
      </section>

      {/* Handled */}
      <section>
        <SectionTitle
          right={
            <Link to="/activity" className="text-muted flex items-center text-[14px] font-semibold">
              All activity <ChevronRight className="size-4" />
            </Link>
          }
        >
          Handled for you
        </SectionTitle>
        <div className="space-y-2.5 px-4">
          {handled.slice(0, 6).map((t) => (
            <FeedRow key={t.task_id} task={t} now={now} />
          ))}
          {feed && handled.length === 0 && <div className="text-muted px-1 text-[15px]">Nothing yet.</div>}
        </div>
      </section>
    </div>
  )
}
