import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { CalendarClock, FlaskConical, RotateCcw, ShieldAlert, TrendingDown, type LucideIcon } from 'lucide-react'
import { Sheet, useToast } from '@/components/shell'
import { USE_MOCK, demoReset, demoTrigger } from '@/lib/api'
import { cn } from '@/lib/utils'

function Action({ icon: Icon, label, onClick, danger }: { icon: LucideIcon; label: string; onClick: () => void; danger?: boolean }) {
  return (
    <button
      onClick={onClick}
      className={cn('tap flex w-full items-center gap-3 rounded-[18px] px-4 py-4 text-left text-[16px] font-semibold ring-1', danger ? 'bg-danger/10 text-danger ring-danger/30' : 'bg-surface-2 ring-white/8')}
    >
      <Icon className="size-5" /> {label}
    </button>
  )
}

export function DemoControls({ onDone }: { onDone?: () => void }) {
  const navigate = useNavigate()
  const toast = useToast()
  const run = async (label: string, fn: () => Promise<void>, to: string | null = '/') => {
    try {
      await fn()
      toast(label)
      onDone?.()
      if (to) navigate(to)
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Demo action failed', 'error')
    }
  }
  return (
    <div className="space-y-2.5">
      <Action icon={RotateCcw} label="Reset demo data" onClick={() => run('Demo data reset', demoReset)} />
      <Action icon={TrendingDown} label="Trigger major price drop" onClick={() => run('Major price drop detected', () => demoTrigger('major_price_drop'))} />
      <Action icon={CalendarClock} label="Trigger return-window alert" onClick={() => run('Return-window alert created', () => demoTrigger('return_window'))} />
      <Action icon={ShieldAlert} danger label="Tamper with an audit entry" onClick={() => run('Edited a sealed audit entry', () => demoTrigger('tamper'), '/tasks/tsk_photo_headphones')} />
    </div>
  )
}

/** Toggle with the `d` key, or triple-tap the Snapback logo on a phone. */
export function DemoPanel() {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement
      if (el?.tagName === 'INPUT' || el?.tagName === 'TEXTAREA' || el?.isContentEditable) return
      if (e.key === 'd' && !e.metaKey && !e.ctrlKey && !e.altKey) setOpen((v) => !v)
      if (e.key === 'Escape') setOpen(false)
    }
    const onEvt = () => setOpen(true)
    window.addEventListener('keydown', onKey)
    window.addEventListener('snapback:demo', onEvt)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('snapback:demo', onEvt)
    }
  }, [])
  return (
    <Sheet open={open} onClose={() => setOpen(false)}>
      <div className="mb-4 flex items-center gap-2 text-[20px] font-bold tracking-tight">
        <FlaskConical className="text-money size-5" /> Demo controls
        <span className="text-faint rounded-full bg-white/6 px-2 py-0.5 text-[12px] font-semibold">{USE_MOCK ? 'mock' : 'live'}</span>
      </div>
      <DemoControls onDone={() => setOpen(false)} />
      <p className="text-faint mt-4 text-center text-[13px]">Press D or triple-tap the logo to toggle</p>
    </Sheet>
  )
}
