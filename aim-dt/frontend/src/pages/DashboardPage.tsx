import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, FileSpreadsheet, Plus, RefreshCw, Trash2, UploadCloud } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import type { AnalysisRun, Batch } from '../types'

function statusClass(value: string) {
  if (['ready', 'completed'].includes(value)) return 'status ok'
  if (['failed', 'cancelled'].includes(value)) return 'status bad'
  if (['completed_with_warnings'].includes(value)) return 'status warn'
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
  const [selectedBatches, setSelectedBatches] = useState<string[]>([])
  const [selectedSpec, setSelectedSpec] = useState('')
  const [selectedMapping, setSelectedMapping] = useState('')

  const batchesQuery = useQuery({ queryKey: ['batches'], queryFn: api.batches, refetchInterval: 2500 })
  const analysesQuery = useQuery({ queryKey: ['analyses'], queryFn: api.analyses, refetchInterval: 2500 })
  const specsQuery = useQuery({ queryKey: ['specs'], queryFn: api.specs })
  const mappingsQuery = useQuery({ queryKey: ['mappings'], queryFn: api.mappings })

  const upload = useMutation({
    mutationFn: () => api.uploadBatch(selectedFile!),
    onSuccess: () => {
      setSelectedFile(null)
      void queryClient.invalidateQueries({ queryKey: ['batches'] })
      void queryClient.invalidateQueries({ queryKey: ['analyses'] })
    },
  })
  const removeBatch = useMutation({
    mutationFn: api.deleteBatch,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['batches'] }),
  })
  const createAnalysis = useMutation({
    mutationFn: () =>
      api.createAnalysis({
        name: `AIM D-T 分析 ${new Date().toLocaleString('zh-CN')}`,
        batch_ids: selectedBatches,
        spec_version_id: selectedSpec,
        mapping_version_id: selectedMapping || null,
      }),
    onSuccess: () => {
      setSelectedBatches([])
      void queryClient.invalidateQueries({ queryKey: ['analyses'] })
    },
  })

  const readyBatches = useMemo(() => (batchesQuery.data ?? []).filter((batch) => batch.status === 'ready'), [batchesQuery.data])
  const activeSpecs = useMemo(() => (specsQuery.data ?? []).filter((item) => item.status !== 'retired'), [specsQuery.data])
  const activeMappings = useMemo(() => (mappingsQuery.data ?? []).filter((item) => item.status === 'active'), [mappingsQuery.data])

  useEffect(() => {
    if (!selectedSpec && activeSpecs.length) setSelectedSpec(activeSpecs[0].id)
  }, [activeSpecs, selectedSpec])
  useEffect(() => {
    if (!selectedMapping && activeMappings.length) setSelectedMapping(activeMappings[0].id)
  }, [activeMappings, selectedMapping])

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <span className="eyebrow">AIM D-T · V1.1</span>
          <h1>分析中心</h1>
          <p>上传原始数据、查看后台任务，并进入 PPT 对应的结果看板。</p>
        </div>
        <button className="icon-button" onClick={() => {
          void queryClient.invalidateQueries()
        }}><RefreshCw size={18} /></button>
      </header>

      {canUpload && (
        <section className="panel upload-panel">
          <div className="panel-title">
            <div><h2>上传原始数据</h2><p>支持 XLSX、CSV；文件先进入后台解析和去重队列。</p></div>
            <UploadCloud size={28} />
          </div>
          <div className="upload-row">
            <label className="file-drop">
              <FileSpreadsheet size={34} />
              <strong>{selectedFile ? selectedFile.name : '选择 XLSX / CSV 文件'}</strong>
              <span>单文件上限 1 GB；大文件不会阻塞浏览器</span>
              <input
                type="file"
                accept=".xlsx,.csv"
                onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
              />
            </label>
            <button className="button primary" disabled={!selectedFile || upload.isPending} onClick={() => upload.mutate()}>
              {upload.isPending ? '上传中…' : '开始上传'}
            </button>
          </div>
          {upload.isError && <div className="form-error">{upload.error.message}</div>}
        </section>
      )}

      <section className="grid-2">
        <div className="panel">
          <div className="panel-title"><div><h2>数据批次</h2><p>每个文件形成独立不可变批次，按时间滚动合并。</p></div></div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>文件</th><th>状态</th><th>原始行</th><th>去重事件</th><th>大小</th><th /></tr></thead>
              <tbody>
                {(batchesQuery.data ?? []).map((batch: Batch) => (
                  <tr key={batch.id}>
                    <td><strong>{batch.original_name}</strong><small>{new Date(batch.created_at).toLocaleString('zh-CN')}</small></td>
                    <td><span className={statusClass(batch.status)}>{batch.status}</span></td>
                    <td>{batch.row_count.toLocaleString()}</td>
                    <td>{batch.event_count.toLocaleString()}</td>
                    <td>{bytes(batch.file_size)}</td>
                    <td>
                      {user.role === 'admin' && (
                        <button
                          className="icon-button danger"
                          title="删除批次"
                          onClick={() => {
                            if (window.confirm(`确认删除 ${batch.original_name}？`)) removeBatch.mutate(batch.id)
                          }}
                        ><Trash2 size={16} /></button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!batchesQuery.data?.length && <Empty text="尚无上传批次" />}
          </div>
        </div>

        <div className="panel">
          <div className="panel-title"><div><h2>新建分析</h2><p>选择 ready 批次和规格版本；Mapping 未配置时结果会告警。</p></div></div>
          <div className="form-grid">
            <label className="span-2">数据批次
              <div className="check-list">
                {readyBatches.map((batch: Batch) => (
                  <label className="check-item" key={batch.id}>
                    <input
                      type="checkbox"
                      checked={selectedBatches.includes(batch.id)}
                      onChange={(event) => setSelectedBatches((current) =>
                        event.target.checked ? [...current, batch.id] : current.filter((id) => id !== batch.id)
                      )}
                    />
                    <span>{batch.original_name}<small>{batch.event_count} events</small></span>
                  </label>
                ))}
                {!readyBatches.length && <span className="muted">等待批次解析完成</span>}
              </div>
            </label>
            <label>规格版本
              <select value={selectedSpec} onChange={(e) => setSelectedSpec(e.target.value)}>
                {activeSpecs.map((spec) => (
                  <option key={spec.id} value={spec.id}>{spec.name} · {spec.status}</option>
                ))}
              </select>
            </label>
            <label>Mapping 版本
              <select value={selectedMapping} onChange={(e) => setSelectedMapping(e.target.value)}>
                <option value="">未配置</option>
                {activeMappings.map((mapping) => <option key={mapping.id} value={mapping.id}>{mapping.name}</option>)}
              </select>
            </label>
            <button
              className="button primary span-2"
              disabled={!selectedBatches.length || !selectedSpec || createAnalysis.isPending}
              onClick={() => createAnalysis.mutate()}
            ><Plus size={18} /> 创建分析任务</button>
            {createAnalysis.isError && <div className="form-error span-2">{createAnalysis.error.message}</div>}
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-title"><div><h2>分析任务</h2><p>点击任务进入总览、趋势、柏拉图、Cell/Tester 和明细页面。</p></div><Activity size={24} /></div>
        <div className="analysis-grid">
          {(analysesQuery.data ?? []).map((run: AnalysisRun) => (
            <Link className="analysis-card" to={`/analyses/${run.id}`} key={run.id}>
              <div className="analysis-card-head">
                <strong>{run.name}</strong>
                <span className={statusClass(run.status)}>{run.status}</span>
              </div>
              <div className="progress"><span style={{ width: `${Math.min(run.progress, 100)}%` }} /></div>
              <div className="analysis-card-foot"><span>{run.phase}</span><span>{new Date(run.created_at).toLocaleString('zh-CN')}</span></div>
              {run.error_message && <p className="error-text">{run.error_message}</p>}
            </Link>
          ))}
          {!analysesQuery.data?.length && <Empty text="尚无分析任务" />}
        </div>
      </section>
    </div>
  )
}

function Empty({ text }: { text: string }) {
  return <div className="empty-state">{text}</div>
}
