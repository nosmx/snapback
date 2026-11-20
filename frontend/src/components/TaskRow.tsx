import { Loader2 } from 'lucide-react'
import { Row } from '@/components/shell'
import { STATUS_TEXT, Thumb, isActive } from '@/components/task-meta'
import { relTime, usd } from '@/lib/utils'
import type { Task } from '@/lib/types'

/** Compact list row: 48px thumbnail, title, item · time, and the outcome on the right. */
export function TaskRow({ task, now }: { task: Task; now: number }) {
  const done = task.status === 'done'
  const trailing =
    done && task.amount_usd ? (
      <span className="text-green text-[16px] font-semibold tabular-nums">{usd(task.amount_usd, { sign: true })}</span>
    ) : task.status === 'awaiting_user' ? (
      <span className="text-amber text-[14px] font-medium">Needs you</span>
    ) : isActive(task.status) ? (
      <span className="text-ink-2 flex items-center gap-1.5 text-[14px]">
        <Loader2 className="size-3.5 animate-spin" /> {STATUS_TEXT[task.status]}
      </span>
    ) : task.status === 'failed' ? (
      <span className="text-red text-[14px] font-medium">Failed</span>
    ) : null
  return (
    <Row
      to={`/tasks/${task.task_id}`}
      leading={<Thumb src={task.order?.image_url} />}
      title={task.title}
      subtitle={`${task.order?.item_name ?? ''} · ${relTime(task.updated_at ?? task.created_at, now)}`}
      trailing={trailing}
      chevron
    />
  )
}
