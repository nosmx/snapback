import { useDecision } from '@/components/DecisionSheet'
import { List, NavBar, Row } from '@/components/shell'
import { Thumb, decisionLine } from '@/components/task-meta'
import { getApprovals, getFeed } from '@/lib/api'
import { usePoll } from '@/lib/hooks'

/** Pushed from Home → "See all" when more than two decisions are waiting. */
export default function Inbox() {
  const openDecision = useDecision()
  const { data: feed } = usePoll(getFeed, 1500)
  const { data: approvals } = usePoll(getApprovals, 1500)
  const byId = new Map((feed ?? []).map((t) => [t.task_id, t]))
  const pending = (approvals ?? []).filter((a) => !a.choice && byId.has(a.task_id))

  return (
    <div>
      <NavBar title="Needs you" back />
      <div className="px-4">
        {pending.length > 0 ? (
          <List inset={76}>
            {pending.map((a) => {
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
        ) : (
          approvals && <p className="text-ink-2 py-20 text-center text-[16px]">You’re all caught up.</p>
        )}
      </div>
    </div>
  )
}
