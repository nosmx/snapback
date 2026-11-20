// Editable standing rules. Edits are a local draft until you review them and Persona confirms it's you.
import { useState, type ReactNode } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { BadgeCheck, CalendarClock, Check, PackageX, Repeat, ShoppingCart, Store, TrendingDown, Undo2, type LucideIcon } from 'lucide-react'
import { Persona } from '@/components/DecisionSheet'
import { List, NavBar, Row, Sheet, useToast } from '@/components/shell'
import { getMandate, updateMandate } from '@/lib/api'
import { usePoll } from '@/lib/hooks'
import { STORE_NAMES, cn, fmtDate, sleep, storeName, usd } from '@/lib/utils'
import type { MandateRules } from '@/lib/types'

// ---------- formatting & the fields shown in "Review changes" ----------
const onOff = (b: boolean) => (b ? 'On' : 'Off')
const extra = (n: number) => (n === 0 ? 'None' : `up to ${usd(n)}`)
const askAt = (r: MandateRules) => `${r.price_drop.major_if.min_percent}% or ${usd(r.price_drop.major_if.min_usd)}+`

const FIELDS: { label: string; get: (r: MandateRules) => string }[] = [
  { label: 'Ask before spending over', get: (r) => usd(r.require_approval_over_usd) },
  { label: 'Extra on a replacement', get: (r) => extra(r.replacement.max_extra_spend_usd) },
  { label: 'Claim small price drops automatically', get: (r) => onOff(r.price_drop.auto_adjust_minor) },
  { label: 'Ask me when a price drops', get: askAt },
  { label: 'Return defective items automatically', get: (r) => onOff(r.auto_return_defective) },
  { label: 'Buy a replacement', get: (r) => onOff(r.replacement.enabled) },
  { label: 'Remind me before a return deadline', get: (r) => `${r.return_window_alert_days} days` },
  { label: 'Claim missing packages automatically', get: (r) => onOff(r.auto_missing_package_claim) },
  { label: 'Allowed stores', get: (r) => r.allowed_stores.map(storeName).join(', ') || 'None' },
]

const OPTIONS = {
  approval: [50, 100, 150, 200, 300, 500],
  extra: [0, 10, 20, 30, 50, 75],
  percent: [5, 10, 15, 20, 25, 30],
  dollars: [5, 10, 20, 30, 50],
  days: [1, 2, 3, 5, 7],
}

// ---------- small iOS controls ----------
function Switch({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      role="switch"
      aria-checked={on}
      aria-label={label}
      onClick={() => onChange(!on)}
      className={cn('relative h-[31px] w-[51px] shrink-0 rounded-full transition-colors duration-200', on ? 'bg-green' : 'bg-fill')}
    >
      <span className={cn('absolute top-[2px] left-[2px] size-[27px] rounded-full bg-white shadow-[0_2px_4px_rgba(0,0,0,0.2)] transition-transform duration-200', on && 'translate-x-[20px]')} />
    </button>
  )
}

function Group({ title, footer, children }: { title: string; footer?: string; children: ReactNode }) {
  return (
    <section>
      <h2 className="text-ink-2 mb-1.5 px-4 text-[13px] uppercase">{title}</h2>
      <List inset={52}>{children}</List>
      {footer && <p className="text-ink-2 mt-1.5 px-4 text-[13px] leading-snug">{footer}</p>}
    </section>
  )
}

const Icon = ({ icon: I }: { icon: LucideIcon }) => <I className="text-ink-2 size-5 shrink-0" strokeWidth={1.6} />
const Value = ({ children, edited }: { children: ReactNode; edited?: boolean }) => (
  <span className={cn('text-[16px] tabular-nums', edited ? 'text-ink font-medium' : 'text-ink-2')}>{children}</span>
)

function Choices<T extends number>({ title, options, value, format, onPick }: { title?: string; options: T[]; value: T; format: (v: T) => string; onPick: (v: T) => void }) {
  return (
    <div>
      {title && <h3 className="text-ink-2 mb-1.5 px-4 text-[13px] uppercase">{title}</h3>}
      <List className="bg-bg">
        {options.map((o) => (
          <Row key={o} onClick={() => onPick(o)} title={format(o)} trailing={o === value ? <Check className="text-ink size-5" strokeWidth={2.2} /> : null} />
        ))}
      </List>
    </div>
  )
}

type Picker = null | 'approval' | 'extra' | 'threshold' | 'days'

