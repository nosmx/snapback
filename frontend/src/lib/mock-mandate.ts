// Mirrors backend/mandate.yaml (generalcontext.md §4).
import type { Mandate } from './types'

export const MOCK_MANDATE: Mandate = {
  user_id: 'u_001',
  verified_by: 'persona',
  persona_inquiry_id: 'inq_mock_18cc5addb48f',
  verified_at: new Date(Date.now() - 9 * 86_400_000).toISOString(),
  rules: {
    auto_return_defective: true,
    auto_missing_package_claim: true,
    price_drop: { auto_adjust_minor: true, major_if: { min_percent: 15, min_usd: 20 } },
    return_window_alert_days: 3,
    replacement: { enabled: true, strategy: 'same_item_unless_poor_reviews', poor_review_threshold: 3.5, max_extra_spend_usd: 30 },
    require_approval_over_usd: 200,
    refund_method: 'original_payment',
    allowed_stores: ['northwind-audio', 'juniper-home', 'kestrel-outdoors'],
  },
}
