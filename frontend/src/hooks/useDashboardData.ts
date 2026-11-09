
import { useEffect, useState } from 'react'
import {
  dashboardApi,
  type DateRange,
  type RevenueSummary,
  type RecoveryMetrics,
  type FailureTrends,
} from '../api/dashboardApi'

const DEMO_PERIOD: DateRange = {
  from_date: '2026-08-01',
  to_date: '2026-09-02',
}

export function useDashboardData() {
  const [period, setPeriod] = useState<DateRange>(DEMO_PERIOD)

  const [summary, setSummary] = useState<RevenueSummary | null>(null)
  const [metrics, setMetrics] = useState<RecoveryMetrics | null>(null)
  const [trends, setTrends] = useState<FailureTrends | null>(null)

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function loadDashboard() {
      setLoading(true)
      setError(null)

      try {
        const [summaryData, metricsData, trendsData] = await Promise.all([
          dashboardApi.getRevenueSummary(period),
          dashboardApi.getRecoveryMetrics(period),
          dashboardApi.getFailureTrends(period, 'day'),
        ])

        if (!cancelled) {
          setSummary(summaryData)
          setMetrics(metricsData)
          setTrends(trendsData)
        }
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error
              ? err.message
              : 'Failed to load dashboard data.'
          )
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    loadDashboard()

    return () => {
      cancelled = true
    }
  }, [period.from_date, period.to_date])

  return {
    period,
    setPeriod,
    summary,
    metrics,
    trends,
    loading,
    error,
  }
}
