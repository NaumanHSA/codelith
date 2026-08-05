import {
  createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode,
} from 'react'
import { api, AUTH_EXPIRED, tokenStore } from './lib/api'
import type { Role, User } from './lib/types'

interface AuthValue {
  user: User | null
  /** True until the stored token has been checked against /auth/me. */
  booting: boolean
  signIn: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, fullName: string) => Promise<void>
  signOut: () => void
  can: (need: Role) => boolean
}

const AuthContext = createContext<AuthValue | null>(null)

/** Roles in ascending order of privilege. */
const RANK: Record<string, number> = { viewer: 0, reviewer: 1, manager: 2, admin: 3 }

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [booting, setBooting] = useState(true)

  // Restore the session from persisted tokens on first paint.
  useEffect(() => {
    let live = true
    if (!tokenStore.access) {
      setBooting(false)
      return
    }
    api
      .me()
      .then(u => live && setUser(u))
      .catch(() => {
        tokenStore.clear()
        if (live) setUser(null)
      })
      .finally(() => live && setBooting(false))
    return () => {
      live = false
    }
  }, [])

  // The API client broadcasts when a refresh fails; drop the session.
  useEffect(() => {
    const onExpired = () => setUser(null)
    window.addEventListener(AUTH_EXPIRED, onExpired)
    return () => window.removeEventListener(AUTH_EXPIRED, onExpired)
  }, [])

  const signIn = useCallback(async (email: string, password: string) => {
    tokenStore.set(await api.login({ email, password }))
    setUser(await api.me())
  }, [])

  const register = useCallback(
    async (email: string, password: string, fullName: string) => {
      // Register returns a user, not tokens — log in afterwards.
      await api.register({ email, password, full_name: fullName })
      tokenStore.set(await api.login({ email, password }))
      setUser(await api.me())
    },
    [],
  )

  const signOut = useCallback(() => {
    tokenStore.clear()
    setUser(null)
  }, [])

  const can = useCallback(
    (need: Role) => (RANK[user?.role ?? ''] ?? -1) >= (RANK[need] ?? 99),
    [user],
  )

  const value = useMemo(
    () => ({ user, booting, signIn, register, signOut, can }),
    [user, booting, signIn, register, signOut, can],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
