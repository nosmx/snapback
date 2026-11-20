// App chrome: desktop iPhone frame, status bar, tab bar, bottom sheets, toasts, iOS-style lists.
// Sheets and toasts portal into an overlay layer INSIDE the device, so they stay in the frame on desktop.
import { Children, Fragment, createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { AnimatePresence, animate, motion, useDragControls } from 'framer-motion'
import { BatteryFull, Camera, ChevronLeft, ChevronRight, Clock, House, Shield, SignalHigh, Wifi } from 'lucide-react'
import { cn } from '@/lib/utils'

// ---------- overlay ----------
const OverlayCtx = createContext<HTMLElement | null>(null)
// eslint-disable-next-line react-refresh/only-export-components
export const useOverlay = () => useContext(OverlayCtx)

const FRAME_H = 844 + 20

export function PhoneFrame({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  const [overlay, setOverlay] = useState<HTMLDivElement | null>(null)
  const [zoom, setZoom] = useState(1)
  useEffect(() => {
    // Shrink the frame to fit short projector screens (e.g. 1280×720).
    const fit = () => setZoom(window.innerWidth >= 768 ? Math.min(1, (window.innerHeight - 40) / FRAME_H) : 1)
    fit()
    window.addEventListener('resize', fit)
    return () => window.removeEventListener('resize', fit)
  }, [])
  return (
    <div className={cn('h-[100dvh] overflow-hidden md:bg-stage md:flex md:items-center md:justify-center', aside ? 'md:gap-12 min-[1400px]:gap-16' : 'md:gap-20')}>
      {/* Tagline on the left; with the activity panel open it needs ≥1400px to fit. */}
      <div className={cn('hidden w-[260px] shrink-0', aside ? 'min-[1400px]:block' : 'lg:block')}>
        <div className="text-[40px] leading-none font-bold tracking-[-0.03em]">Snapback</div>
        <p className="text-ink-2 mt-3 text-[19px] leading-snug">Your post-purchase autopilot.</p>
      </div>
      <div style={{ zoom }} className="h-full md:h-auto md:rounded-[58px] md:bg-[#1c1c1e] md:p-[10px] md:shadow-[0_30px_80px_-20px_rgba(0,0,0,0.35)]">
        <div className="bg-bg relative h-full w-full overflow-hidden md:h-[844px] md:w-[390px] md:rounded-[48px]">
          <OverlayCtx.Provider value={overlay}>{children}</OverlayCtx.Provider>
          <div ref={setOverlay} className="pointer-events-none absolute inset-0 z-50" />
          <div className="bg-ink pointer-events-none absolute bottom-[8px] left-1/2 z-[60] hidden h-[5px] w-[134px] -translate-x-1/2 rounded-full md:block" />
        </div>
      </div>
      {aside && (
        <div className="w-[360px] shrink-0" style={{ height: FRAME_H * zoom }}>
          {aside}
        </div>
      )}
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
    <div className="bg-bg absolute inset-x-0 top-0 z-40 hidden h-[47px] items-center justify-between px-8 pt-1 text-[16px] font-semibold md:flex">
      <span className="w-14 tabular-nums">{t.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }).replace(/\s?[AP]M/, '')}</span>
      <span className="absolute top-[11px] left-1/2 h-[31px] w-[112px] -translate-x-1/2 rounded-full bg-black" />
      <span className="flex items-center gap-1.5">
        <SignalHigh className="size-4" strokeWidth={2.6} />
        <Wifi className="size-4" strokeWidth={2.6} />
        <BatteryFull className="size-5" strokeWidth={1.8} />
      </span>
    </div>
  )
}

// ---------- tab bar ----------
export type TabKey = 'home' | 'snap' | 'activity' | 'rules'
export const TABS: { key: TabKey; to: string; label: string; icon: typeof House }[] = [
  { key: 'home', to: '/', label: 'Home', icon: House },
  { key: 'snap', to: '/snap', label: 'Snap', icon: Camera },
  { key: 'activity', to: '/activity', label: 'Activity', icon: Clock },
  { key: 'rules', to: '/rules', label: 'Rules', icon: Shield },
]

