// Decision sheet: options → Persona confirmation → one progress row that updates in place → Done.
// The provider sits above the screens so the flow survives the row unmounting once answered.
import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { Check, Loader2, ScanFace } from 'lucide-react'
import { Sheet, useToast } from '@/components/shell'
import { Thumb, stepMeta } from '@/components/task-meta'
import { answerApproval, getAudit, getLastMockInquiry, getTask } from '@/lib/api'
import { usePoll } from '@/lib/hooks'
import { cn, fmtDate, sleep, storeName, usd } from '@/lib/utils'
import type { Approval, ApprovalOption, Task } from '@/lib/types'

type Phase = 'choose' | 'confirming' | 'verified' | 'progress' | 'error'

const Ctx = createContext<(a: Approval, t: Task) => void>(() => {})
// eslint-disable-next-line react-refresh/only-export-components
export const useDecision = () => useContext(Ctx)

// eslint-disable-next-line react-refresh/only-export-components
export function actionOf(o: ApprovalOption): 'execute' | 'dismiss' | 'snooze' {
  if (o.action) return o.action
  if (['ignore', 'keep', 'dismiss'].includes(o.id)) return 'dismiss'
  if (o.id.startsWith('remind') || o.id === 'snooze') return 'snooze'
  return 'execute'
}

const WORKING: Record<string, string> = {
  awaiting_user: 'Starting',
  executing: 'Working on it',
  verifying: 'Confirming the result',
  awaiting_refund: 'Waiting for the refund',
}

const fade = { initial: { opacity: 0 }, animate: { opacity: 1 }, exit: { opacity: 0 }, transition: { duration: 0.2 } }

export function DecisionSheetProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  const toast = useToast()
  const [open, setOpen] = useState(false)
  const [ctx, setCtx] = useState<{ approval: Approval; task: Task } | null>(null)
  const [phase, setPhase] = useState<Phase>('choose')
  const [option, setOption] = useState<ApprovalOption | null>(null)
  const [inquiry, setInquiry] = useState('')
  const [base, setBase] = useState(0)
  const [err, setErr] = useState('')

  const taskId = ctx?.task.task_id ?? ''
  const live = open && phase === 'progress'
  const { data: task } = usePoll(() => (live ? getTask(taskId) : Promise.resolve(null)), 700, [taskId, live])
  const { data: entries } = usePoll(() => (live ? getAudit(taskId) : Promise.resolve([])), 700, [taskId, live])

  const openDecision = useCallback((approval: Approval, t: Task) => {
    setCtx({ approval, task: t })
    setPhase('choose')
    setOption(null)
    setErr('')
    setOpen(true)
  }, [])

  const choose = async (opt: ApprovalOption) => {
    if (!ctx) return
    const kind = actionOf(opt)
    if (kind !== 'execute') {
      try {
        await answerApproval(ctx.approval.approval_id, opt.id)
        setOpen(false)
        toast(kind === 'snooze' ? 'We’ll remind you tomorrow' : opt.id === 'keep' ? 'Keeping it. Alerts are off.' : 'Ignored')
      } catch (e) {
        toast(e instanceof Error ? e.message : 'Something went wrong')
      }
      return
    }
    setOption(opt)
    setPhase('confirming')
    try {
      const before = await getAudit(ctx.task.task_id)
      setBase(before.length)
      await sleep(1500) // Persona confirmation, simulated in the UI
      const res = await answerApproval(ctx.approval.approval_id, opt.id)
      setInquiry(res.persona_inquiry_id ?? getLastMockInquiry())
      setPhase('verified')
      await sleep(900)
      setPhase('progress')
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
      setPhase('error')
    }
  }

  const fresh = (entries ?? []).slice(base)
  const done = phase === 'progress' && task?.status === 'done'

  return (
    <Ctx.Provider value={openDecision}>
      {children}
      <Sheet open={open} onClose={() => setOpen(false)} dismissible={phase !== 'confirming' && phase !== 'verified'}>
        {ctx && (
          <AnimatePresence mode="wait" initial={false}>
            {phase === 'choose' && (
              <motion.div key="choose" {...fade}>
                <Choose approval={ctx.approval} task={ctx.task} onChoose={choose} />
              </motion.div>
            )}
            {(phase === 'confirming' || phase === 'verified') && (
              <motion.div key="persona" {...fade}>
                <Persona verified={phase === 'verified'} inquiry={inquiry} />
              </motion.div>
            )}
            {phase === 'progress' && (
              <motion.div key="progress" {...fade}>
                <Progress
                  task={task ?? ctx.task}
                  option={option}
                  last={fresh[fresh.length - 1]}
                  done={done}
                  onClose={() => setOpen(false)}
                  onSee={() => {
                    setOpen(false)
                    navigate(`/tasks/${taskId}`)
                  }}
                />
              </motion.div>
            )}
            {phase === 'error' && (
              <motion.div key="error" {...fade} className="py-8 text-center">
                <div className="text-red text-[17px] font-semibold">Couldn’t complete that</div>
                <div className="text-ink-2 mt-1 text-[15px]">{err}</div>
                <button className="tap bg-fill mt-5 h-12 w-full rounded-xl text-[17px] font-semibold" onClick={() => option && choose(option)}>
                  Try again
                </button>
              </motion.div>
            )}
          </AnimatePresence>
        )}
      </Sheet>
    </Ctx.Provider>
  )
}

