import { ArrowRight, CalendarClock, ChevronRight, TrendingDown } from 'lucide-react'
import { useDecision, actionOf } from '@/components/DecisionSheet'
import { Pill, ProductImage } from '@/components/task-meta'
import { cn, fmtDate, relTime, storeName, usd } from '@/lib/utils'
import type { Approval, Task } from '@/lib/types'

/** Compact "needs you" card. Tapping opens the decision bottom sheet. */
export function DecisionCard({ approval, task, className }: { approval: Approval; task: Task; className?: string }) {
  const open = useDecision()
  const o = task.order
  const pm = approval.price_math
  const dl = approval.deadline
  const best = Math.max(0, ...approval.options.filter((x) => actionOf(x) === 'execute').map((x) => x.net_savings_usd ?? 0))
  return (
    <button
      onClick={() => open(approval, task)}
      className={cn('tap bg-surface flex flex-col gap-4 rounded-[26px] p-4 text-left ring-1 ring-warn/25', className)}
    >
      <div className="flex w-full items-center justify-between">
        <Pill tone="warn">
          {task.trigger_type === 'return_window' ? <CalendarClock /> : <TrendingDown />}
          {pm ? `Price dropped ${Math.round(pm.drop_pct)}%` : dl ? `${dl.days_left} days to return` : 'Needs you'}
        </Pill>
        <span className="text-faint text-[13px]">{relTime(approval.asked_at ?? task.created_at)}</span>
      </div>

      <div className="flex w-full items-center gap-3.5">
        <ProductImage src={o?.image_url} className="size-[84px] rounded-[20px]" />
        <div className="min-w-0 flex-1">
          <div className="text-muted truncate text-[13px]">{o ? storeName(o.store) : ''}</div>
          <div className="truncate text-[18px] leading-tight font-semibold">{o?.item_name ?? task.title}</div>
          {pm && (
            <div className="mt-1.5 flex items-baseline gap-2">
              <span className="text-faint text-[16px] font-semibold tabular-nums line-through">{usd(pm.paid_usd)}</span>
              <ArrowRight className="text-faint size-4 self-center" />
              <span className="text-[26px] leading-none font-bold tracking-tight tabular-nums">{usd(pm.current_usd)}</span>
            </div>
          )}
          {dl && (
            <div className="mt-1.5 text-[22px] leading-none font-bold tracking-tight">
              by {fmtDate(dl.return_by)} <span className="text-faint text-[15px] font-semibold">· {usd(dl.price_usd)}</span>
            </div>
          )}
        </div>
      </div>

      <div className="flex w-full items-center justify-between border-t border-white/6 pt-3">
        {best > 0 ? (
          <span className="text-[15px] font-medium">
            <span className="text-muted">Up to </span>
            <span className="text-money text-[18px] font-bold tabular-nums">{usd(best, { sign: true })}</span>
          </span>
        ) : (
          <span className="text-muted text-[15px]">Your call</span>
        )}
        <span className="bg-warn text-bg inline-flex items-center gap-1 rounded-full py-1.5 pr-2.5 pl-3.5 text-[14px] font-bold">
          Decide <ChevronRight className="size-4" />
        </span>
      </div>
    </button>
  )
}