export function TabBar({ active }: { active: TabKey }) {
  return (
    <nav
      className="bg-card/90 absolute inset-x-0 bottom-0 z-40 grid grid-cols-4 border-t backdrop-blur-xl"
      style={{ height: 'var(--tabbar-h)', paddingBottom: 'var(--bottom-inset)' }}
    >
      {TABS.map(({ key, to, label, icon: Icon }) => {
        const on = key === active
        return (
          <Link key={key} to={to} className={cn('tap flex flex-col items-center justify-center gap-[3px]', on ? 'text-ink' : 'text-ink-3')}>
            {key === 'snap' ? (
              <span className={cn('flex h-[26px] w-[44px] items-center justify-center rounded-full', on ? 'bg-ink text-bg' : 'bg-fill text-ink')}>
                <Icon className="size-[17px]" strokeWidth={2} />
              </span>
            ) : (
              <Icon className="size-[23px]" strokeWidth={on ? 2.1 : 1.6} />
            )}
            <span className="text-[10.5px] font-medium">{label}</span>
          </Link>
        )
      })}
    </nav>
  )
}

// ---------- scroll containers & large titles ----------
const ScrollCtx = createContext<HTMLElement | null>(null)

export function Scroller({ children, className }: { children: ReactNode; className?: string }) {
  const [el, setEl] = useState<HTMLDivElement | null>(null)
  return (
    <ScrollCtx.Provider value={el}>
      <div
        ref={setEl}
        className={cn('no-scrollbar absolute inset-x-0 bottom-0 overflow-x-hidden overflow-y-auto overscroll-contain', className)}
        style={{ top: 'var(--top-inset)', paddingBottom: 'calc(var(--tabbar-h) + 28px)' }}
      >
        {children}
      </div>
    </ScrollCtx.Provider>
  )
}

function useScrolled(threshold: number) {
  const el = useContext(ScrollCtx)
  const [on, setOn] = useState(false)
  useEffect(() => {
    if (!el) return
    const onScroll = () => setOn(el.scrollTop > threshold)
    onScroll()
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [el, threshold])
  return on
}

/** iOS navigation bar: large title that collapses into a small centered title on scroll. */
export function NavBar({ title, large = true, back, right, onTitleTap }: { title: string; large?: boolean; back?: string | boolean; right?: ReactNode; onTitleTap?: () => void }) {
  const navigate = useNavigate()
  const location = useLocation()
  const scrolled = useScrolled(large ? 38 : 4)
  const compact = !large || scrolled
  return (
    <>
      <div className={cn('sticky top-0 z-30 flex h-11 items-center border-b px-2 transition-colors duration-200', compact ? 'bg-bg/85 border-sep backdrop-blur-xl' : 'border-transparent')}>
        <div className="flex w-24 items-center">
          {back && (
            <button onClick={() => (location.key === 'default' ? navigate('/') : navigate(-1))} className="tap text-ink flex items-center text-[17px]">
              <ChevronLeft className="size-7" strokeWidth={2} />
              <span className="-ml-0.5">{typeof back === 'string' ? back : 'Back'}</span>
            </button>
          )}
        </div>
        <div className={cn('min-w-0 flex-1 truncate text-center text-[17px] font-semibold transition-opacity duration-200', compact ? 'opacity-100' : 'opacity-0')}>{title}</div>
        <div className="flex w-24 justify-end pr-2">{right}</div>
      </div>
      {large && (
        <h1 onClick={onTitleTap} className="px-5 pt-0.5 pb-3 text-[34px] leading-[1.1] font-bold tracking-[-0.025em] select-none">
          {title}
        </h1>
      )}
    </>
  )
}

// ---------- grouped inset lists ----------
export function Section({ title, action, children, className }: { title?: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cn('px-4', className)}>
      {(title || action) && (
        <div className="mb-2 flex items-baseline justify-between px-1">
          {title && <h2 className="text-[20px] font-semibold tracking-[-0.01em]">{title}</h2>}
          {action}
        </div>
      )}
      {children}
    </section>
  )
}

export function SeeAll({ to }: { to: string }) {
  return (
    <Link to={to} className="text-ink-2 text-[15px]">
      See all
    </Link>
  )
}

/** White rounded card with hairline separators between children (inset past the leading thumbnail). */
export function List({ children, inset = 16, className }: { children: ReactNode; inset?: number; className?: string }) {
  const items = Children.toArray(children).filter(Boolean)
  return (
    <div className={cn('bg-card overflow-hidden rounded-2xl', className)}>
      {items.map((c, i) => (
        <Fragment key={i}>
          {c}
          {i < items.length - 1 && <div className="bg-sep h-px" style={{ marginLeft: inset }} />}
        </Fragment>
      ))}
    </div>
  )
}

