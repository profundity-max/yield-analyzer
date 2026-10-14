import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, FileSpreadsheet, RefreshCw, Trash2, UploadCloud } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import { AnalysisWorkspace } from '../components/AnalysisWorkspace'

function statusClass(value: string) {
  if (['ready', 'completed'].includes(value)) return 'status ok'
  if (['failed', 'cancelled'].includes(value)) return 'status bad'
  if (['completed_with_warnings', 'needs_configuration'].includes(value)) return 'status warn'
  return 'status pending'
}

function bytes(value: number) {
  if (value > 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`
  if (value > 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${value} B`
}

export function DashboardPage() {
  const { user } = useAuth()
  const canUpload = user.role === 'admin' || user.role === 'analyst'
  const queryClient = useQueryClient()
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [activeBatchId, setActiveBatchId] = useState<string | null>(null)
  const [activeAnalysisId, setActiveAnalysisId] = useState<string | null>(null)
  const batchesQuery = useQuery({ queryKey: ['batches'], queryFn: api.batches, refetchInterval: 3000 })
  const analysesQuery = useQuery({ queryKey: ['analyses'], queryFn: api.analyses, refetchInterval: 3000 })
  const workbenchQuery = useQuery({
    queryKey: ['workbench', activeBatchId],
    queryFn: () => api.workbench(activeBatchId!),
    enabled: Boolean(activeBatchId),
    refetchInterval: (query) => {
      const data = query.state.data
      return data?.analysis_id && ['completed', 'completed_with_warnings', 'failed', 'needs_configuration'].includes(data.analysis_status ?? '') ? false : 2000
    },
  })
  const upload = useMutation({
    mutationFn: () => api.uploadBatch(selectedFile!),
    onSuccess: (batch) => {
      setSelectedFile(null)
      setActiveBatchId(batch.id)
      setActiveAnalysisId(null)
      void queryClient.invalidateQueries({ queryKey: ['batches'] })
      void queryClient.invalidateQueries({ queryKey: ['analyses'] })
    },
  })
  const removeBatch = useMutation({
    mutationFn: api.deleteBatch,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['batches'] })
      void queryClient.invalidateQueries({ queryKey: ['analyses'] })
    },
  })
  useEffect(() => {
    const data = workbenchQuery.data
    if (!data?.analysis_id) return
    setActiveAnalysisId(data.analysis_id)
    if (['completed', 'completed_with_warnings', 'failed', 'needs_configuration'].includes(data.analysis_status ?? '')) {
      void queryClient.invalidateQueries({ queryKey: ['batches'] })
      void queryClient.invalidateQueries({ queryKey: ['analyses'] })
    }
  }, [queryClient, workbenchQuery.data])
  const activeWorkbench = workbenchQuery.data

  return (
    <div className="page">
      <header className="page-header">
        <div><span className="eyebrow">AIM D-T · V2.0</span><h1>分析中心</h1><p>上传后在当前页面自动解析、分析并展示结果图。</p></div>
        <button className="icon-button" onClick={() => void queryClient.invalidateQueries()}><RefreshCw size={18} /></button>
      </header>

      {canUpload && (
        <section className="panel upload-panel">
          <div className="panel-title"><div><h2>上传原始数据</h2><p>系统自动使用当前 Spec 和 Mapping；没有映射时仍会先出通用图。</p></div><UploadCloud size={28} /></div>
          <div className="upload-row">
            <label className="file-drop">
              <FileSpreadsheet size={34} />
              <strong>{selectedFile ? selectedFile.name : '选择 XLSX / CSV 文件'}</strong>
              <span>默认仅启用 T1-T2 到 T1-T5；文件内嵌 USL/LSL 优先</span>
              <input type="file" accept=".xlsx,.csv" onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)} />
            </label>
            <button className="button primary" disabled={!selectedFile || upload.isPending} onClick={() => upload.mutate()}>{upload.isPending ? '上传中…' : '上传并分析'}</button>
          </div>
          {upload.isError && <div className="form-error">{upload.error.message}</div>}
        </section>
      )}

      {activeBatchId && activeWorkbench && (
        <section className="panel live-workbench">
          <div className="panel-title"><div><h2>当前数据处理</h2><p>{activeWorkbench.stage} · {activeWorkbench.progress.toFixed(1)}%</p></div><Activity /></div>
          <div className="progress large"><span style={{ width: `${Math.min(activeWorkbench.progress, 100)}%` }} /></div>
          {activeWorkbench.unmatched_count > 0 && <div className="warning-banner"><strong>待映射</strong><span>{activeWorkbench.unmatched_count} 个事件尚未匹配 Cell/Tester/QPL，可先查看图表，再在上方 Mapping 中补全。</span></div>}
          {activeWorkbench.error_message && <div className="form-error">{activeWorkbench.error_message}</div>}
        </section>
      )}

      {activeAnalysisId && (
        <section className="embedded-result">
          <AnalysisWorkspace analysisId={activeAnalysisId} batchId={activeBatchId ?? undefined} embedded onRunChange={setActiveAnalysisId} />
        </section>
      )}

      <section className="grid-2">
        <div className="panel">
          <div className="panel-title"><div><h2>数据批次</h2><p>每个上传文件保持独立，可在历史分析中追溯。</p></div></div>
          <div className="table-wrap"><table><thead><tr><th>文件</th><th>状态</th><th>原始行</th><th>事件</th><th>大小</th><th /></tr></thead><tbody>
            {(batchesQuery.data ?? []).map((batch) => <tr key={batch.id}><td><strong>{batch.original_name}</strong><small>{new Date(batch.created_at).toLocaleString('zh-CN')}</small></td><td><span className={statusClass(batch.status)}>{batch.status}</span></td><td>{batch.row_count.toLocaleString()}</td><td>{batch.event_count.toLocaleString()}</td><td>{bytes(batch.file_size)}</td><td>{user.role === 'admin' && <button className="icon-button danger" onClick={() => { if (window.confirm(`确认删除 ${batch.original_name}？`)) removeBatch.mutate(batch.id) }}><Trash2 size={16} /></button>}</td></tr>)}
          </tbody></table></div>
        </div>
        <div className="panel">
          <div className="panel-title"><div><h2>历史分析</h2><p>每次切换 Spec 或 Mapping 都会新建一个可追溯快照。</p></div></div>
          <div className="analysis-grid compact-grid">
            {(analysesQuery.data ?? []).slice(0, 12).map((run) => <Link className="analysis-card" to={`/analyses/${run.id}`} key={run.id}><div className="analysis-card-head"><strong>{run.name}</strong><span className={statusClass(run.status)}>{run.status}</span></div><div className="analysis-card-foot"><span>{run.phase}</span><span>{new Date(run.created_at).toLocaleString('zh-CN')}</span></div></Link>)}
          </div>
        </div>
      </section>
    </div>
  )
}
