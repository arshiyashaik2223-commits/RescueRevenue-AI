import { useEffect, useState } from 'react'
import { dashboardApi, type RevenueSummary, type RecoveryMetrics, type FailureTrends } from '../api/dashboardApi'

export function useDashboardData() {
  const [summary, setSummary] = useState<RevenueSummary | null>(null)
  const [metrics, setMetrics] = useState<RecoveryMetrics | null>(null)
  const [trends, setTrends] = useState<FailureTrends | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    Promise.all([dashboardApi.getRevenueSummary(), dashboardApi.getRecoveryMetrics(), dashboardApi.getFailureTrends()])
      .then(([s, m, t]) => {
        setSummary(s)
        setMetrics(m)
        setTrends(t)
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load dashboard data.'))
      .finally(() => setLoading(false))
  }, [])

  return { summary, metrics, trends, loading, error }
}
