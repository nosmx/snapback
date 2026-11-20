import { useCallback, useEffect, useRef, useState, type ChangeEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { Check, Images, Loader2, RotateCcw, ScanSearch, ShieldCheck, Sparkles, Video, VideoOff, X } from 'lucide-react'
import { useCountUp, useToast } from '@/components/shell'
import { Pill } from '@/components/task-meta'
import { getAudit, getTask, uploadPhoto } from '@/lib/api'
import { usePoll } from '@/lib/hooks'
import { cn, storeName, usd } from '@/lib/utils'
import type { AuditEntry } from '@/lib/types'

// Backend step names map onto stages by keyword, so small naming differences don't break the stepper.
const STAGES = [
  { key: 'identify', label: 'Identifying item', re: /identif|embed|photo_|ocr/ },
  { key: 'match', label: 'Matching your order', re: /match|extract/ },
  { key: 'policy', label: 'Checking store policy', re: /policy|senso|context|review/ },
  { key: 'decide', label: 'Deciding', re: /decision|decide|plan|rules/ },
  { key: 'file', label: 'Filing the return', re: /return|claim/ },
  { key: 'order', label: 'Ordering a replacement', re: /replace|order_placed|checkout|rank/ },
  { key: 'verify', label: 'Verifying', re: /verif|refund/ },
] as const
const stageOf = (step: string) => STAGES.findIndex((s) => s.re.test(step))

function Corners() {
  const base = 'absolute size-9 border-money'
  return (
    <>
      <span className={cn(base, 'top-5 left-5 rounded-tl-[14px] border-t-[3px] border-l-[3px]')} />
      <span className={cn(base, 'top-5 right-5 rounded-tr-[14px] border-t-[3px] border-r-[3px]')} />
      <span className={cn(base, 'bottom-5 left-5 rounded-bl-[14px] border-b-[3px] border-l-[3px]')} />
      <span className={cn(base, 'right-5 bottom-5 rounded-br-[14px] border-r-[3px] border-b-[3px]')} />
    </>
  )
}

function SideButton({ icon: Icon, label, onClick }: { icon: typeof Images; label: string; onClick: () => void }) {
  return (
    <button onClick={onClick} className="tap flex w-[72px] flex-col items-center gap-1.5">
      <span className="flex size-[52px] items-center justify-center rounded-full bg-white/10 ring-1 ring-white/10">
        <Icon className="size-[22px]" />
      </span>
      <span className="text-muted text-[12px] font-semibold">{label}</span>
    </button>
  )
}

export default function Snap() {
  const navigate = useNavigate()
  const toast = useToast()
  const [preview, setPreview] = useState<string | null>(null)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [stream, setStream] = useState<MediaStream | null>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const libRef = useRef<HTMLInputElement>(null)
  const camRef = useRef<HTMLInputElement>(null)

  const { data: task } = usePoll(() => (taskId ? getTask(taskId) : Promise.resolve(null)), 700, [taskId])
  const { data: audit } = usePoll(() => (taskId ? getAudit(taskId) : Promise.resolve([] as AuditEntry[])), 700, [taskId])

  useEffect(() => {
    if (videoRef.current && stream) videoRef.current.srcObject = stream
    return () => stream?.getTracks().forEach((t) => t.stop())
  }, [stream])

  const startCamera = async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      toast('Live camera needs HTTPS — opening the camera app', 'info')
      camRef.current?.click()
      return
    }
    try {
      setStream(await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false }))
    } catch {
      toast('Camera unavailable', 'error')
    }
  }

  const start = useCallback(
    async (f: File) => {
      setStream(null)
      setPreview(URL.createObjectURL(f))
      setUploading(true)
      try {
        setTaskId(await uploadPhoto(f))
      } catch (e) {
        toast(e instanceof Error ? e.message : 'Upload failed', 'error')
        setPreview(null)
      } finally {
        setUploading(false)
      }
    },
    [toast],
  )

  const shutter = () => {
    const v = videoRef.current
    if (stream && v && v.videoWidth) {
      const c = document.createElement('canvas')
      c.width = v.videoWidth
      c.height = v.videoHeight
      c.getContext('2d')!.drawImage(v, 0, 0)
      c.toBlob((b) => b && start(new File([b], 'snap.jpg', { type: 'image/jpeg' })), 'image/jpeg', 0.9)
    } else camRef.current?.click()
  }

  const demoPhoto = async () => {
    const blob = await (await fetch('/demo/demo_broken_headphones.png')).blob()
    start(new File([blob], 'broken_headphones.png', { type: 'image/png' }))
  }

  const reset = () => {
    setPreview(null)
    setTaskId(null)
  }

  const onFile = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (f) start(f)
    e.target.value = ''
  }

  const entries = audit ?? []
  const reached = entries.reduce((m, e) => Math.max(m, stageOf(e.step)), -1)
  const done = task?.status === 'done'
  const failed = task?.status === 'failed'
  const running = (!!taskId || uploading) && !done && !failed
  const matched = entries.find((e) => stageOf(e.step) === 1)
  const confidence = matched?.decision.match(/(\d+)%/)?.[1]
  const count = useCountUp(done ? task?.amount_usd ?? 0 : 0)
  const o = task?.order

  const inputs = (
    <>
      <input ref={libRef} type="file" accept="image/*" className="hidden" onChange={onFile} />
      <input ref={camRef} type="file" accept="image/*" capture="environment" className="hidden" onChange={onFile} />
    </>
  )

  // ---------- viewfinder ----------
  if (!preview) {
    return (
      <div className="flex h-full flex-col bg-black">
        <div className="flex items-center justify-between px-4 py-3">
          <button onClick={() => navigate('/')} aria-label="Close" className="tap flex size-10 items-center justify-center rounded-full bg-white/10">
            <X className="size-5" />
          </button>
          <span className="text-[16px] font-semibold">Snap a broken item</span>
          <button onClick={stream ? () => setStream(null) : startCamera} aria-label="Live camera" className={cn('tap flex size-10 items-center justify-center rounded-full', stream ? 'bg-money text-money-ink' : 'bg-white/10')}>
            {stream ? <VideoOff className="size-5" /> : <Video className="size-5" />}
          </button>
        </div>

        <div className="relative mx-4 flex-1 overflow-hidden rounded-[32px] bg-[#07080b] ring-1 ring-white/8">
          {stream ? (
            <video ref={videoRef} autoPlay playsInline muted className="absolute inset-0 h-full w-full object-cover" />
          ) : (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 px-10 text-center">
              <ScanSearch className="size-12 text-white/25" strokeWidth={1.5} />
              <div className="text-[20px] font-semibold tracking-tight">Point at what’s broken</div>
              <div className="text-muted text-[14px] leading-snug">Snapback finds the order, checks the store’s policy, files the return and buys a replacement.</div>
            </div>
          )}
          <Corners />
          <motion.div
            className="via-money/70 absolute inset-x-8 h-[2px] bg-gradient-to-r from-transparent to-transparent"
            animate={{ top: ['12%', '88%', '12%'] }}
            transition={{ repeat: Infinity, duration: 3.2, ease: 'easeInOut' }}
          />
        </div>

        <div className="flex items-center justify-around px-6 pt-6" style={{ paddingBottom: 'calc(var(--bottom-inset) + 22px)' }}>
          <SideButton icon={Images} label="Library" onClick={() => libRef.current?.click()} />
          <button onClick={shutter} aria-label="Take photo" className="tap flex size-[80px] items-center justify-center rounded-full ring-[4px] ring-white">
            <span className="size-[64px] rounded-full bg-white" />
          </button>
          <SideButton icon={Sparkles} label="Demo photo" onClick={demoPhoto} />
        </div>
        {inputs}
      </div>
    )
  }

  // ---------- processing ----------
  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center justify-between px-4 py-3">
        <button onClick={() => navigate('/')} aria-label="Close" className="tap bg-surface flex size-10 items-center justify-center rounded-full ring-1 ring-white/8">
          <X className="size-5" />
        </button>
        <span className="flex items-center gap-2 text-[16px] font-semibold">
          {running && <Loader2 className="text-money size-4 animate-spin" />}
          {done ? 'All done' : running ? 'Working on it' : 'Snap'}
        </span>
        <span className="size-10" />
      </div>

      <div className="no-scrollbar flex-1 overflow-y-auto px-4 pb-6">
        <div className="relative overflow-hidden rounded-[28px] ring-1 ring-white/10">
          <img src={preview} alt="Your photo" className="h-[220px] w-full bg-white object-cover" />
          {running && !matched && (
            <motion.div
              className="via-money/45 absolute inset-x-0 h-20 bg-gradient-to-b from-transparent to-transparent"
              animate={{ top: ['-25%', '100%'] }}
              transition={{ repeat: Infinity, duration: 1.5, ease: 'easeInOut' }}
            />
          )}
          <AnimatePresence>
            {matched && o && (
              <motion.div
                initial={{ y: 24, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                className="absolute inset-x-3 bottom-3 flex items-center gap-3 rounded-[18px] bg-black/75 p-2.5 ring-1 ring-white/10 backdrop-blur-md"
              >
                <img src={o.image_url} alt="" className="size-11 rounded-xl bg-white object-cover" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[14px] font-semibold">{o.item_name}</div>
                  <div className="text-muted truncate text-[12px]">
                    {storeName(o.store)} · {o.order_id} · {usd(o.price)}
                  </div>
                </div>
                {confidence && <Pill tone="money">{confidence}% match</Pill>}
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        <ol className="mt-6">
          {STAGES.map((s, i) => {
            const isDone = i <= reached
            const isActive = running && i === reached + 1
            const result = [...entries].reverse().find((e) => stageOf(e.step) === i)
            return (
              <li key={s.key} className="relative flex gap-4 pb-5">
                <span className="absolute top-9 bottom-0 left-[15px] w-[2px] overflow-hidden rounded-full bg-white/8">
                  <motion.span className="bg-money block w-full" initial={false} animate={{ height: isDone ? '100%' : '0%' }} transition={{ duration: 0.45, ease: 'easeOut' }} />
                </span>
                <span
                  className={cn(
                    'relative z-10 flex size-8 shrink-0 items-center justify-center rounded-full transition-colors',
                    isDone ? 'bg-money text-money-ink' : isActive ? 'bg-money/15 text-money ring-money/60 ring-2' : 'bg-surface ring-1 ring-white/10',
                  )}
                >
                  {isDone ? (
                    <motion.span initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ type: 'spring', stiffness: 500, damping: 18 }}>
                      <Check className="size-4" strokeWidth={3.2} />
                    </motion.span>
                  ) : isActive ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <span className="size-1.5 rounded-full bg-white/25" />
                  )}
                  {isActive && <motion.span className="ring-money/40 absolute inset-0 rounded-full ring-2" animate={{ scale: [1, 1.5], opacity: [0.8, 0] }} transition={{ repeat: Infinity, duration: 1.2 }} />}
                </span>
                <div className="min-w-0 pt-1">
                  <div className={cn('text-[17px] leading-tight font-semibold', !isDone && !isActive && 'text-faint')}>{s.label}</div>
                  <AnimatePresence>
                    {isDone && (
                      <motion.div initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} className="text-muted mt-1 text-[14px] leading-snug">
                        {result ? result.decision : 'Not needed for this case'}
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              </li>
            )
          })}
          <li className="flex gap-4">
            <span className={cn('flex size-8 shrink-0 items-center justify-center rounded-full', done ? 'bg-money text-money-ink' : 'bg-surface ring-1 ring-white/10')}>
              {done ? <ShieldCheck className="size-4" strokeWidth={2.6} /> : <span className="size-1.5 rounded-full bg-white/25" />}
            </span>
            <div className={cn('pt-1 text-[17px] font-semibold', done ? 'text-money' : 'text-faint')}>Done</div>
          </li>
        </ol>

        {failed && (
          <div className="bg-danger/12 text-danger ring-danger/40 mt-5 rounded-2xl p-4 ring-1">
            Something went wrong.{' '}
            <Link className="font-semibold underline" to={`/tasks/${taskId}`}>
              See what happened
            </Link>
          </div>
        )}
        {task?.status === 'awaiting_user' && (
          <div className="bg-warn/12 text-warn ring-warn/40 mt-5 rounded-2xl p-4 ring-1">
            Snapback needs one answer from you.{' '}
            <Link className="font-semibold underline" to={`/tasks/${taskId}`}>
              Open the task
            </Link>
          </div>
        )}
      </div>

      <AnimatePresence>
        {done && taskId && (
          <motion.div
            initial={{ y: '100%' }}
            animate={{ y: 0 }}
            transition={{ type: 'spring', damping: 30, stiffness: 300 }}
            className="bg-surface shrink-0 rounded-t-[28px] px-5 pt-5 ring-1 ring-white/8"
            style={{ paddingBottom: 'calc(var(--bottom-inset) + 16px)' }}
          >
            <div className="text-money text-[46px] leading-none font-bold tracking-[-0.04em] tabular-nums">{usd(Math.round(count * 100) / 100, { sign: true })}</div>
            <div className="mt-1.5 text-[15px] font-medium">{task?.outcome ?? 'Completed and verified.'}</div>
            <div className="mt-4 grid grid-cols-[1fr_auto] gap-2">
              <Link to={`/tasks/${taskId}`} className="tap bg-money text-money-ink rounded-2xl py-4 text-center text-[16px] font-bold">
                View audit trail
              </Link>
              <button onClick={reset} aria-label="Snap another" className="tap bg-surface-2 flex items-center justify-center rounded-2xl px-5 ring-1 ring-white/8">
                <RotateCcw className="size-5" />
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
      {inputs}
    </div>
  )
}
