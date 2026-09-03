import { apiClient } from './client'

export interface RevenueSummary {
  period: { from_date: string; to_date: string }
  revenue_at_risk: number
  revenue_recovered: number
  recovery_rate: number
  avg_time_to_recovery_hours: number
  currency: string
}

export interface RecoveryMetrics {
  period: { from_date: string; to_date: string }
  funnel: { detected: number; attempted: number; recovered: number; lost: number }
  breakdown: { group_by: string; data: { key: string; detected: number; recovered: number }[] } | null
}

export interface FailureTrends {
  period: { from_date: string; to_date: string }
  interval: string
  series: { bucket_start: string; total_failures: number; by_reason: Record<string, number> }[]
}

export const dashboardApi = {
  getRevenueSummary: () => apiClient.get<RevenueSummary>('/analytics/revenue-summary'),
  getRecoveryMetrics: (groupBy?: string) =>
    apiClient.get<RecoveryMetrics>(`/analytics/recovery-metrics${groupBy ? `?group_by=${groupBy}` : ''}`),
  getFailureTrends: (interval = 'day') =>
    apiClient.get<FailureTrends>(`/analytics/failure-trends?interval=${interval}`),
}