export function Row({
  leading,
  title,
  subtitle,
  trailing,
  chevron,
  to,
  onClick,
  className,
}: {
  leading?: ReactNode
  title: ReactNode
  subtitle?: ReactNode
  trailing?: ReactNode
  chevron?: boolean
  to?: string
  onClick?: () => void
  className?: string
}) {
  const body = (
    <>
      {leading}
      <div className="min-w-0 flex-1">
        <div className="truncate text-[16px] leading-snug">{title}</div>
        {subtitle && <div className="text-ink-2 truncate text-[14px] leading-snug">{subtitle}</div>}
      </div>
      {trailing}
      {chevron && <ChevronRight className="text-ink-3 -mr-1 size-5 shrink-0" strokeWidth={1.8} />}
    </>
  )
  const cls = cn('flex min-h-[60px] w-full items-center gap-3 px-4 py-2.5 text-left', (to || onClick) && 'press', className)
  if (to)
    return (
      <Link to={to} className={cls}>
        {body}
      </Link>
    )
  if (onClick)
    return (
      <button onClick={onClick} className={cls}>
        {body}
      </button>
    )
  return <div className={cls}>{body}</div>
}

// ---------- bottom sheet ----------
export function Sheet({ open, onClose, dismissible = true, children }: { open: boolean; onClose: () => void; dismissible?: boolean; children: ReactNode }) {
  const overlay = useOverlay()
  const controls = useDragControls()
  if (!overlay) return null
  return createPortal(
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            key="backdrop"
            className="pointer-events-auto absolute inset-0 bg-black/30"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={() => dismissible && onClose()}
          />
          <motion.div
            key="panel"
            role="dialog"
            aria-modal="true"
            className="bg-card pointer-events-auto absolute inset-x-0 bottom-0 flex max-h-[90%] flex-col rounded-t-[16px] shadow-[0_-10px_40px_rgba(0,0,0,0.15)]"
            initial={{ y: '100%' }}
            animate={{ y: 0 }}
            exit={{ y: '100%' }}
            transition={{ type: 'tween', duration: 0.3, ease: [0.32, 0.72, 0, 1] }}
            drag={dismissible ? 'y' : false}
            dragListener={false}
            dragControls={controls}
            dragConstraints={{ top: 0, bottom: 0 }}
            dragElastic={{ top: 0, bottom: 0.7 }}
            onDragEnd={(_, info) => {
              if (info.offset.y > 90 || info.velocity.y > 600) onClose()
            }}
          >
            <div className="flex shrink-0 cursor-grab touch-none justify-center pt-2 pb-3" onPointerDown={(e) => dismissible && controls.start(e)}>
              <div className="bg-sep h-[5px] w-9 rounded-full" />
            </div>
            <div className="no-scrollbar overflow-y-auto px-5" style={{ paddingBottom: 'calc(var(--bottom-inset) + 16px)' }}>
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
const ToastCtx = createContext<(msg: string) => void>(() => {})
// eslint-disable-next-line react-refresh/only-export-components
export const useToast = () => useContext(ToastCtx)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<{ id: number; msg: string }[]>([])
  const overlay = useOverlay()
  const push = useCallback((msg: string) => {
    const id = Date.now() + Math.random()
    setItems((x) => [...x, { id, msg }])
    setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), 2400)
  }, [])
  return (
    <ToastCtx.Provider value={push}>
      {children}
      {overlay &&
        createPortal(
          <div className="absolute inset-x-0 z-[70] flex flex-col items-center gap-2 px-6" style={{ top: 'calc(var(--top-inset) + 6px)' }}>
            <AnimatePresence>
              {items.map((t) => (
                <motion.div
                  key={t.id}
                  initial={{ opacity: 0, y: -12 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  transition={{ duration: 0.2 }}
                  className="bg-ink text-bg pointer-events-auto max-w-full truncate rounded-full px-4 py-2 text-[14px] font-medium shadow-lg"
                >
                  {t.msg}
                </motion.div>
              ))}
            </AnimatePresence>
          </div>,
          overlay,
        )}
    </ToastCtx.Provider>
  )
}

/** Animated number for the money summary. */
// eslint-disable-next-line react-refresh/only-export-components
export function useCountUp(value: number, duration = 0.8) {
  const [display, setDisplay] = useState(0)
  const from = useRef(0)
  useEffect(() => {
    const c = animate(from.current, value, { duration, ease: [0.16, 1, 0.3, 1], onUpdate: (v) => setDisplay(v) })
    from.current = value
    return () => c.stop()
  }, [value, duration])
  return display
}
