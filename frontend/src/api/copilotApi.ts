import { apiClient } from './client'

export interface ChartData {
  type: string
  labels: string[]
  series: number[]
}

export interface AskQuestionResponse {
  insight_id: string
  question: string
  answer: string
  chart_data: ChartData | null
  model_used: string
  created_at: string
}

export const copilotApi = {
  ask: (question: string) => apiClient.post<AskQuestionResponse>('/copilot/ask', { question }),
}
