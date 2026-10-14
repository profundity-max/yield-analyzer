import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { LockKeyhole, UserRound } from 'lucide-react'
import { api, setCsrfToken } from '../api'

export function LoginPage() {
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const queryClient = useQueryClient()
  const login = useMutation({
    mutationFn: () => api.login(username, password),
    onSuccess: (session) => {
      setCsrfToken(session.csrf_token)
      queryClient.setQueryData(['session'], session)
    },
  })
  return (
    <div className="login-page">
      <div className="login-panel">
        <div className="login-brand">
          <div className="brand-mark large">DT</div>
          <div>
            <h1>AIM D-T 数据分析</h1>
            <p>内网数据分析与质量追溯平台</p>
          </div>
        </div>
        <form
          onSubmit={(event) => {
            event.preventDefault()
            login.mutate()
          }}
        >
          <label>
            <span>账号</span>
            <div className="input-with-icon">
              <UserRound size={18} />
              <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
            </div>
          </label>
          <label>
            <span>密码</span>
            <div className="input-with-icon">
              <LockKeyhole size={18} />
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
              />
            </div>
          </label>
          {login.isError && <div className="form-error">{login.error.message}</div>}
          <button className="button primary wide" disabled={login.isPending}>
            {login.isPending ? '登录中…' : '登录'}
          </button>
        </form>
      </div>
    </div>
  )
}
