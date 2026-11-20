// Audit hash chain helpers: entry_hash = sha256(prev_hash + canonical_json(entry)).
// Pure-JS SHA-256 so it works without a secure context (e.g. demo laptop opened over LAN IP).
import type { AuditEntry, ChainCheck } from './types'

const K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
])

const ror = (x: number, n: number) => (x >>> n) | (x << (32 - n))

export function sha256Hex(msg: string): string {
  const bytes = new TextEncoder().encode(msg)
  const len = bytes.length
  const padded = new Uint8Array(((len + 9 + 63) >> 6) << 6)
  padded.set(bytes)
  padded[len] = 0x80
  const dv = new DataView(padded.buffer)
  const bitLen = len * 8
  dv.setUint32(padded.length - 4, bitLen >>> 0)
  dv.setUint32(padded.length - 8, Math.floor(bitLen / 0x100000000))
  const H = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]
  const w = new Uint32Array(64)
  for (let i = 0; i < padded.length; i += 64) {
    for (let t = 0; t < 16; t++) w[t] = dv.getUint32(i + t * 4)
    for (let t = 16; t < 64; t++) {
      const x = w[t - 15]
      const y = w[t - 2]
      const s0 = ror(x, 7) ^ ror(x, 18) ^ (x >>> 3)
      const s1 = ror(y, 17) ^ ror(y, 19) ^ (y >>> 10)
      w[t] = (w[t - 16] + s0 + w[t - 7] + s1) | 0
    }
    let [a, b, c, d, e, f, g, h] = H
    for (let t = 0; t < 64; t++) {
      const S1 = ror(e, 6) ^ ror(e, 11) ^ ror(e, 25)
      const ch = (e & f) ^ (~e & g)
      const t1 = (h + S1 + ch + K[t] + w[t]) | 0
      const S0 = ror(a, 2) ^ ror(a, 13) ^ ror(a, 22)
      const maj = (a & b) ^ (a & c) ^ (b & c)
      const t2 = (S0 + maj) | 0
      h = g
      g = f
      f = e
      e = (d + t1) | 0
      d = c
      c = b
      b = a
      a = (t1 + t2) | 0
    }
    H[0] = (H[0] + a) | 0
    H[1] = (H[1] + b) | 0
    H[2] = (H[2] + c) | 0
    H[3] = (H[3] + d) | 0
    H[4] = (H[4] + e) | 0
    H[5] = (H[5] + f) | 0
    H[6] = (H[6] + g) | 0
    H[7] = (H[7] + h) | 0
  }
  return H.map((x) => (x >>> 0).toString(16).padStart(8, '0')).join('')
}

export const GENESIS = '0'.repeat(64)

function canon(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(canon)
  if (v && typeof v === 'object') {
    const out: Record<string, unknown> = {}
    for (const k of Object.keys(v as object).sort()) out[k] = canon((v as Record<string, unknown>)[k])
    return out
  }
  return v
}

export function canonicalJson(v: unknown): string {
  return JSON.stringify(canon(v))
}

const HASHED: (keyof AuditEntry)[] = [
  'seq', 'task_id', 'step', 'decision', 'reason', 'sources', 'rejected_options', 'rules_checked',
  'authorized_by', 'model', 'cost_usd', 'latency_ms', 'verified', 'created_at',
]

/** Mock-mode hash. Live mode trusts the backend's own canonicalization (GET /api/audit/verify). */
export function computeEntryHash(prev: string, e: AuditEntry): string {
  const payload: Record<string, unknown> = {}
  for (const k of HASHED) payload[k] = e[k] ?? null
  return sha256Hex(prev + canonicalJson(payload))
}

/**
 * Check a run of entries (sorted by seq). prev_hash must equal the previous entry_hash whenever
 * the two entries are adjacent in the global chain (seq differs by 1). With `recompute`, each
 * entry's own hash is re-derived too, so any edited field is caught.
 */
export function verifyEntries(entries: AuditEntry[], recompute: boolean): ChainCheck {
  const sorted = [...entries].sort((a, b) => (a.seq ?? a.entry_id) - (b.seq ?? b.entry_id))
  let links = 0
  for (let i = 0; i < sorted.length; i++) {
    const e = sorted[i]
    if (recompute && computeEntryHash(e.prev_hash, e) !== e.entry_hash) {
      return { ok: false, checked_links: links, broken_at: e.entry_id, detail: `Entry #${e.entry_id} (${e.step}) was modified after it was sealed` }
    }
    if (i > 0) {
      const p = sorted[i - 1]
      const adjacent = e.seq === undefined || p.seq === undefined || e.seq === p.seq + 1
      if (adjacent) {
        links++
        if (e.prev_hash !== p.entry_hash) {
          return { ok: false, checked_links: links, broken_at: e.entry_id, detail: `Entry #${e.entry_id} does not link to #${p.entry_id}` }
        }
      }
    }
  }
  return { ok: true, checked_links: links, detail: `${sorted.length} entries · ${links} links checked` }
}
