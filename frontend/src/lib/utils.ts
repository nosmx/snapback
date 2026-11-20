import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function usd(n: number | null | undefined, opts: { sign?: boolean; cents?: boolean } = {}) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  const cents = opts.cents ?? !Number.isInteger(n)
  const s = Math.abs(n).toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: cents ? 2 : 0,
    maximumFractionDigits: cents ? 2 : 0,
  })
  if (opts.sign) return (n < 0 ? '−' : '+') + s
  return n < 0 ? '−' + s : s
}

export function relTime(iso: string, now = Date.now()) {
  const t = new Date(iso).getTime()
  const s = Math.round((now - t) / 1000)
  if (s < 45) return 'just now'
  const m = Math.round(s / 60)
  if (m < 60) return `${m} min ago`
  const h = Math.round(m / 60)
  if (h < 24) return `${h}h ago`
  const d = Math.round(h / 24)
  return d === 1 ? 'yesterday' : `${d} days ago`
}

export function fmtDate(iso: string, withTime = false) {
  const d = new Date(iso)
  return d.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    ...(withTime ? { hour: 'numeric', minute: '2-digit' } : {}),
  })
}

export function fmtTime(iso: string) {
  return new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', second: '2-digit' })
}

export function fmtMs(ms: number) {
  if (ms < 1000) return `${Math.round(ms)} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`
  return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`
}

export function shortHash(h: string | null | undefined) {
  if (!h) return '—'
  return `${h.slice(0, 8)}…${h.slice(-4)}`
}

export const STORE_NAMES: Record<string, string> = {
  'northwind-audio': 'Northwind Audio',
  'juniper-home': 'Juniper Home',
  'kestrel-outdoors': 'Kestrel Outdoors',
}

export function storeName(id: string) {
  return STORE_NAMES[id] ?? id
}

export const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))
