// One bottom sheet for the whole decision: choose → Persona verification → live progress → done.
// The provider sits above the routes so the flow survives the card unmounting once answered.
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { AlertTriangle, ArrowRight, Check, CheckCircle2, Fingerprint, Loader2, Sparkles } from 'lucide-react'
import { Sheet, useCountUp, useToast } from '@/components/shell'
import { Pill, ProductImage, TRIGGER, stepMeta } from '@/components/task-meta'
import { answerApproval, getAudit, getLastMockInquiry, getTask } from '@/lib/api'
import { usePoll } from '@/lib/hooks'
import { cn, fmtDate, sleep, storeName, usd } from '@/lib/utils'
import type { Approval, ApprovalOption, Task } from '@/lib/types'

type Phase = 'choose' | 'verifying' | 'verified' | 'running' | 'done' | 'error'

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
  awaiting_user: 'Starting…',
  detected: 'Planning…',
  planned: 'Planning…',
  executing: 'Working on it…',
  verifying: 'Verifying with outside evidence…',
  awaiting_refund: 'Waiting for the refund to post…',
}

const fade = { initial: { opacity: 0, y: 12 }, animate: { opacity: 1, y: 0 }, exit: { opacity: 0, y: -8 }, transition: { duration: 0.22 } }

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
  const live = open && phase !== 'choose'
  const { data: task } = usePoll(() => (live && taskId ? getTask(taskId) : Promise.resolve(null)), 700, [taskId, live])
  const { data: entries } = usePoll(() => (live && taskId ? getAudit(taskId) : Promise.resolve([])), 700, [taskId, live])

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
        if (kind === 'snooze') toast('We’ll remind you tomorrow', 'info')
        else if (opt.id === 'keep') toast('Keeping it · alerts off')
        else toast('Ignored · we won’t ask again')
      } catch (e) {
        toast(e instanceof Error ? e.message : 'Something went wrong', 'error')
      }
      return
    }
    setOption(opt)
    setPhase('verifying')
    try {
      const before = await getAudit(ctx.task.task_id)
      setBase(before.length)
      await sleep(1600) // Persona embedded check — simulated in the UI
      const res = await answerApproval(ctx.approval.approval_id, opt.id)
      setInquiry(res.persona_inquiry_id ?? getLastMockInquiry())
      setPhase('verified')
      await sleep(1200)
      setPhase('running')
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
      setPhase('error')
    }
  }

  useEffect(() => {
    if (phase === 'running' && (task?.status === 'done' || task?.status === 'failed')) setPhase('done')
  }, [phase, task?.status])

  const fresh = (entries ?? []).slice(base)

  return (
    <Ctx.Provider value={openDecision}>
      {children}
      <Sheet open={open} onClose={() => setOpen(false)} dismissible={phase !== 'verifying' && phase !== 'verified'}>
        {ctx && (
          <AnimatePresence mode="wait" initial={false}>
            {phase === 'choose' && (
              <motion.div key="choose" {...fade}>
                <ChooseStep approval={ctx.approval} task={ctx.task} onChoose={choose} />
              </motion.div>
            )}
            {phase === 'verifying' && (
              <motion.div key="verifying" {...fade}>
                <PersonaStep verified={false} option={option} inquiry="" />
              </motion.div>
            )}
            {phase === 'verified' && (
              <motion.div key="verified" {...fade}>
                <PersonaStep verified option={option} inquiry={inquiry} />
              </motion.div>
            )}
            {(phase === 'running' || phase === 'done') && (
              <motion.div key="run" {...fade}>
                <RunStep
                  done={phase === 'done'}
                  option={option}
                  task={task ?? ctx.task}
                  entries={fresh}
                  onClose={() => setOpen(false)}
                  onAudit={() => {
                    setOpen(false)
                    navigate(`/tasks/${taskId}`)
                  }}
                />
              </motion.div>
            )}
            {phase === 'error' && (
              <motion.div key="error" {...fade} className="flex flex-col items-center gap-3 py-8 text-center">
                <AlertTriangle className="text-danger size-12" />
                <div className="text-xl font-bold">Couldn’t complete that</div>
                <div className="text-muted">{err}</div>
                <button className="tap bg-surface-3 mt-2 rounded-2xl px-5 py-3 font-semibold" onClick={() => option && choose(option)}>
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

function ChooseStep({ approval, task, onChoose }: { approval: Approval; task: Task; onChoose: (o: ApprovalOption) => void }) {
  const o = task.order
  const pm = approval.price_math
  const dl = approval.deadline
  const exec = approval.options.filter((x) => actionOf(x) === 'execute')
  const rest = approval.options.filter((x) => actionOf(x) !== 'execute')
  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3.5">
        <ProductImage src={o?.image_url} className="size-[72px] rounded-[20px]" />
        <div className="min-w-0">
          <Pill tone="warn">{TRIGGER[task.trigger_type]?.label ?? 'Decision'}</Pill>
          <div className="mt-1.5 truncate text-[17px] font-semibold">{o?.item_name ?? task.title}</div>
          <div className="text-muted truncate text-[14px]">
            {o ? `${storeName(o.store)} · ${o.order_id}` : task.order_id}
          </div>
        </div>
      </div>

      <h2 className="text-[24px] leading-[1.2] font-bold tracking-[-0.02em]">{approval.question}</h2>

      {pm && (
        <div className="bg-bg/60 flex items-end justify-between rounded-[22px] p-4 ring-1 ring-white/6">
          <div>
            <div className="text-muted text-[13px] font-medium">You paid</div>
            <div className="text-muted text-[22px] font-semibold tabular-nums line-through decoration-2">{usd(pm.paid_usd)}</div>
          </div>
          <ArrowRight className="text-faint mb-2 size-5" />
          <div>
            <div className="text-muted text-[13px] font-medium">Now</div>
            <div className="text-[34px] leading-none font-bold tracking-tight tabular-nums">{usd(pm.current_usd)}</div>
          </div>
          <Pill tone="warn" className="mb-1 text-[15px]">−{Math.round(pm.drop_pct)}%</Pill>
        </div>
      )}
      {dl && (
        <div className="bg-bg/60 flex items-center justify-between rounded-[22px] p-4 ring-1 ring-white/6">
          <div>
            <div className="text-muted text-[13px] font-medium">Return by</div>
            <div className="text-[30px] leading-tight font-bold tracking-tight">{fmtDate(dl.return_by)}</div>
          </div>
          <div className="text-right">
            <Pill tone="warn" className="text-[15px]">{dl.days_left} days left</Pill>
            <div className="text-muted mt-1 text-[14px] tabular-nums">paid {usd(dl.price_usd)}</div>
          </div>
        </div>
      )}

      <div className="space-y-3">
        {exec.map((opt) => {
          const rec = approval.recommended === opt.id
          return (
            <button
              key={opt.id}
              onClick={() => onChoose(opt)}
              className={cn(
                'tap relative flex min-h-[76px] w-full items-center gap-3 rounded-[22px] p-4 text-left ring-1',
                rec ? 'bg-money/10 ring-money/60 ring-2' : 'bg-surface-2 ring-white/8',
              )}
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-[18px] font-bold">{opt.label}</span>
                  {rec && (
                    <span className="bg-money text-money-ink inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[12px] font-bold">
                      <Sparkles className="size-3" /> Recommended
                    </span>
                  )}
                </div>
                <div className="text-muted mt-0.5 text-[14px] leading-snug">{opt.detail}</div>
              </div>
              {opt.net_savings_usd ? (
                <span className="text-money text-[22px] font-bold tracking-tight tabular-nums">{usd(opt.net_savings_usd, { sign: true })}</span>
              ) : null}
            </button>
          )
        })}
      </div>

      {rest.length > 0 && (
        <div className={cn('grid gap-2', rest.length > 1 ? 'grid-cols-2' : 'grid-cols-1')}>
          {rest.map((opt) => (
            <button key={opt.id} onClick={() => onChoose(opt)} className="tap bg-surface-2/60 text-muted rounded-2xl px-3 py-3.5 text-[15px] font-semibold ring-1 ring-white/6">
              {opt.label}
            </button>
          ))}
        </div>
      )}

      <div className="text-faint flex items-center justify-center gap-1.5 pb-1 text-[13px]">
        <Fingerprint className="size-4" /> One tap, verified with Persona. Everything after runs on its own.
      </div>
    </div>
  )
}

function PersonaStep({ verified, option, inquiry }: { verified: boolean; option: ApprovalOption | null; inquiry: string }) {
  return (
    <div className="flex flex-col items-center gap-5 py-6 text-center">
      <div className="relative flex size-[132px] items-center justify-center">
        <svg viewBox="0 0 132 132" className="absolute inset-0 -rotate-90">
          <circle cx="66" cy="66" r="60" fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="6" />
          <motion.circle
            cx="66"
            cy="66"
            r="60"
            fill="none"
            stroke="var(--color-money)"
            strokeWidth="6"
            strokeLinecap="round"
            initial={{ pathLength: verified ? 1 : 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: verified ? 0 : 1.5, ease: 'easeInOut' }}
          />
        </svg>
        <AnimatePresence mode="wait">
          {verified ? (
            <motion.span
              key="ok"
              initial={{ scale: 0.4, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ type: 'spring', stiffness: 400, damping: 15 }}
              className="bg-money text-money-ink flex size-[96px] items-center justify-center rounded-full"
            >
              <Check className="size-12" strokeWidth={3} />
            </motion.span>
          ) : (
            <motion.span key="fp" animate={{ opacity: [0.5, 1, 0.5] }} transition={{ repeat: Infinity, duration: 1.2 }}>
              <Fingerprint className="text-money size-16" strokeWidth={1.6} />
            </motion.span>
          )}
        </AnimatePresence>
      </div>
      <div>
        <div className={cn('text-[26px] font-bold tracking-tight', verified && 'text-money')}>
          {verified ? 'Verified by Persona ✓' : 'Verifying it’s you…'}
        </div>
        <div className="text-muted mt-1.5 text-[15px]">
          {verified ? (
            <>
              Approved <b className="text-ink">{option?.label}</b>
              {option?.net_savings_usd ? ` · ${usd(option.net_savings_usd, { sign: true })}` : ''}
            </>
          ) : (
            'A verified human must approve before any money moves.'
          )}
        </div>
      </div>
      {verified && inquiry ? (
        <code className="bg-bg text-muted rounded-lg px-2.5 py-1 font-mono text-[12px]">{inquiry}</code>
      ) : (
        <div className="text-faint text-[12px] font-bold tracking-[0.18em]">SECURED BY PERSONA</div>
      )}
    </div>
  )
}

function RunStep({
  done,
  option,
  task,
  entries,
  onClose,
  onAudit,
}: {
  done: boolean
  option: ApprovalOption | null
  task: Task
  entries: { entry_id: number; step: string; decision: string; verified: boolean | null }[]
  onClose: () => void
  onAudit: () => void
}) {
  const amount = task.amount_usd ?? option?.net_savings_usd ?? 0
  const count = useCountUp(done ? amount : 0)
  return (
    <div className="space-y-5">
      <div>
        <div className="flex items-center gap-2 text-[24px] font-bold tracking-tight">
          {done ? <CheckCircle2 className="text-money size-7" /> : <Loader2 className="text-money size-6 animate-spin" />}
          {done ? 'Done' : 'Snapback is on it'}
        </div>
        <div className="text-muted mt-1 text-[15px]">
          {option?.label} · {task.order?.item_name ?? task.title} · no more taps needed
        </div>
      </div>

      {done && (
        <motion.div initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} className="bg-money/10 ring-money/30 rounded-[22px] p-5 ring-1">
          <div className="text-money text-[48px] leading-none font-bold tracking-[-0.04em] tabular-nums">{usd(Math.round(count * 100) / 100, { sign: true })}</div>
          <div className="mt-2 text-[16px] font-medium">{task.outcome ?? 'Completed and verified.'}</div>
        </motion.div>
      )}

      <ol className="relative space-y-4 pl-1">
        {entries.map((e) => {
          const m = stepMeta(e.step)
          return (
            <motion.li key={e.entry_id} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} className="flex items-start gap-3">
              <span className={cn('mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full', e.verified ? 'bg-money text-money-ink' : 'bg-money/15 text-money')}>
                <Check className="size-3.5" strokeWidth={3} />
              </span>
              <div className="min-w-0">
                <div className="text-faint text-[12px] font-bold tracking-wider uppercase">{m.label}</div>
                <div className="text-[15px] font-medium">{e.decision}</div>
              </div>
            </motion.li>
          )
        })}
        {!done && (
          <li className="text-money flex items-center gap-3 text-[15px] font-medium">
            <Loader2 className="size-6 animate-spin" /> {WORKING[task.status] ?? 'Working…'}
          </li>
        )}
      </ol>

      <div className="grid grid-cols-2 gap-2 pt-1">
        <button onClick={onClose} className="tap bg-surface-2 rounded-2xl py-3.5 text-[16px] font-semibold ring-1 ring-white/8">
          {done ? 'Close' : 'Run in background'}
        </button>
        <button onClick={onAudit} className="tap bg-money text-money-ink rounded-2xl py-3.5 text-[16px] font-bold">
          View audit trail
        </button>
      </div>
    </div>
  )
}
