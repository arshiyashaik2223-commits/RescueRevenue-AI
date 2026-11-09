
import { useState } from 'react'
import { useDashboardData } from '../hooks/useDashboardData'
import type { DateRange } from '../api/dashboardApi'
import { Card } from '../components/ui/Card'
import { FunnelChart } from '../components/charts/FunnelChart'
import { TrendChart } from '../components/charts/TrendChart'

function formatAmount(amount: number, currency: string) {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency,
    maximumFractionDigits: 0,
  }).format(amount / 100)
}

export function Dashboard() {
  const {
    period,
    setPeriod,
    summary,
    metrics,
    trends,
    loading,
    error,
  } = useDashboardData()

  const [draftPeriod, setDraftPeriod] = useState<DateRange>(period)

  function applyDateRange() {
    if (!draftPeriod.from_date || !draftPeriod.to_date) {
      alert('Please select both dates.')
      return
    }

    if (draftPeriod.from_date > draftPeriod.to_date) {
      alert('Start date cannot be after end date.')
      return
    }

    setPeriod(draftPeriod)
  }

  function showDemoData() {
    const demoRange = {
      from_date: '2026-08-01',
      to_date: '2026-09-02',
    }

    setDraftPeriod(demoRange)
    setPeriod(demoRange)
  }

  function showLast30Days() {
    const to = new Date()
    const from = new Date()
    from.setDate(to.getDate() - 30)

    const range = {
      from_date: from.toISOString().slice(0, 10),
      to_date: to.toISOString().slice(0, 10),
    }

    setDraftPeriod(range)
    setPeriod(range)
  }

  return (
    <div className="space-y-8 p-8">
      <div>
        <h1 className="font-display text-2xl text-ink">
          Recovery overview
        </h1>
        <p className="text-sm text-ink-mid">
          {period.from_date} – {period.to_date}
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-4 rounded-lg border border-hairline bg-surface p-4">
        <div>
          <label className="mb-1 block text-xs text-ink-soft">
            From date
          </label>
          <input
            type="date"
            value={draftPeriod.from_date}
            onChange={(e) =>
              setDraftPeriod({
                ...draftPeriod,
                from_date: e.target.value,
              })
            }
            className="rounded border border-hairline bg-surface px-3 py-2 text-sm text-ink"
          />
        </div>

        <div>
          <label className="mb-1 block text-xs text-ink-soft">
            To date
          </label>
          <input
            type="date"
            value={draftPeriod.to_date}
            onChange={(e) =>
              setDraftPeriod({
                ...draftPeriod,
                to_date: e.target.value,
              })
            }
            className="rounded border border-hairline bg-surface px-3 py-2 text-sm text-ink"
          />
        </div>

        <button
          onClick={applyDateRange}
          className="rounded bg-ink px-4 py-2 text-sm text-white"
        >
          Apply dates
        </button>

        <button
          onClick={showDemoData}
          className="rounded border border-hairline px-4 py-2 text-sm text-ink"
        >
          Show demo data
        </button>

        <button
          onClick={showLast30Days}
          className="rounded border border-hairline px-4 py-2 text-sm text-ink"
        >
          Last 30 days
        </button>
      </div>

      {loading && (
        <div className="p-4 text-sm text-ink-mid">
          Loading dashboard analytics…
        </div>
      )}

      {error && (
        <div className="rounded border border-lost p-4 text-sm text-lost">
          Dashboard error: {error}
        </div>
      )}

      {!loading && !error && summary && metrics && trends && (
        <>
          <div className="grid grid-cols-1 gap-px border border-hairline bg-hairline sm:grid-cols-4">
            <div className="bg-surface p-5">
              <div className="text-xs text-ink-soft">Revenue at risk</div>
              <div className="mt-1 font-display text-3xl text-ink">
                {formatAmount(summary.revenue_at_risk, summary.currency)}
              </div>
            </div>

            <div className="bg-surface p-5">
              <div className="text-xs text-ink-soft">Revenue recovered</div>
              <div className="mt-1 font-display text-3xl text-recovered">
                {formatAmount(summary.revenue_recovered, summary.currency)}
              </div>
            </div>

            <div className="bg-surface p-5">
              <div className="text-xs text-ink-soft">Recovery rate</div>
              <div className="mt-1 font-display text-3xl text-ink">
                {(summary.recovery_rate * 100).toFixed(1)}%
              </div>
            </div>

            <div className="bg-surface p-5">
              <div className="text-xs text-ink-soft">
                Avg. time to recover
              </div>
              <div className="mt-1 font-display text-3xl text-ink">
                {summary.avg_time_to_recovery_hours.toFixed(1)}h
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <Card>
              <h2 className="mb-4 text-sm font-medium text-ink">
                Recovery funnel
              </h2>
              <FunnelChart funnel={metrics.funnel} />
            </Card>

            <Card>
              <h2 className="mb-4 text-sm font-medium text-ink">
                Failures over time
              </h2>
              <TrendChart series={trends.series} />
            </Card>
          </div>
        </>
      )}
    </div>
  )
}
