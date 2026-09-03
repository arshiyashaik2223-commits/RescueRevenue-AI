import { useState } from 'react'
import { useRecoveryCases } from '../hooks/useRecoveryCases'
import { RecoveryTable } from '../components/tables/RecoveryTable'

export function RecoveryFeed() {
  const [status, setStatus] = useState<string | undefined>(undefined)
  const { data, loading, error } = useRecoveryCases({ status, page_size: 50 })

  return (
    <div className="space-y-6 p-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl text-ink">Recovery feed</h1>
          <p className="text-sm text-ink-mid">Every failed payment, ranked by how likely it is to come back.</p>
        </div>
        <select
          value={status ?? ''}
          onChange={(e) => setStatus(e.target.value || undefined)}
          className="border border-hairline bg-surface px-3 py-2 text-sm"
        >
          <option value="">All statuses</option>
          <option value="open">Open</option>
          <option value="recovered">Recovered</option>
          <option value="lost">Lost</option>
          <option value="expired">Expired</option>
        </select>
      </div>

      {loading && <p className="text-sm text-ink-mid">Loading cases…</p>}
      {error && <p className="text-sm text-lost">{error}</p>}
      {data && <RecoveryTable items={data.items} />}
    </div>
  )
}
