import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { ApiError, api } from '../services/api'
import { clearUserData } from '../services/queryCache'
import type { User } from '../types'

interface AuthState {
  user: User | null
  loading: boolean
  login: (identifier: string, password: string) => Promise<User>
  logout: () => Promise<void>
  refresh: () => Promise<void>
  setUser: (u: User | null) => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUserState] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  const currentId = useRef<number | null>(null)

  // Cached account data belongs to whoever fetched it, so it can't outlive a change of account.
  const setUser = useCallback((next: User | null) => {
    const nextId = next?.id ?? null
    if (currentId.current !== nextId) {
      if (currentId.current !== null) clearUserData()
      currentId.current = nextId
    }
    setUserState(next)
  }, [])

  const refresh = useCallback(async () => {
    try {
      setUser((await api.get<{ user: User | null }>('/api/auth/session')).user)
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setUser(null)
    } finally {
      setLoading(false)
    }
  }, [setUser])

  const sessionRequested = useRef(false)
  useEffect(() => {
    if (sessionRequested.current) return
    sessionRequested.current = true
    void refresh()
  }, [refresh])

  const value = useMemo<AuthState>(() => ({
    user,
    loading,
    setUser,
    refresh,
    login: async (identifier, password) => {
      const u = await api.post<User>('/api/auth/login', { identifier, password })
      setUser(u)
      return u
    },
    logout: async () => {
      await api.post('/api/auth/logout')
      setUser(null)
    },
  }), [user, loading, refresh, setUser])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
