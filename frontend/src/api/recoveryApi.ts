import { apiClient } from './client'

export interface FailedPaymentListItem {
  failed_payment_id: string
  customer: { name: string; email?: string }
  amount: number
  currency: string
  failure_reason_category: string
  status: string
  recovery_score: number | null
  risk_tier: string | null
  retry_attempts_count: number
  detected_at: string
}

export interface FailedPaymentListResponse {
  items: FailedPaymentListItem[]
  page: number
  page_size: number
  total_items: number
  total_pages: number
}

export interface RecommendedAction {
  channel: string
  next_attempt_at: string
  cadence_step: number
}

export interface RecoveryPrediction {
  prediction_id: string
  failed_payment_id: string
  recovery_score: number
  risk_tier: string
  model_version: string
  recommended_action: RecommendedAction | null
  predicted_at: string
}

export interface RecoveryRecommendation {
  failed_payment_id: string
  current_prediction: RecoveryPrediction
  history: RecoveryPrediction[]
}

export const recoveryApi = {
  listFailedPayments: (params: Record<string, string | number | undefined> = {}) => {
    const query = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== undefined) as [string, string][],
    ).toString()
    return apiClient.get<FailedPaymentListResponse>(`/failed-payments${query ? `?${query}` : ''}`)
  },
  getRecommendation: (failedPaymentId: string, includeHistory = false) =>
    apiClient.get<RecoveryRecommendation>(
      `/recovery-predictions/${failedPaymentId}?include_history=${includeHistory}`,
    ),
  retryPayment: (failedPaymentId: string, notifyCustomer = true) =>
    apiClient.post(`/failed-payments/${failedPaymentId}/retry`, { notify_customer: notifyCustomer }),
}
