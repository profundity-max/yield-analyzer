import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileSpreadsheet, RefreshCw, RotateCcw, UploadCloud } from 'lucide-react'
import { api } from '../api'
import { useAuth } from '../auth'
import { AnalysisWorkspace } from '../components/AnalysisWorkspace'

function triggerLabel(value: string) {
  return {
    upload_file: '上传文件',
    replace_file: '替换文件',
    revert_file: '恢复上一版本',
    spec_change: '修改 Spec',
    mapping_change: '修改 Mapping',
    manual_refresh: '手动刷新',
    history_import: '历史迁移',
  }[value] ?? value
}

export function DashboardPage() {
  const { user } = useAuth()
  const canEdit = user.role === 'admin' || user.role === 'analyst'
  const queryClient = useQueryClient()
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const masterQuery = useQuery({
    queryKey: ['master-workbench'],
    queryFn: api.masterWorkbench,
    refetchInterval: (query) => {
      const status = query.state.data?.analysis_status
      return status && ['queued', 'running'].includes(status) ? 1500 : 5000
    },
  })
  const upload = useMutation({
    mutationFn: () => api.uploadBatch(selectedFile!),
    onSuccess: () => {
      setSelectedFile(null)
      void queryClient.invalidateQueries({ queryKey: ['master-workbench'] })
    },
  })
  const refresh = useMutation({
    mutationFn: api.refreshMaster,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['master-workbench'] }),
  })
  const replace = useMutation({
    mutationFn: ({ moduleId, file }: { moduleId: string; file: File }) => api.replaceModule(moduleId, file),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['master-workbench'] }),
  })
  const revert = useMutation({
    mutationFn: api.revertModule,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['master-workbench'] }),
  })
  const master = masterQuery.data
  const activeAnalysisId = useMemo(() => {
    if (!master) return null
    if (master.analysis_status && ['completed', 'completed_with_warnings'].includes(master.analysis_status)) {
      return master.current_analysis_id
    }
    return master.last_success_analysis_id ?? master.current_analysis_id
  }, [master])

  return (
    <div className="page">
      <header className="page-header">
        <div><span className="eyebrow">AIM D-T · V3.0</span><h1>分析中心</h1><p>所有上传文件合并为一个总数据源；修改配置后只刷新这一份数据源。</p></div>
        <div className="header-actions">
          {canEdit && <button className="button ghost" disabled={refresh.isPending || !master?.module_count} onClick={() => refresh.mutate()}><RefreshCw size={16} /> 刷新总数据源</button>}
          <button className="icon-button" onClick={() => void queryClient.invalidateQueries()}><RefreshCw size={18} /></button>
        </div>
      </header>

      {canEdit && (
        <section className="panel upload-panel">
          <div className="panel-title"><div><h2>追加数据文件</h2><p>新文件成为总数据源中的一个数据模块，不会覆盖已有模块。</p></div><UploadCloud size={28} /></div>
          <div className="upload-row">
            <label className="file-drop"><FileSpreadsheet size={34} /><strong>{selectedFile ? selectedFile.name : '选择 XLSX / CSV 文件'}</strong><span>Active Spec 和 Active Mapping 自动用于总数据源</span><input type="file" accept=".xlsx,.csv" onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)} /></label>
            <button className="button primary" disabled={!selectedFile || upload.isPending} onClick={() => upload.mutate()}>{upload.isPending ? '上传中…' : '上传并合并'}</button>
          </div>
          {upload.isError && <div className="form-error">{upload.error.message}</div>}
        </section>
      )}

      {master && (
        <section className="panel master-summary">
          <div className="panel-title"><div><h2>{master.name}</h2><p>{master.analysis_status ?? '尚无分析'} · {master.stage} · {master.progress.toFixed(1)}%</p></div></div>
          <div className="progress large"><span style={{ width: `${Math.min(master.progress, 100)}%` }} /></div>
          <div className="quality-grid master-metrics">
            <div><span>数据模块</span><strong>{master.module_count}</strong></div>
            <div><span>原始行数</span><strong>{master.total_rows.toLocaleString()}</strong></div>
            <div><span>去重事件</span><strong>{master.total_events.toLocaleString()}</strong></div>
            <div><span>未映射事件</span><strong>{master.unmatched_count.toLocaleString()}</strong></div>
          </div>
          {master.unmatched_count > 0 && <div className="warning-banner"><strong>待映射</strong><span>总数据源仍有 {master.unmatched_count} 个事件未匹配，可在图表区打开 Mapping 配置。</span></div>}
          {master.error_message && <div className="form-error">{master.error_message}</div>}
        </section>
      )}

      {activeAnalysisId && (
        <section className="embedded-result">
          <AnalysisWorkspace analysisId={activeAnalysisId} masterMode embedded onMasterRefresh={() => void queryClient.invalidateQueries({ queryKey: ['master-workbench'] })} />
        </section>
      )}

      <section className="panel">
        <div className="panel-title"><div><h2>数据模块</h2><p>每个上传文件是一个模块；“替换文件”会完整替换当前模块内容并刷新总数据源。</p></div></div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>模块文件</th><th>当前版本</th><th>数据量</th><th>上传时间</th><th>上一版本</th><th>操作</th></tr></thead>
            <tbody>
              {(master?.modules ?? []).map((module) => (
                <tr key={module.id}>
                  <td><strong>{module.active_filename || module.name}</strong><small>模块 ID: {module.id.slice(0, 8)}</small></td>
                  <td>Rev.{module.active_revision}<span className={`status ${module.status === 'ready' ? 'ok' : 'pending'}`}>{module.status}</span></td>
                  <td>{module.row_count.toLocaleString()} 行<small>{module.event_count.toLocaleString()} 事件</small></td>
                  <td>{new Date(module.uploaded_at).toLocaleString('zh-CN')}</td>
                  <td>{module.previous_filename ? <><strong>{module.previous_filename}</strong><small>Rev.{module.previous_revision}</small></> : '无'}</td>
                  <td><div className="row-actions">
                    {canEdit && <label className="button small ghost">替换文件<input className="hidden" type="file" accept=".xlsx,.csv" onChange={(event) => { const file = event.target.files?.[0]; if (file) replace.mutate({ moduleId: module.id, file }); event.target.value = '' }} /></label>}
                    {canEdit && module.previous_available && <button className="button small ghost" onClick={() => { if (window.confirm('确认恢复上一版本并刷新总数据源？')) revert.mutate(module.id) }}><RotateCcw size={14} /> 恢复上一版</button>}
                  </div></td>
                </tr>
              ))}
              {!master?.modules.length && <tr><td colSpan={6}><div className="empty-state">尚未上传数据模块</div></td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <div className="panel-title"><div><h2>上传与刷新日志</h2><p>历史分析不再单独堆在首页；这里保留文件、替换、配置和刷新记录。</p></div></div>
        <div className="table-wrap compact-log">
          <table><thead><tr><th>时间</th><th>操作</th><th>模块</th><th>文件变化</th><th>状态</th></tr></thead><tbody>
            {(master?.logs ?? []).map((log) => <tr key={log.id}><td>{new Date(log.created_at).toLocaleString('zh-CN')}</td><td>{triggerLabel(log.trigger)}</td><td>{log.module_name || '—'}</td><td>{log.from_filename && log.to_filename ? `${log.from_filename} → ${log.to_filename}` : log.to_filename || '—'}</td><td><span className={`status ${log.status === 'completed' ? 'ok' : log.status === 'failed' ? 'bad' : 'pending'}`}>{log.status}</span></td></tr>)}
          </tbody></table>
        </div>
      </section>
    </div>
  )
}
