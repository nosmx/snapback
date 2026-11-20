import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { List, Row, Sheet, useToast } from '@/components/shell'
import { USE_MOCK, demoReset, demoTrigger } from '@/lib/api'

export function DemoControls({ onDone }: { onDone?: () => void }) {
  const navigate = useNavigate()
  const toast = useToast()
  const run = async (label: string, fn: () => Promise<void>, to: string = '/') => {
    try {
      await fn()
      toast(label)
      onDone?.()
      navigate(to)
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Demo action failed')
    }
  }
  return (
    <List className="bg-bg">
      <Row onClick={() => run('Demo data reset', demoReset)} title="Reset demo data" chevron />
      <Row onClick={() => run('Major price drop detected', () => demoTrigger('major_price_drop'))} title="Trigger major price drop" chevron />
      <Row onClick={() => run('Return-window alert created', () => demoTrigger('return_window'))} title="Trigger return-window alert" chevron />
      <Row onClick={() => run('Edited a sealed record', () => demoTrigger('tamper'), '/tasks/tsk_photo_headphones')} title={<span className="text-red">Tamper with a record</span>} chevron />
    </List>
  )
}

/** Hidden demo controls: press D, or triple-tap the "Snapback" title on a phone. */
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
      <div className="mb-4 flex items-baseline justify-between">
        <h2 className="text-[20px] font-semibold">Demo controls</h2>
        <span className="text-ink-3 text-[13px]">{USE_MOCK ? 'mock data' : 'live backend'}</span>
      </div>
      <DemoControls onDone={() => setOpen(false)} />
    </Sheet>
  )
}