function Choose({ approval, task, onChoose }: { approval: Approval; task: Task; onChoose: (o: ApprovalOption) => void }) {
  const o = task.order
  const pm = approval.price_math
  const dl = approval.deadline
  const facts = pm
    ? `Paid ${usd(pm.paid_usd)} · Now ${usd(pm.current_usd)}`
    : dl
      ? `Return by ${fmtDate(dl.return_by)} · ${dl.days_left} days left`
      : (approval.facts ?? null)
  return (
    <div>
      <div className="flex items-start gap-3.5">
        <Thumb src={o?.image_url} className="size-14 rounded-xl" />
        <div className="min-w-0 pt-0.5">
          <div className="text-ink-2 text-[13px]">{o ? storeName(o.store) : ''}</div>
          <h2 className="text-[19px] leading-snug font-semibold tracking-[-0.01em]">{approval.question}</h2>
        </div>
      </div>
      {facts && <div className="text-ink-2 mt-3 text-[15px] tabular-nums">{facts}</div>}

      <div className="mt-5 space-y-2.5">
        {approval.options.map((opt) => {
          const rec = approval.recommended === opt.id
          const save = opt.net_savings_usd ? usd(opt.net_savings_usd, { sign: true }) : null
          return (
            <button
              key={opt.id}
              onClick={() => onChoose(opt)}
              className={cn('tap flex w-full items-center gap-3 rounded-xl px-4 py-3 text-left', rec ? 'bg-green text-white' : 'bg-card border')}
            >
              <div className="min-w-0 flex-1">
                {rec && <div className="text-[12px] font-medium text-white/80">Recommended</div>}
                <div className="text-[17px] font-semibold">{opt.label}</div>
                <div className={cn('text-[13px] leading-snug', rec ? 'text-white/85' : 'text-ink-2')}>{opt.detail}</div>
              </div>
              {save && <div className={cn('text-[17px] font-semibold tabular-nums', !rec && 'text-green')}>{save}</div>}
            </button>
          )
        })}
      </div>
      <p className="text-ink-3 mt-4 text-center text-[13px]">Approving asks Persona to confirm it’s you.</p>
    </div>
  )
}

/** Minimal Persona step, shared with the Rules editor. */
export function Persona({ verified, inquiry }: { verified: boolean; inquiry: string }) {
  return (
    <div className="flex flex-col items-center py-8 text-center">
      <div className="text-ink-2 flex items-center gap-1.5 text-[13px] font-semibold">
        <span className="bg-ink text-bg flex size-5 items-center justify-center rounded-[5px]">
          <ScanFace className="size-3.5" />
        </span>
        Persona
      </div>
      <div className="mt-6 flex size-16 items-center justify-center">
        <AnimatePresence mode="wait">
          {verified ? (
            <motion.span key="ok" initial={{ scale: 0.6, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ duration: 0.2 }} className="bg-green flex size-16 items-center justify-center rounded-full text-white">
              <Check className="size-8" strokeWidth={2.5} />
            </motion.span>
          ) : (
            <motion.span key="spin" exit={{ opacity: 0 }}>
              <Loader2 className="text-ink-3 size-10 animate-spin" strokeWidth={1.5} />
            </motion.span>
          )}
        </AnimatePresence>
      </div>
      <div className="mt-4 text-[19px] font-semibold">{verified ? 'Verified' : 'Confirming it’s you…'}</div>
      <div className="text-ink-3 mt-1 h-5 font-mono text-[12px]">{verified ? inquiry : ''}</div>
    </div>
  )
}

function Progress({
  task,
  option,
  last,
  done,
  onClose,
  onSee,
}: {
  task: Task
  option: ApprovalOption | null
  last?: { step: string; decision: string }
  done: boolean
  onClose: () => void
  onSee: () => void
}) {
  const amount = task.amount_usd ?? option?.net_savings_usd ?? null
  const title = done ? 'Done' : last ? stepMeta(last.step).label : WORKING[task.status] ?? 'Working on it'
  const sub = done ? task.outcome ?? 'Completed and confirmed.' : last?.decision ?? 'Starting…'
  return (
    <div className="pt-2">
      <div className="text-ink-2 text-[13px]">
        {option?.label} · {task.order?.item_name}
      </div>
      {done && amount ? (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-green mt-1 text-[40px] leading-tight font-bold tracking-[-0.02em] tabular-nums">
          {usd(amount, { sign: true })}
        </motion.div>
      ) : (
        <div className="mt-1 text-[22px] font-semibold tracking-[-0.01em]">Working on it</div>
      )}

      <div className="bg-bg mt-4 flex items-center gap-3 rounded-xl px-4 py-3.5">
        <span className="flex size-7 shrink-0 items-center justify-center">
          {done ? (
            <span className="bg-green flex size-7 items-center justify-center rounded-full text-white">
              <Check className="size-4" strokeWidth={2.5} />
            </span>
          ) : (
            <Loader2 className="text-ink-2 size-5 animate-spin" />
          )}
        </span>
        <div className="min-w-0 flex-1">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div key={title + sub} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: 0.18 }}>
              <div className="text-[16px] font-semibold">{title}</div>
              <div className="text-ink-2 truncate text-[14px]">{sub}</div>
            </motion.div>
          </AnimatePresence>
        </div>
      </div>

      <div className="mt-5 space-y-2">
        <button onClick={onSee} className="tap bg-ink text-bg h-12 w-full rounded-xl text-[17px] font-semibold">
          See what I did
        </button>
        <button onClick={onClose} className="tap text-ink-2 h-11 w-full text-[16px]">
          {done ? 'Close' : 'Keep working in background'}
        </button>
      </div>
    </div>
  )
}
