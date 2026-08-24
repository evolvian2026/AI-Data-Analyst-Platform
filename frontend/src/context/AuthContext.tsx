import {
  createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode,
} from 'react'
import { api, getToken, setToken } from '../lib/api'
import type { SystemConfig, User } from '../lib/types'

interface AuthValue {
  user: User | null
  config: SystemConfig | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (payload: {
    email: string; password: string; full_name?: string; organization?: string
  }) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [config, setConfig] = useState<SystemConfig | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    async function bootstrap() {
      try {
        const systemConfig = await api.config()
        if (!cancelled) setConfig(systemConfig)
      } catch {
        /* the app still renders; the landing page explains the server is unreachable */
      }
      if (getToken()) {
        try {
          const me = await api.me()
          if (!cancelled) setUser(me)
        } catch {
          setToken(null)
        }
      }
      if (!cancelled) setLoading(false)
    }
    void bootstrap()
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    const onExpired = () => setUser(null)
    window.addEventListener('auth:expired', onExpired)
    return () => window.removeEventListener('auth:expired', onExpired)
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const response = await api.login({ email, password })
    setToken(response.access_token)
    setUser(response.user)
  }, [])

  const register = useCallback(async (payload: {
    email: string; password: string; full_name?: string; organization?: string
  }) => {
    const response = await api.register(payload)
    setToken(response.access_token)
    setUser(response.user)
  }, [])

  const logout = useCallback(() => {
    setToken(null)
    setUser(null)
  }, [])

  const value = useMemo(
    () => ({ user, config, loading, login, register, logout }),
    [user, config, loading, login, register, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside AuthProvider')
  return value
}
