import { createContext, useContext, useEffect, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, setCsrfToken } from './api'
import type { User } from './types'

interface AuthContextValue {
  user: User
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside AuthProvider')
  return value
}

export function AuthProvider({ user, children }: { user: User; children: ReactNode }) {
  const queryClient = useQueryClient()
  const logoutMutation = useMutation({
    mutationFn: api.logout,
    onSettled: () => queryClient.clear(),
  })
  return (
    <AuthContext.Provider value={{ user, logout: logoutMutation.mutateAsync }}>
      {children}
    </AuthContext.Provider>
  )
}

export function SessionLoader({ children }: { children: (session: { user: User; csrf_token: string }) => ReactNode }) {
  const query = useQuery({ queryKey: ['session'], queryFn: api.me, retry: false })
  useEffect(() => {
    if (query.data?.csrf_token) setCsrfToken(query.data.csrf_token)
  }, [query.data])
  if (query.isLoading) return <div className="full-page">正在加载系统…</div>
  if (query.isError || !query.data) return <>{children({ user: null as never, csrf_token: '' })}</>
  return <>{children(query.data)}</>
}
