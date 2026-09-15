import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api } from './api'
import type { AuthUser } from './types'

interface AuthState {
  user: AuthUser | null
  loading: boolean
  login: (username: string, password: string) => Promise<AuthUser>
  logout: () => Promise<void>
}

const Ctx = createContext<AuthState>(null as unknown as AuthState)
// oxlint-disable-next-line react/only-export-components -- context hook 與 provider 必須共享同一實例
export const useAuth = () => useContext(Ctx)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.me().then(r => setUser(r.user)).catch(() => setUser(null)).finally(() => setLoading(false))
    const expired = () => setUser(null)
    window.addEventListener('ops:unauthorized', expired)
    return () => window.removeEventListener('ops:unauthorized', expired)
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    const r = await api.login(username, password); setUser(r.user); return r.user
  }, [])
  const logout = useCallback(async () => { try { await api.logout() } finally { setUser(null) } }, [])
  return <Ctx.Provider value={{ user, loading, login, logout }}>{children}</Ctx.Provider>
}
