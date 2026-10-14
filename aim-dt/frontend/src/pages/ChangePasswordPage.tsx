import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { KeyRound } from 'lucide-react'
import { api } from '../api'

export function ChangePasswordPage() {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const queryClient = useQueryClient()
  const change = useMutation({
    mutationFn: () => api.changePassword(currentPassword, newPassword),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['session'] }),
  })
  const mismatch = confirmPassword.length > 0 && newPassword !== confirmPassword
  return (
    <div className="login-page">
      <div className="login-panel">
        <div className="login-brand">
          <div className="brand-mark large"><KeyRound /></div>
          <div><h1>修改初始密码</h1><p>新密码至少 10 位，修改后继续进入工作台。</p></div>
        </div>
        <form onSubmit={(event) => { event.preventDefault(); change.mutate() }}>
          <label>当前密码<input type="password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} /></label>
          <label>新密码<input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} /></label>
          <label>确认新密码<input type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} /></label>
          {mismatch && <div className="form-error">两次输入的新密码不一致。</div>}
          {change.isError && <div className="form-error">{change.error.message}</div>}
          <button className="button primary wide" disabled={mismatch || newPassword.length < 10 || change.isPending}>确认修改</button>
        </form>
      </div>
    </div>
  )
}
