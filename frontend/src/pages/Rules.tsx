import type { ReactNode } from 'react'
import {
  BadgeDollarSign, BellRing, CalendarClock, CreditCard, Lock, PackageX, Repeat, ShieldCheck, ShoppingCart, Star,
  Store, TrendingDown, Undo2, type LucideIcon,
} from 'lucide-react'
import { PageHeader } from '@/components/shell'
import { getMandate } from '@/lib/api'
import { usePoll } from '@/lib/hooks'
import { cn, fmtDate, storeName, usd } from '@/lib/utils'

function Group({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <section>
      <h2 className="text-faint mb-2 px-1 text-[13px] font-bold tracking-wider uppercase">{title}</h2>
      <div className="bg-surface divide-y divide-white/6 overflow-hidden rounded-[22px] ring-1 ring-white/6">{children}</div>
      {note && <p className="text-faint mt-2 px-1 text-[13px] leading-snug">{note}</p>}
    </section>
  )
}

function Row({ icon: Icon, tone, title, sub, right }: { icon: LucideIcon; tone: string; title: string; sub?: string; right: ReactNode }) {
  return (
    <div className="flex min-h-[64px] items-center gap-3 px-4 py-3">
      <span className={cn('flex size-9 shrink-0 items-center justify-center rounded-[11px]', tone)}>
        <Icon className="size-[18px]" strokeWidth={2.2} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[16px] leading-tight font-semibold">{title}</div>
        {sub && <div className="text-muted mt-0.5 text-[13px] leading-snug">{sub}</div>}
      </div>
      <div className="shrink-0 text-right">{right}</div>
    </div>
  )
}

function Toggle({ on }: { on: boolean }) {
  return (
    <span role="switch" aria-checked={on} aria-readonly className={cn('relative inline-flex h-[30px] w-[50px] rounded-full transition-colors', on ? 'bg-money' : 'bg-surface-3')}>
      <span className={cn('absolute top-[3px] size-6 rounded-full bg-white shadow transition-all', on ? 'left-[23px]' : 'left-[3px]')} />
    </span>
  )
}

const Value = ({ children }: { children: ReactNode }) => <span className="text-[16px] font-bold tabular-nums">{children}</span>

export default function Rules() {
  const { data: m, error } = usePoll(getMandate, 60_000)
  const r = m?.rules

  return (
    <div>
      <PageHeader title="Your rules" subtitle="Snapback acts on its own inside these. Anything outside asks you first." />
      {error && !m && <div className="text-danger px-5 text-[14px]">Couldn’t load rules: {error}</div>}
      {m && r && (
        <div className="space-y-6 px-4 pt-2">
          <div className="from-money/18 to-surface relative overflow-hidden rounded-[24px] bg-gradient-to-br p-5 ring-1 ring-money/30">
            <div className="flex items-center gap-3">
              <span className="bg-money text-money-ink flex size-12 items-center justify-center rounded-full">
                <ShieldCheck className="size-6" strokeWidth={2.4} />
              </span>
              <div>
                <div className="text-[18px] font-bold tracking-tight">Verified by {m.verified_by === 'persona' ? 'Persona' : m.verified_by ?? '—'}</div>
                <div className="text-muted text-[13px]">
                  A verified human set these rules{m.verified_at ? ` · ${fmtDate(m.verified_at)}` : ''}
                </div>
              </div>
            </div>
            <div className="text-faint mt-3 font-mono text-[12px]">
              {m.user_id}
              {m.persona_inquiry_id ? ` · ${m.persona_inquiry_id}` : ''}
            </div>
          </div>

          <Group title="Acts automatically" note="Each action in the audit trail names the rule that allowed it.">
            <Row icon={Undo2} tone="bg-money/15 text-money" title="Return defective items" sub="Inside the store’s return window" right={<Toggle on={r.auto_return_defective} />} />
            <Row icon={PackageX} tone="bg-money/15 text-money" title="File missing-package claims" sub="When the carrier says lost or late" right={<Toggle on={r.auto_missing_package_claim} />} />
            <Row icon={TrendingDown} tone="bg-money/15 text-money" title="Claim minor price drops" sub="If the store’s policy allows it" right={<Toggle on={r.price_drop.auto_adjust_minor} />} />
            <Row icon={Repeat} tone="bg-money/15 text-money" title="Buy replacements" sub="For items it returns as defective" right={<Toggle on={r.replacement.enabled} />} />
          </Group>

          <Group title="Asks you first" note="One tap, verified with Persona. Then it runs end to end.">
            <Row
              icon={TrendingDown}
              tone="bg-warn/15 text-warn"
              title="Major price drop"
              sub="Either threshold counts as major"
              right={
                <Value>
                  ≥{r.price_drop.major_if.min_percent}% <span className="text-faint font-semibold">or</span> ≥{usd(r.price_drop.major_if.min_usd)}
                </Value>
              }
            />
            <Row icon={ShoppingCart} tone="bg-warn/15 text-warn" title="Any purchase over" sub="Gross charge of a new order" right={<Value>{usd(r.require_approval_over_usd)}</Value>} />
            <Row icon={CalendarClock} tone="bg-warn/15 text-warn" title="Return window closing" sub="Alert before the deadline" right={<Value>{r.return_window_alert_days} days</Value>} />
            <Row icon={BellRing} tone="bg-warn/15 text-warn" title="Duplicate orders" sub="Same item, same day" right={<Value>Always</Value>} />
          </Group>

          <Group title="Replacements">
            <Row
              icon={Star}
              tone="bg-info/15 text-info"
              title="Strategy"
              sub={r.replacement.strategy === 'same_item_unless_poor_reviews' ? `Same item, unless reviews fall below ${r.replacement.poor_review_threshold ?? 3.5}★` : r.replacement.strategy.replace(/_/g, ' ')}
              right={<Value>{r.replacement.strategy === 'same_item_unless_poor_reviews' ? 'Same item' : '—'}</Value>}
            />
            <Row icon={BadgeDollarSign} tone="bg-info/15 text-info" title="Max extra spend" sub="Over the original price" right={<Value>+{usd(r.replacement.max_extra_spend_usd)}</Value>} />
          </Group>

          <Group title="Money">
            <Row icon={CreditCard} tone="bg-white/8 text-ink" title="Refunds go to" right={<Value>{r.refund_method === 'original_payment' ? 'Original card' : r.refund_method}</Value>} />
            <Row icon={Lock} tone="bg-white/8 text-ink" title="Card numbers" sub="Checkout uses a payment token" right={<Value>Never seen</Value>} />
          </Group>

          <section>
            <h2 className="text-faint mb-2 px-1 text-[13px] font-bold tracking-wider uppercase">Allowed stores</h2>
            <div className="flex flex-wrap gap-2">
              {r.allowed_stores.map((s) => (
                <span key={s} className="bg-surface flex items-center gap-2 rounded-full py-2 pr-4 pl-2 text-[15px] font-semibold ring-1 ring-white/8">
                  <span className="bg-surface-3 flex size-7 items-center justify-center rounded-full">
                    <Store className="text-money size-3.5" />
                  </span>
                  {storeName(s)}
                </span>
              ))}
            </div>
          </section>

          <button disabled className="bg-surface text-faint flex w-full items-center justify-center gap-2 rounded-[20px] py-4 text-[15px] font-semibold ring-1 ring-white/6">
            <Lock className="size-4" /> Editing rules requires Persona re-verification
          </button>
        </div>
      )}
    </div>
  )
}
