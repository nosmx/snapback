import { Link } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { ProductImage, StatusBadge, TRIGGER } from '@/components/task-meta'
import { cn, relTime, storeName, usd } from '@/lib/utils'
import type { Task } from '@/lib/types'

export function FeedRow({ task, now }: { task: Task; now: number }) {
  const o = task.order
  const t = TRIGGER[task.trigger_type] ?? TRIGGER.chat
  const Icon = t.icon
  const done = task.status === 'done'
  const working = ['detected', 'planned', 'executing', 'verifying', 'awaiting_refund'].includes(task.status)
  return (
    <Link to={`/tasks/${task.task_id}`} className="tap bg-surface flex items-center gap-3.5 rounded-[24px] p-3 pr-4 ring-1 ring-white/6 active:bg-surface-2">
      <div className="relative shrink-0">
        <ProductImage src={o?.image_url} className="size-[64px] rounded-[18px]" />
        <span className={cn('ring-surface absolute -right-1.5 -bottom-1.5 flex size-7 items-center justify-center rounded-full ring-[3px] backdrop-blur', t.tone, 'bg-surface-2')}>
          <Icon className="size-3.5" strokeWidth={2.5} />
        </span>
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[16px] leading-tight font-semibold">{task.title}</div>
        <div className="text-muted mt-0.5 truncate text-[14px]">
          {o?.item_name}
          {o ? ` · ${storeName(o.store)}` : ''}
        </div>
        <div className="text-faint mt-0.5 text-[13px]">{relTime(task.updated_at ?? task.created_at, now)}</div>
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1">
        {task.amount_usd && done ? (
          <span className="text-money text-[19px] font-bold tracking-tight tabular-nums">{usd(task.amount_usd, { sign: true })}</span>
        ) : working ? (
          <Loader2 className="text-info size-5 animate-spin" />
        ) : null}
        {!done && <StatusBadge status={task.status} className="px-2 py-0.5 text-[12px]" />}
      </div>
    </Link>
  )
}
