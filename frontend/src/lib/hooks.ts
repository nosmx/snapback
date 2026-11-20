import { useCallback, useEffect, useRef, useState } from 'react'
import { CHANGED_EVENT } from './api'

/** Poll an async loader every `ms`, and immediately whenever the app signals a data change. */
export function usePoll<T>(fn: () => Promise<T>, ms: number, deps: unknown[] = []) {
  const [data, setData] = useState<T | undefined>(undefined)
  const [error, setError] = useState<string | null>(null)
  const fnRef = useRef(fn)
  useEffect(() => {
    fnRef.current = fn
  })

  const tick = useCallback(async () => {
    try {
      const d = await fnRef.current()
      setData(d)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  useEffect(() => {
    let alive = true
    const run = () => alive && tick()
    run()
    const id = window.setInterval(run, ms)
    window.addEventListener(CHANGED_EVENT, run)
    return () => {
      alive = false
      window.clearInterval(id)
      window.removeEventListener(CHANGED_EVENT, run)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ms, tick, ...deps])

  return { data, error, refresh: tick }
}

/** Re-render every `ms` so relative times ("2 min ago") stay fresh. */
export function useNow(ms = 30_000) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), ms)
    return () => window.clearInterval(id)
  }, [ms])
  return now
}
