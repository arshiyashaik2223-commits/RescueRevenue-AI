import { apiClient } from './client'

export interface TokenResponse {
  business_id: string
  user_id: string
  email: string
  role: string
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export const authApi = {
  register: (payload: { business_name: string; admin_name: string; email: string; password: string }) =>
    apiClient.post<TokenResponse>('/auth/register', payload),
  login: (payload: { email: string; password: string }) => apiClient.post<TokenResponse>('/auth/login', payload),
  logout: (refresh_token: string) => apiClient.post('/auth/logout', { refresh_token }),
}
