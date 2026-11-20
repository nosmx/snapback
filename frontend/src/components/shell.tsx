// App chrome: desktop phone frame, status bar, bottom tab bar, bottom sheets, toasts.
// Sheets and toasts portal into an overlay layer INSIDE the device, so they stay in the phone frame on desktop.
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { NavLink, useLocation } from 'react-router-dom'
import { AnimatePresence, animate, motion, useDragControls } from 'framer-motion'
import { Activity, BatteryFull, Bell, Camera, CheckCircle2, House, Info, ShieldCheck, SignalHigh, Wifi, XCircle } from 'lucide-react'
import { getApprovals } from '@/lib/api'
import { usePoll } from '@/lib/hooks'
import { cn } from '@/lib/utils'

// ---------- overlay ----------
const OverlayCtx = createContext<HTMLElement | null>(null)
// eslint-disable-next-line react-refresh/only-export-components
export const useOverlay = () => useContext(OverlayCtx)

const FRAME_H = 844 + 22

export function PhoneFrame({ children }: { children: ReactNode }) {
  const [overlay, setOverlay] = useState<HTMLDivElement | null>(null)
  const [zoom, setZoom] = useState(1)
  useEffect(() => {
    // Shrink the frame to fit short projector screens (e.g. 1280×720).
    const fit = () => setZoom(window.innerWidth >= 768 ? Math.min(1, (window.innerHeight - 32) / FRAME_H) : 1)
    fit()
    window.addEventListener('resize', fit)
    return () => window.removeEventListener('resize', fit)
  }, [])
  return (
    <div className="stage h-[100dvh] overflow-hidden md:flex md:items-center md:justify-center">
      <div
        style={{ zoom }}
        className="h-full md:h-auto md:rounded-[62px] md:bg-[#1b1e27] md:p-[11px] md:shadow-[0_50px_140px_-30px_rgba(0,0,0,0.9),inset_0_0_0_1px_rgba(255,255,255,0.09)]"
      >
        <div className="bg-bg relative h-full w-full overflow-hidden md:h-[844px] md:w-[390px] md:rounded-[52px]">
          <OverlayCtx.Provider value={overlay}>{children}</OverlayCtx.Provider>
          <div ref={setOverlay} className="pointer-events-none absolute inset-0 z-50" />
          <div className="pointer-events-none absolute bottom-[7px] left-1/2 z-[60] hidden h-[5px] w-[134px] -translate-x-1/2 rounded-full bg-white/55 md:block" />
        </div>
      </div>
    </div>
  )
}

export function StatusBar() {
  const [t, setT] = useState(() => new Date())
  useEffect(() => {
    const id = setInterval(() => setT(new Date()), 15_000)
    return () => clearInterval(id)
  }, [])
  return (
    <div className="bg-bg absolute inset-x-0 top-0 z-40 hidden h-[50px] items-center justify-between px-8 pt-1 text-[15px] font-semibold md:flex">
      <span className="tabular-nums">{t.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }).replace(/\s?[AP]M/, '')}</span>
      <span className="absolute top-[11px] left-1/2 h-[32px] w-[118px] -translate-x-1/2 rounded-full bg-black" />
      <span className="flex items-center gap-1.5">
        <SignalHigh className="size-4" strokeWidth={2.6} />
        <Wifi className="size-4" strokeWidth={2.6} />
        <BatteryFull className="size-5" strokeWidth={2} />
      </span>
    </div>
  )
}

// ---------- tab bar ----------
export function TabBar() {
  const { pathname } = useLocation()
  const { data: approvals } = usePoll(getApprovals, 3000)
  const pending = (approvals ?? []).filter((a) => !a.choice).length
  const tab = (to: string, label: string, Icon: typeof House, badge?: number) => {
    const active = to === '/' ? pathname === '/' : pathname.startsWith(to)
    return (
      <NavLink to={to} className={cn('tap relative flex flex-col items-center gap-1 py-2', active ? 'text-ink' : 'text-faint')}>
        {active && <motion.span layoutId="tab-dot" className="bg-money absolute -top-px h-[3px] w-6 rounded-full" />}
        <span className="relative">
          <Icon className="size-[23px]" strokeWidth={active ? 2.4 : 2} />
          {!!badge && (
            <span className="bg-warn text-bg absolute -top-1.5 -right-2.5 flex h-[18px] min-w-[18px] items-center justify-center rounded-full px-1 text-[11px] font-bold">
              {badge}
            </span>
          )}
        </span>
        <span className="text-[11px] font-semibold">{label}</span>
      </NavLink>
    )
  }
  return (
    <nav
      className="absolute inset-x-0 bottom-0 z-40 grid grid-cols-5 items-start border-t bg-[#0d1016]/90 px-2 backdrop-blur-xl"
      style={{ height: 'var(--tabbar-h)', paddingBottom: 'var(--bottom-inset)' }}
    >
      {tab('/', 'Home', House)}
      {tab('/inbox', 'Needs you', Bell, pending)}
      <div className="flex justify-center">
        <NavLink
          to="/snap"
          aria-label="Snap a broken item"
          className="tap bg-money text-money-ink ring-bg -mt-6 flex size-[62px] items-center justify-center rounded-full shadow-[0_10px_30px_-6px_rgba(61,220,132,0.65)] ring-[6px]"
        >
          <Camera className="size-7" strokeWidth={2.3} />
        </NavLink>
      </div>
      {tab('/activity', 'Activity', Activity)}
      {tab('/rules', 'Rules', ShieldCheck)}
    </nav>
  )
}

