import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Plus, Save, Users } from 'lucide-react'
import { api } from '../api'
import type { MappingVersion, SpecVersion, User } from '../types'

export function AdminPage() {
  const queryClient = useQueryClient()
  const specs = useQuery({ queryKey: ['specs'], queryFn: api.specs })
  const mappings = useQuery({ queryKey: ['mappings'], queryFn: api.mappings })
  const users = useQuery({ queryKey: ['users'], queryFn: api.users })
  const [mappingText, setMappingText] = useState(JSON.stringify([{ equipment_id: 'L1_P_Delta_T_1@965N1', site_name: 'V7X_P_Delta_T', config: 'V965N1', slot: '1', cell: 'Cell-1', tester: 'T01', qpl: 'QPL1' }], null, 2))
  const [mappingName, setMappingName] = useState('默认映射 V1')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState('viewer')
  const [message, setMessage] = useState('')
  const [specName, setSpecName] = useState('D-T 五点规格')
  const [pointsText, setPointsText] = useState('T1-T2, T1-T3, T1-T4, T1-T5, T1-T6')
  const [rulesText, setRulesText] = useState(JSON.stringify({ default: Object.fromEntries(['T1-T2', 'T1-T3', 'T1-T4', 'T1-T5', 'T1-T6'].map((point) => [point, { lsl: 0, usl: 2 }])), by_config: {} }, null, 2))

  const createSpec = useMutation({
    mutationFn: () =>
      api.createSpec({
        name: specName,
        enabled_points: pointsText.split(',').map((item) => item.trim()).filter(Boolean),
        rules: JSON.parse(rulesText),
      }),
    onSuccess: () => {
      setMessage('新规格草稿已创建。')
      void queryClient.invalidateQueries({ queryKey: ['specs'] })
    },
    onError: (error: Error) => setMessage(error.message),
  })
  const confirmSpec = useMutation({
    mutationFn: api.confirmSpec,
    onSuccess: () => {
      setMessage('规格已确认为 active 版本。')
      void queryClient.invalidateQueries({ queryKey: ['specs'] })
    },
  })
  const createMapping = useMutation({
    mutationFn: () => api.createMapping(mappingName, JSON.parse(mappingText)),
    onSuccess: () => {
      setMessage('Mapping 已保存并激活。')
      void queryClient.invalidateQueries({ queryKey: ['mappings'] })
    },
    onError: (error: Error) => setMessage(error.message),
  })
  const createUser = useMutation({
    mutationFn: () => api.createUser(username, password, role),
    onSuccess: () => {
      setMessage(`用户 ${username} 已创建。`)
      setUsername('')
      setPassword('')
      void queryClient.invalidateQueries({ queryKey: ['users'] })
    },
    onError: (error: Error) => setMessage(error.message),
  })

  return (
    <div className="page">
      <header className="page-header">
        <div><span className="eyebrow">仅 Admin 可见</span><h1>规则与管理</h1><p>确认规格、维护测试机映射、创建账号并保留审计。</p></div>
      </header>
      {message && <div className="notice">{message}</div>}
      <div className="grid-2">
        <section className="panel">
          <div className="panel-title"><div><h2>规格版本</h2><p>自动解析的候选规格必须确认后才能转为正式结果。</p></div><CheckCircle2 /></div>
          <div className="form-grid compact-form">
            <label>规格名称<input value={specName} onChange={(e) => setSpecName(e.target.value)} /></label>
            <label>启用点<input value={pointsText} onChange={(e) => setPointsText(e.target.value)} /></label>
            <label className="span-2">规则 JSON<textarea rows={7} value={rulesText} onChange={(e) => setRulesText(e.target.value)} /></label>
            <button className="button primary span-2" disabled={createSpec.isPending} onClick={() => createSpec.mutate()}>
              <Save size={16} /> 创建规格草稿
            </button>
          </div>
          <div className="list-stack">
            {(specs.data ?? []).map((spec: SpecVersion) => (
              <div className="admin-row" key={spec.id}>
                <div><strong>{spec.name}</strong><small>{spec.fingerprint.slice(0, 12)} · {spec.status}</small></div>
                {spec.status !== 'active' && (
                  <button className="button small primary" onClick={() => confirmSpec.mutate(spec.id)}>确认</button>
                )}
              </div>
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="panel-title"><div><h2>Mapping 版本</h2><p>规则按匹配条件最具体的记录生效。</p></div><Save /></div>
          <div className="form-grid">
            <label className="span-2">版本名称<input value={mappingName} onChange={(e) => setMappingName(e.target.value)} /></label>
            <label className="span-2">规则 JSON<textarea rows={9} value={mappingText} onChange={(e) => setMappingText(e.target.value)} /></label>
            <button className="button primary span-2" disabled={createMapping.isPending} onClick={() => createMapping.mutate()}>
              <Save size={16} /> 保存并激活 Mapping
            </button>
          </div>
          <div className="list-stack compact">
            {(mappings.data ?? []).map((mapping: MappingVersion) => (
              <div className="admin-row" key={mapping.id}><strong>{mapping.name}</strong><span className="status ok">{mapping.status}</span></div>
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="panel-title"><div><h2>账号管理</h2><p>新账号首次登录必须修改初始密码。</p></div><Users /></div>
          <div className="form-grid">
            <label>账号<input value={username} onChange={(e) => setUsername(e.target.value)} /></label>
            <label>初始密码<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
            <label>角色<select value={role} onChange={(e) => setRole(e.target.value)}><option value="viewer">viewer</option><option value="analyst">analyst</option><option value="admin">admin</option></select></label>
            <button className="button primary" disabled={!username || password.length < 10 || createUser.isPending} onClick={() => createUser.mutate()}><Plus size={16} /> 创建账号</button>
          </div>
          <div className="table-wrap compact">
            <table><thead><tr><th>账号</th><th>角色</th><th>状态</th><th>创建时间</th></tr></thead><tbody>
              {(users.data ?? []).map((user: User) => <tr key={user.id}><td>{user.username}</td><td>{user.role}</td><td>{user.is_active ? '启用' : '停用'}</td><td>{new Date(user.created_at).toLocaleString('zh-CN')}</td></tr>)}
            </tbody></table>
          </div>
        </section>
      </div>
    </div>
  )
}
