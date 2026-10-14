import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Plus, Users } from 'lucide-react'
import { api } from '../api'
import type { Category, User } from '../types'

export function AdminPage() {
  const queryClient = useQueryClient()
  const specs = useQuery({ queryKey: ['specs'], queryFn: api.specs })
  const mappings = useQuery({ queryKey: ['mappings'], queryFn: api.mappings })
  const users = useQuery({ queryKey: ['users'], queryFn: api.users })
  const categories = useQuery({ queryKey: ['categories'], queryFn: () => api.categories(true) })
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState('viewer')
  const [categoryKind, setCategoryKind] = useState<'cell' | 'tester' | 'qpl'>('cell')
  const [categoryCode, setCategoryCode] = useState('')
  const [categoryLabel, setCategoryLabel] = useState('')
  const [message, setMessage] = useState('')

  const confirmSpec = useMutation({ mutationFn: api.confirmSpec, onSuccess: () => { setMessage('规格已激活。'); void queryClient.invalidateQueries({ queryKey: ['specs'] }) } })
  const createCategory = useMutation({
    mutationFn: () => api.createCategory({ kind: categoryKind, code: categoryCode, label: categoryLabel || categoryCode, sort_order: 0 }),
    onSuccess: () => { setCategoryCode(''); setCategoryLabel(''); setMessage('类别已新增。'); void queryClient.invalidateQueries({ queryKey: ['categories'] }) },
    onError: (error: Error) => setMessage(error.message),
  })
  const toggleCategory = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) => api.updateCategory(id, { active }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['categories'] }),
  })
  const createUser = useMutation({
    mutationFn: () => api.createUser(username, password, role),
    onSuccess: () => { setMessage(`用户 ${username} 已创建。`); setUsername(''); setPassword(''); void queryClient.invalidateQueries({ queryKey: ['users'] }) },
    onError: (error: Error) => setMessage(error.message),
  })

  return (
    <div className="page">
      <header className="page-header"><div><span className="eyebrow">配置与管理</span><h1>规则与管理</h1><p>Spec 和 Mapping 在分析结果页直接编辑，保存后自动生效并刷新图表。</p></div></header>
      {message && <div className="notice">{message}</div>}
      <div className="grid-2">
        <section className="panel">
          <div className="panel-title"><div><h2>规格版本</h2><p>默认标准规格启用 T1-T2 到 T1-T5。</p></div><CheckCircle2 /></div>
          <div className="list-stack">{(specs.data ?? []).map((spec) => <div className="admin-row" key={spec.id}><div><strong>{spec.name}</strong><small>{spec.enabled_points_json} · {spec.status}</small></div>{spec.status !== 'active' && <button className="button small primary" onClick={() => confirmSpec.mutate(spec.id)}>启用</button>}</div>)}</div>
        </section>

        <section className="panel">
          <div className="panel-title"><div><h2>Mapping 版本</h2><p>当前映射和待识别值在分析结果页编辑。</p></div></div>
          <div className="list-stack">{(mappings.data ?? []).map((mapping) => <div className="admin-row" key={mapping.id}><strong>{mapping.name}</strong><span className={`status ${mapping.status === 'active' ? 'ok' : ''}`}>{mapping.status}</span></div>)}</div>
        </section>

        <section className="panel">
          <div className="panel-title"><div><h2>类别管理</h2><p>预置 PPT 类别；停用不会破坏历史分析。</p></div></div>
          <div className="form-grid">
            <label>类型<select value={categoryKind} onChange={(e) => setCategoryKind(e.target.value as typeof categoryKind)}><option value="cell">Cell</option><option value="tester">Tester</option><option value="qpl">QPL</option></select></label>
            <label>代码<input value={categoryCode} onChange={(e) => setCategoryCode(e.target.value)} placeholder="Cell-7 / T11 / QPL4" /></label>
            <label>显示名称<input value={categoryLabel} onChange={(e) => setCategoryLabel(e.target.value)} /></label>
            <button className="button primary" disabled={!categoryCode} onClick={() => createCategory.mutate()}><Plus size={16} /> 新增类别</button>
          </div>
          <div className="category-grid">{(categories.data ?? []).map((item: Category) => <div className="category-chip" key={item.id}><div><strong>{item.label}</strong><small>{item.kind} · {item.code}</small></div><button className="button small ghost" onClick={() => toggleCategory.mutate({ id: item.id, active: !item.active })}>{item.active ? '停用' : '启用'}</button></div>)}</div>
        </section>

        <section className="panel">
          <div className="panel-title"><div><h2>账号管理</h2><p>新账号首次登录必须修改初始密码。</p></div><Users /></div>
          <div className="form-grid">
            <label>账号<input value={username} onChange={(e) => setUsername(e.target.value)} /></label>
            <label>初始密码<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
            <label>角色<select value={role} onChange={(e) => setRole(e.target.value)}><option value="viewer">viewer</option><option value="analyst">analyst</option><option value="admin">admin</option></select></label>
            <button className="button primary" disabled={!username || password.length < 10 || createUser.isPending} onClick={() => createUser.mutate()}><Plus size={16} /> 创建账号</button>
          </div>
          <div className="table-wrap compact"><table><thead><tr><th>账号</th><th>角色</th><th>状态</th><th>创建时间</th></tr></thead><tbody>{(users.data ?? []).map((user: User) => <tr key={user.id}><td>{user.username}</td><td>{user.role}</td><td>{user.is_active ? '启用' : '停用'}</td><td>{new Date(user.created_at).toLocaleString('zh-CN')}</td></tr>)}</tbody></table></div>
        </section>
      </div>
    </div>
  )
}
