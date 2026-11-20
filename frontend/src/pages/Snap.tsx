import { useCallback, useRef, useState, type ChangeEvent } from 'react'
import { Link } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { Camera, Check, Loader2 } from 'lucide-react'
import { List, useToast } from '@/components/shell'
import { getAudit, getTask, uploadPhoto } from '@/lib/api'
import { usePoll } from '@/lib/hooks'
import { cn } from '@/lib/utils'
import type { AuditEntry } from '@/lib/types'

// Backend step names map onto stages by keyword, so small naming differences don't break the checklist.
const STAGES = [
  { key: 'identify', label: 'Identifying item', re: /identif|embed|photo_|ocr/ },
  { key: 'match', label: 'Finding your order', re: /match|extract/ },
  { key: 'policy', label: 'Checking store policy', re: /policy|senso|context|review/ },
  { key: 'decide', label: 'Deciding', re: /decision|decide|plan|rules/ },
  { key: 'file', label: 'Filing return', re: /return|claim/ },
  { key: 'order', label: 'Ordering replacement', re: /replace|order_placed|checkout|rank/ },
  { key: 'verify', label: 'Confirming', re: /verif|refund/ },
] as const
const stageOf = (step: string) => STAGES.findIndex((s) => s.re.test(step))

export default function Snap() {
  const toast = useToast()
  const [preview, setPreview] = useState<string | null>(null)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const libRef = useRef<HTMLInputElement>(null)
  const camRef = useRef<HTMLInputElement>(null)

  const { data: task } = usePoll(() => (taskId ? getTask(taskId) : Promise.resolve(null)), 700, [taskId])
  const { data: audit } = usePoll(() => (taskId ? getAudit(taskId) : Promise.resolve([] as AuditEntry[])), 700, [taskId])

  const start = useCallback(
    async (f: File) => {
      setPreview(URL.createObjectURL(f))
      setUploading(true)
      try {
        setTaskId(await uploadPhoto(f))
      } catch (e) {
        toast(e instanceof Error ? e.message : 'Upload failed')
        setPreview(null)
      } finally {
        setUploading(false)
      }
    },
    [toast],
  )
  const onFile = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (f) start(f)
    e.target.value = ''
  }
  const samplePhoto = async () => {
    const blob = await (await fetch('/demo/demo_broken_headphones.png')).blob()
    start(new File([blob], 'broken_headphones.png', { type: 'image/png' }))
  }
  const reset = () => {
    setPreview(null)
    setTaskId(null)
  }

  const inputs = (
    <>
      <input ref={camRef} type="file" accept="image/*" capture="environment" className="hidden" onChange={onFile} />
      <input ref={libRef} type="file" accept="image/*" className="hidden" onChange={onFile} />
    </>
  )

  if (!preview) {
    return (
      <div className="px-5 pt-8">
        <h1 className="text-[28px] leading-tight font-bold tracking-[-0.02em]">Take a photo of the item</h1>
        <p className="text-ink-2 mt-1.5 text-[16px]">Snapback finds your order and handles the rest.</p>
        <button
          onClick={() => camRef.current?.click()}
          className="tap bg-card mt-7 flex aspect-[4/5] w-full flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed"
        >
          <Camera className="text-ink-2 size-10" strokeWidth={1.4} />
          <span className="text-[17px] font-medium">Take photo</span>
        </button>
        <div className="mt-5 flex items-center justify-center gap-3 text-[15px]">
          <button onClick={() => libRef.current?.click()} className="text-ink">
            Choose from library
          </button>
          <span className="text-ink-3">·</span>
          <button onClick={samplePhoto} className="text-ink-2">
            Use sample photo
          </button>
        </div>
        {inputs}
      </div>
    )
  }

  const entries = audit ?? []
  const reached = entries.reduce((m, e) => Math.max(m, stageOf(e.step)), -1)
  const done = task?.status === 'done'
  const failed = task?.status === 'failed'
  const running = (!!taskId || uploading) && !done && !failed

  return (
    <div className="px-4 pt-4">
      <img src={preview} alt="Your photo" className="h-[200px] w-full rounded-2xl bg-white object-cover" />

      <List className="mt-4" inset={52}>
        {STAGES.map((s, i) => {
          const isDone = i <= reached
          const isActive = running && i === reached + 1
          const result = [...entries].reverse().find((e) => stageOf(e.step) === i)
          return (
            <div key={s.key} className="flex items-start gap-3 px-4 py-3">
              <span className="flex size-6 shrink-0 items-center justify-center pt-px">
                {isDone ? (
                  <motion.span initial={{ scale: 0.5, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ duration: 0.2 }} className="bg-green flex size-[22px] items-center justify-center rounded-full text-white">
                    <Check className="size-3.5" strokeWidth={3} />
                  </motion.span>
                ) : isActive ? (
                  <Loader2 className="text-ink-2 size-[18px] animate-spin" />
                ) : (
                  <span className="border-sep size-[22px] rounded-full border-2" />
                )}
              </span>
              <div className="min-w-0 flex-1">
                <div className={cn('text-[16px] leading-snug', !isDone && !isActive && 'text-ink-3')}>{s.label}</div>
                <AnimatePresence>
                  {isDone && (
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-ink-2 text-[14px] leading-snug">
                      {result ? result.decision : 'Not needed'}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            </div>
          )
        })}
      </List>

      {done && taskId && (
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2 }} className="mt-5">
          <p className="text-ink-2 mb-3 text-center text-[15px]">{task?.outcome}</p>
          <Link to={`/tasks/${taskId}`} className="tap bg-ink text-bg flex h-12 w-full items-center justify-center rounded-xl text-[17px] font-semibold">
            See what I did
          </Link>
          <button onClick={reset} className="text-ink-2 mt-2 h-11 w-full text-[15px]">
            Snap another
          </button>
        </motion.div>
      )}
      {failed && (
        <p className="text-red mt-4 text-center text-[15px]">
          Something went wrong.{' '}
          <Link className="underline" to={`/tasks/${taskId}`}>
            See what happened
          </Link>
        </p>
      )}
      {inputs}
    </div>
  )
}
