import { createContext, useEffect, useState, type ReactNode } from 'react'
import { authApi, type TokenResponse } from '../api/authApi'
import { setToken, getToken } from '../api/client'

interface AuthUser {
  userId: string
  businessId: string
  email: string
  role: string
}

interface AuthContextValue {
  user: AuthUser | null
  loading: boolean
  error: string | null
  login: (email: string, password: string) => Promise<void>
  register: (payload: { business_name: string; admin_name: string; email: string; password: string }) => Promise<void>
  logout: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined)

const USER_STORAGE_KEY = 'rr_user'
const REFRESH_TOKEN_KEY = 'rr_refresh_token'

function persistSession(response: TokenResponse): AuthUser {
  setToken(response.access_token)
  localStorage.setItem(REFRESH_TOKEN_KEY, response.refresh_token)
  const user: AuthUser = {
    userId: response.user_id,
    businessId: response.business_id,
    email: response.email,
    role: response.role,
  }
  localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(user))
  return user
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const token = getToken()
    const stored = localStorage.getItem(USER_STORAGE_KEY)
    if (token && stored) {
      setUser(JSON.parse(stored) as AuthUser)
    }
    setLoading(false)
  }, [])

  async function login(email: string, password: string) {
    setError(null)
    try {
      const response = await authApi.login({ email, password })
      setUser(persistSession(response))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to sign in.')
      throw err
    }
  }

  async function register(payload: { business_name: string; admin_name: string; email: string; password: string }) {
    setError(null)
    try {
      const response = await authApi.register(payload)
      setUser(persistSession(response))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to create account.')
      throw err
    }
  }

  async function logout() {
    const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY)
    try {
      if (refreshToken) await authApi.logout(refreshToken)
    } catch {
      // Session may already be invalid server-side — clear locally regardless.
    }
    setToken(null)
    localStorage.removeItem(REFRESH_TOKEN_KEY)
    localStorage.removeItem(USER_STORAGE_KEY)
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, loading, error, login, register, logout }}>{children}</AuthContext.Provider>
  )
}
