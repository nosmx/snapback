import { motion } from 'framer-motion'
import { PartyPopper } from 'lucide-react'
import { DecisionCard } from '@/components/DecisionCard'
import { PageHeader } from '@/components/shell'
import { getApprovals, getFeed } from '@/lib/api'
import { usePoll } from '@/lib/hooks'

export default function Inbox() {
  const { data: feed } = usePoll(getFeed, 1500)
  const { data: approvals } = usePoll(getApprovals, 1500)
  const byId = new Map((feed ?? []).map((t) => [t.task_id, t]))
  const pending = (approvals ?? []).filter((a) => !a.choice && byId.has(a.task_id))

  return (
    <div>
      <PageHeader title="Needs you" subtitle="Only choices that depend on you. Everything else runs on its own." />
      <div className="space-y-3 px-4 pt-2">
        {pending.map((a, i) => (
          <motion.div key={a.approval_id} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
            <DecisionCard approval={a} task={byId.get(a.task_id)!} className="w-full" />
          </motion.div>
        ))}
        {approvals && pending.length === 0 && (
          <div className="flex flex-col items-center gap-3 px-6 py-20 text-center">
            <span className="bg-money/15 text-money flex size-16 items-center justify-center rounded-full">
              <PartyPopper className="size-8" />
            </span>
            <div className="text-[22px] font-bold tracking-tight">You’re all caught up</div>
            <div className="text-muted text-[15px]">Snapback will ask here when a decision depends on you or goes beyond your rules.</div>
          </div>
        )}
      </div>
    </div>
  )
}