export default function Rules() {
  const toast = useToast()
  const { data: m, error, refresh } = usePoll(getMandate, 60_000)
  const [draft, setDraft] = useState<MandateRules | null>(null)
  const [picker, setPicker] = useState<Picker>(null)
  const [review, setReview] = useState(false)
  const [phase, setPhase] = useState<'review' | 'confirming' | 'verified' | 'error'>('review')
  const [inquiry, setInquiry] = useState('')
  const [err, setErr] = useState('')

  if (error && !m) return (
    <div>
      <NavBar title="Rules" />
      <p className="text-red px-5 text-[14px]">Couldn’t load rules: {error}</p>
    </div>
  )
  if (!m) return <NavBar title="Rules" />

  const saved = m.rules
  const r = draft ?? saved
  const changes = FIELDS.filter((f) => f.get(saved) !== f.get(r)).map((f) => ({ label: f.label, from: f.get(saved), to: f.get(r) }))
  const changed = (label: string) => changes.some((c) => c.label === label)
  const edit = (mutate: (x: MandateRules) => void) => {
    const next = structuredClone(r)
    mutate(next)
    setDraft(next)
  }
  const toggleStore = (s: string, on: boolean) => {
    if (!on && r.allowed_stores.length === 1 && r.allowed_stores.includes(s)) {
      toast('Keep at least one store')
      return
    }
    edit((x) => {
      x.allowed_stores = on ? [...x.allowed_stores, s] : x.allowed_stores.filter((v) => v !== s)
    })
  }

  const save = async () => {
    if (!draft) return
    setPhase('confirming')
    try {
      await sleep(1500) // Persona confirmation, simulated in the UI
      const next = await updateMandate(draft)
      setInquiry(next.persona_inquiry_id ?? '')
      setPhase('verified')
      await sleep(900)
      await refresh()
      setDraft(null)
      setReview(false)
      toast('Rules updated')
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
      setPhase('error')
    }
  }

  const mi = r.price_drop.major_if
  return (
    <div>
      <NavBar title="Rules" />
      <div className="space-y-7 px-4">
        <Group title="Spending" footer="Anything above these limits asks you first.">
          <Row leading={<Icon icon={ShoppingCart} />} title="Ask before spending over" onClick={() => setPicker('approval')} chevron trailing={<Value edited={changed(FIELDS[0].label)}>{usd(r.require_approval_over_usd)}</Value>} />
          <Row leading={<Icon icon={Repeat} />} title="Extra on a replacement" onClick={() => setPicker('extra')} chevron trailing={<Value edited={changed(FIELDS[1].label)}>{extra(r.replacement.max_extra_spend_usd)}</Value>} />
        </Group>

        <Group title="Price drops" footer={`Drops under ${mi.min_percent}% and ${usd(mi.min_usd)} are small. Bigger drops always ask you.`}>
          <Row
            leading={<Icon icon={TrendingDown} />}
            title="Claim small drops automatically"
            trailing={<Switch label="Claim small drops automatically" on={r.price_drop.auto_adjust_minor} onChange={(v) => edit((x) => void (x.price_drop.auto_adjust_minor = v))} />}
          />
          <Row leading={<Icon icon={TrendingDown} />} title="Ask me when it drops" onClick={() => setPicker('threshold')} chevron trailing={<Value edited={changed(FIELDS[3].label)}>{askAt(r)}</Value>} />
        </Group>

        <Group title="Returns">
          <Row
            leading={<Icon icon={Undo2} />}
            title="Return defective items"
            subtitle="Automatically, inside the return window"
            trailing={<Switch label="Return defective items" on={r.auto_return_defective} onChange={(v) => edit((x) => void (x.auto_return_defective = v))} />}
          />
          <Row
            leading={<Icon icon={Repeat} />}
            title="Buy a replacement"
            subtitle="For items returned as defective"
            trailing={<Switch label="Buy a replacement" on={r.replacement.enabled} onChange={(v) => edit((x) => void (x.replacement.enabled = v))} />}
          />
          <Row leading={<Icon icon={CalendarClock} />} title="Remind me before deadline" onClick={() => setPicker('days')} chevron trailing={<Value edited={changed(FIELDS[6].label)}>{r.return_window_alert_days} days</Value>} />
          <Row
            leading={<Icon icon={PackageX} />}
            title="Claim missing packages"
            subtitle="When the carrier says lost or late"
            trailing={<Switch label="Claim missing packages" on={r.auto_missing_package_claim} onChange={(v) => edit((x) => void (x.auto_missing_package_claim = v))} />}
          />
        </Group>

        <Group title={`Stores · ${r.allowed_stores.length} allowed`} footer="Snapback never acts at stores you haven’t allowed.">
          {Object.keys(STORE_NAMES).map((s) => (
            <Row key={s} leading={<Icon icon={Store} />} title={storeName(s)} trailing={<Switch label={storeName(s)} on={r.allowed_stores.includes(s)} onChange={(v) => toggleStore(s, v)} />} />
          ))}
        </Group>

        <Group title="Identity" footer="Refunds always go to your original card. Snapback never sees card numbers.">
          <Row
            leading={<BadgeCheck className="text-green size-5 shrink-0" strokeWidth={1.8} />}
            title="Verified with Persona"
            subtitle={m.verified_at ? `Rules last confirmed ${fmtDate(m.verified_at)}` : undefined}
            trailing={
              <span className="text-green flex items-center gap-1 text-[16px]">
                <Check className="size-4" strokeWidth={2.4} /> Verified
              </span>
            }
          />
        </Group>

        <p className="text-ink-3 px-4 text-center text-[13px]">Changes take effect after Persona confirms it’s you.</p>
      </div>

      {/* Unsaved changes bar: sticks above the tab bar while you scroll */}
      <AnimatePresence>
        {changes.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 16 }}
            transition={{ duration: 0.2 }}
            className="bg-card sticky z-20 mx-4 mt-6 flex items-center gap-2 rounded-2xl py-2.5 pr-2.5 pl-4 shadow-[0_8px_30px_rgba(0,0,0,0.14)]"
            style={{ bottom: 'calc(var(--tabbar-h) + 12px)' }}
          >
            <span className="flex-1 text-[15px] font-medium">
              {changes.length} unsaved change{changes.length === 1 ? '' : 's'}
            </span>
            <button onClick={() => setDraft(null)} className="text-ink-2 px-2 text-[15px]">
              Discard
            </button>
            <button
              onClick={() => {
                setPhase('review')
                setReview(true)
              }}
              className="tap bg-ink text-bg h-9 rounded-full px-4 text-[15px] font-semibold"
            >
              Review
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Value pickers */}
      <Sheet open={picker === 'approval'} onClose={() => setPicker(null)}>
        <h2 className="text-[20px] font-semibold">Ask before spending over</h2>
        <p className="text-ink-2 mt-1 mb-4 text-[15px]">Any new order above this needs your one-tap approval.</p>
        <Choices options={OPTIONS.approval} value={r.require_approval_over_usd} format={(v) => usd(v)} onPick={(v) => (edit((x) => void (x.require_approval_over_usd = v)), setPicker(null))} />
      </Sheet>
      <Sheet open={picker === 'extra'} onClose={() => setPicker(null)}>
        <h2 className="text-[20px] font-semibold">Extra on a replacement</h2>
        <p className="text-ink-2 mt-1 mb-4 text-[15px]">How much more than the original a replacement may cost.</p>
        <Choices options={OPTIONS.extra} value={r.replacement.max_extra_spend_usd} format={extra} onPick={(v) => (edit((x) => void (x.replacement.max_extra_spend_usd = v)), setPicker(null))} />
      </Sheet>
      <Sheet open={picker === 'days'} onClose={() => setPicker(null)}>
        <h2 className="text-[20px] font-semibold">Remind me before deadline</h2>
        <p className="text-ink-2 mt-1 mb-4 text-[15px]">When to ask about a return window that’s about to close.</p>
        <Choices options={OPTIONS.days} value={r.return_window_alert_days} format={(v) => `${v} day${v === 1 ? '' : 's'} before`} onPick={(v) => (edit((x) => void (x.return_window_alert_days = v)), setPicker(null))} />
      </Sheet>
      <Sheet open={picker === 'threshold'} onClose={() => setPicker(null)}>
        <h2 className="text-[20px] font-semibold">Ask me when a price drops by</h2>
        <p className="text-ink-2 mt-1 mb-4 text-[15px]">Either one counts. Smaller drops are claimed automatically if you allow it.</p>
        <div className="space-y-5">
          <Choices title="Percent" options={OPTIONS.percent} value={mi.min_percent} format={(v) => `${v}% or more`} onPick={(v) => edit((x) => void (x.price_drop.major_if.min_percent = v))} />
          <Choices title="Or dollars" options={OPTIONS.dollars} value={mi.min_usd} format={(v) => `${usd(v)} or more`} onPick={(v) => edit((x) => void (x.price_drop.major_if.min_usd = v))} />
        </div>
        <button onClick={() => setPicker(null)} className="tap bg-ink text-bg mt-5 h-12 w-full rounded-xl text-[17px] font-semibold">
          Done
        </button>
      </Sheet>

      {/* Review + Persona */}
      <Sheet open={review} onClose={() => setReview(false)} dismissible={phase === 'review' || phase === 'error'}>
        {phase === 'review' && (
          <div>
            <h2 className="text-[20px] font-semibold">Review changes</h2>
            <p className="text-ink-2 mt-1 text-[15px]">Snapback will follow these from now on.</p>
            <List className="bg-bg mt-4">
              {changes.map((c) => (
                <div key={c.label} className="px-4 py-3">
                  <div className="text-[15px]">{c.label}</div>
                  <div className="text-ink-2 mt-0.5 text-[14px]">
                    <span className="line-through">{c.from}</span>
                    <span className="mx-1.5">→</span>
                    <span className="text-ink font-medium">{c.to}</span>
                  </div>
                </div>
              ))}
            </List>
            <button onClick={save} className="tap bg-ink text-bg mt-5 h-12 w-full rounded-xl text-[17px] font-semibold">
              Confirm with Persona
            </button>
            <button onClick={() => setReview(false)} className="text-ink-2 mt-1 h-11 w-full text-[16px]">
              Cancel
            </button>
          </div>
        )}
        {(phase === 'confirming' || phase === 'verified') && <Persona verified={phase === 'verified'} inquiry={inquiry} />}
        {phase === 'error' && (
          <div className="py-6 text-center">
            <div className="text-red text-[17px] font-semibold">Couldn’t save your rules</div>
            <div className="text-ink-2 mt-1 text-[15px]">{err}</div>
            <button onClick={() => setPhase('review')} className="tap bg-fill mt-5 h-12 w-full rounded-xl text-[17px] font-semibold">
              Back
            </button>
          </div>
        )}
      </Sheet>
    </div>
  )
}
