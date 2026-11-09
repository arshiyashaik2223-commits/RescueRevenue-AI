
import { apiClient } from './client'

export interface DateRange {
  from_date: string
  to_date: string
}

export interface RevenueSummary {
  period: DateRange
  revenue_at_risk: number
  revenue_recovered: number
  recovery_rate: number
  avg_time_to_recovery_hours: number
  currency: string
}

export interface RecoveryMetrics {
  period: DateRange
  funnel: {
    detected: number
    attempted: number
    recovered: number
    lost: number
  }
  breakdown: {
    group_by: string
    data: { key: string; detected: number; recovered: number }[]
  } | null
}

export interface FailureTrends {
  period: DateRange
  interval: string
  series: {
    bucket_start: string
    total_failures: number
    by_reason: Record<string, number>
  }[]
}

function dateParams(period: DateRange): string {
  const params = new URLSearchParams({
    from_date: period.from_date,
    to_date: period.to_date,
  })

  return params.toString()
}

export const dashboardApi = {
  getRevenueSummary: (period: DateRange) =>
    apiClient.get<RevenueSummary>(
      `/analytics/revenue-summary?${dateParams(period)}`
    ),

  getRecoveryMetrics: (period: DateRange, groupBy?: string) => {
    const params = new URLSearchParams(dateParams(period))
    if (groupBy) params.set('group_by', groupBy)

    return apiClient.get<RecoveryMetrics>(
      `/analytics/recovery-metrics?${params.toString()}`
    )
  },

  getFailureTrends: (period: DateRange, interval = 'day') => {
    const params = new URLSearchParams(dateParams(period))
    params.set('interval', interval)

    return apiClient.get<FailureTrends>(
      `/analytics/failure-trends?${params.toString()}`
    )
  },
}