// ---------- bottom sheet ----------
export function Sheet({
  open,
  onClose,
  dismissible = true,
  children,
}: {
  open: boolean
  onClose: () => void
  dismissible?: boolean
  children: ReactNode
}) {
  const overlay = useOverlay()
  const controls = useDragControls()
  if (!overlay) return null
  return createPortal(
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            key="backdrop"
            className="pointer-events-auto absolute inset-0 bg-black/65 backdrop-blur-[2px]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => dismissible && onClose()}
          />
          <motion.div
            key="panel"
            role="dialog"
            aria-modal="true"
            className="bg-surface pointer-events-auto absolute inset-x-0 bottom-0 flex max-h-[92%] flex-col rounded-t-[30px] border-t border-white/10 shadow-[0_-20px_60px_rgba(0,0,0,0.5)]"
            initial={{ y: '100%' }}
            animate={{ y: 0 }}
            exit={{ y: '100%' }}
            transition={{ type: 'spring', damping: 34, stiffness: 340 }}
            drag={dismissible ? 'y' : false}
            dragListener={false}
            dragControls={controls}
            dragConstraints={{ top: 0, bottom: 0 }}
            dragElastic={{ top: 0, bottom: 0.7 }}
            onDragEnd={(_, info) => {
              if (info.offset.y > 100 || info.velocity.y > 600) onClose()
            }}
          >
            <div className="flex shrink-0 cursor-grab touch-none justify-center pt-3 pb-3" onPointerDown={(e) => dismissible && controls.start(e)}>
              <div className="h-[5px] w-10 rounded-full bg-white/20" />
            </div>
            <div className="no-scrollbar overflow-y-auto px-5" style={{ paddingBottom: 'calc(var(--bottom-inset) + 20px)' }}>
              {children}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>,
    overlay,
  )
}

// ---------- toasts ----------
type Tone = 'success' | 'info' | 'error'
const ToastCtx = createContext<(msg: string, tone?: Tone) => void>(() => {})
// eslint-disable-next-line react-refresh/only-export-components
export const useToast = () => useContext(ToastCtx)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<{ id: number; msg: string; tone: Tone }[]>([])
  const overlay = useOverlay()
  const push = useCallback((msg: string, tone: Tone = 'success') => {
    const id = Date.now() + Math.random()
    setItems((x) => [...x, { id, msg, tone }])
    setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), 2800)
  }, [])
  return (
    <ToastCtx.Provider value={push}>
      {children}
      {overlay &&
        createPortal(
          <div className="absolute inset-x-0 z-[70] flex flex-col items-center gap-2 px-4" style={{ top: 'calc(var(--top-inset) + 8px)' }}>
            <AnimatePresence>
              {items.map((t) => (
                <motion.div
                  key={t.id}
                  layout
                  initial={{ opacity: 0, y: -18, scale: 0.94 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: -12, scale: 0.96 }}
                  className="bg-surface-3/95 pointer-events-auto flex max-w-full items-center gap-2 rounded-full px-4 py-2.5 text-[15px] font-medium shadow-2xl ring-1 ring-white/12 backdrop-blur"
                >
                  {t.tone === 'success' && <CheckCircle2 className="text-money size-5 shrink-0" />}
                  {t.tone === 'info' && <Info className="text-info size-5 shrink-0" />}
                  {t.tone === 'error' && <XCircle className="text-danger size-5 shrink-0" />}
                  <span className="truncate">{t.msg}</span>
                </motion.div>
              ))}
            </AnimatePresence>
          </div>,
          overlay,
        )}
    </ToastCtx.Provider>
  )
}

// ---------- misc ----------
/** Animated number for money heroes. */
// eslint-disable-next-line react-refresh/only-export-components
export function useCountUp(value: number, duration = 1) {
  const [display, setDisplay] = useState(0)
  const from = useRef(0)
  useEffect(() => {
    const c = animate(from.current, value, { duration, ease: [0.16, 1, 0.3, 1], onUpdate: (v) => setDisplay(v) })
    from.current = value
    return () => c.stop()
  }, [value, duration])
  return display
}

export function LogoMark({ className }: { className?: string }) {
  return (
    <span className={cn('bg-money text-money-ink flex items-center justify-center rounded-[11px]', className ?? 'size-9')}>
      <svg viewBox="0 0 24 24" className="size-[62%]" fill="none" stroke="currentColor" strokeWidth={2.8} strokeLinecap="round" strokeLinejoin="round">
        <path d="M9 14 4 9l5-5" />
        <path d="M4 9h10.5a5.5 5.5 0 0 1 5.5 5.5a5.5 5.5 0 0 1-5.5 5.5H11" />
      </svg>
    </span>
  )
}

export function PageHeader({ title, subtitle, left, right }: { title: string; subtitle?: string; left?: ReactNode; right?: ReactNode }) {
  return (
    <header className="bg-bg/85 sticky top-0 z-30 flex items-center gap-3 px-5 pt-3 pb-3 backdrop-blur-xl">
      {left}
      <div className="min-w-0 flex-1">
        <h1 className="truncate text-[28px] leading-tight font-bold tracking-[-0.03em]">{title}</h1>
        {subtitle && <p className="text-muted truncate text-[14px]">{subtitle}</p>}
      </div>
      {right}
    </header>
  )
}

export function SectionTitle({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between px-5">
      <h2 className="flex items-center gap-2 text-[20px] font-bold tracking-[-0.02em]">{children}</h2>
      {right}
    </div>
  )
}
