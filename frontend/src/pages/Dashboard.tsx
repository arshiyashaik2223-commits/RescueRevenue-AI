import { useDashboardData } from '../hooks/useDashboardData'
import { Card } from '../components/ui/Card'
import { FunnelChart } from '../components/charts/FunnelChart'
import { TrendChart } from '../components/charts/TrendChart'

function formatAmount(amount: number, currency: string) {
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency, maximumFractionDigits: 0 }).format(
    amount / 100,
  )
}

export function Dashboard() {
  const { summary, metrics, trends, loading, error } = useDashboardData()

  if (loading) return <div className="p-8 text-sm text-ink-mid">Loading dashboard…</div>
  if (error) return <div className="p-8 text-sm text-lost">{error}</div>
  if (!summary || !metrics || !trends) return null

  return (
    <div className="space-y-8 p-8">
      <div>
        <h1 className="font-display text-2xl text-ink">Recovery overview</h1>
        <p className="text-sm text-ink-mid">
          {summary.period.from_date} – {summary.period.to_date}
        </p>
      </div>

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
          <div className="mt-1 font-display text-3xl text-ink">{(summary.recovery_rate * 100).toFixed(1)}%</div>
        </div>
        <div className="bg-surface p-5">
          <div className="text-xs text-ink-soft">Avg. time to recover</div>
          <div className="mt-1 font-display text-3xl text-ink">
            {summary.avg_time_to_recovery_hours.toFixed(1)}h
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <h2 className="mb-4 text-sm font-medium text-ink">Recovery funnel</h2>
          <FunnelChart funnel={metrics.funnel} />
        </Card>
        <Card>
          <h2 className="mb-4 text-sm font-medium text-ink">Failures over time</h2>
          <TrendChart series={trends.series} />
        </Card>
      </div>
    </div>
  )
}
