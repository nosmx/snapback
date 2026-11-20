import { useEffect, useState } from 'react'

type Health = {
  integrations: Record<string, 'real' | 'mock'>
  db_backend: string
  counts: Record<string, number>
}

// Block 1 placeholder: live sponsor status. Feed, decision cards and audit timeline come next.
export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [chain, setChain] = useState<{ ok: boolean; entries: number } | null>(null)

  useEffect(() => {
    const load = () => {
      fetch('/api/health').then((r) => r.json()).then(setHealth).catch(() => setHealth(null))
      fetch('/api/audit/verify').then((r) => r.json()).then(setChain).catch(() => setChain(null))
    }
    load()
    const t = setInterval(load, 2000)
    return () => clearInterval(t)
  }, [])

  return (
    <main className="mx-auto max-w-3xl p-6 font-sans text-stone-900">
      <h1 className="text-3xl font-bold tracking-tight">Snapback</h1>
      <p className="text-stone-600">Post-purchase autopilot with an audit trail.</p>
      <section className="mt-6 rounded-xl bg-white p-5 shadow-sm ring-1 ring-stone-200">
        <h2 className="font-semibold">Sponsor stack</h2>
        {!health && <p className="text-sm text-red-700">Backend not reachable on :8000</p>}
        <ul className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
          {health &&
            Object.entries(health.integrations).map(([name, mode]) => (
              <li key={name} className="flex items-center justify-between rounded-lg bg-stone-50 px-3 py-2 text-sm">
                <span className="font-medium">{name}</span>
                <span className={mode === 'real' ? 'text-green-700' : 'text-amber-700'}>{mode}</span>
              </li>
            ))}
        </ul>
        {health && (
          <p className="mt-3 text-sm text-stone-600">
            {health.counts.orders} orders · {health.counts.catalog} catalog items · {health.counts.audit_log} audit entries
            {chain && (chain.ok ? ' · chain verified ✓' : ' · chain BROKEN')}
          </p>
        )}
      </section>
    </main>
  )
}
