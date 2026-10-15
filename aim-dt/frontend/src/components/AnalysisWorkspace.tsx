import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, FileText, RotateCcw, Settings2, Square } from 'lucide-react'
import { api } from '../api'
import { useAuth } from '../auth'
import { CellYieldPanel, DistributionPanel, KpiGrid, ParetoChart, TesterYieldPanel, TimeYieldChart, formatPct } from './Charts'
import { MappingEditorModal, SpecEditorModal } from './ConfigEditors'
import type { EventRow, Summary } from '../types'

const tabs = ['总览', '时良率', '柏拉图', 'Cell', 'Tester', '分布', '明细'] as const
type Tab = (typeof tabs)[number]

interface Props {
  analysisId: string
  batchId?: string
  onRunChange?: (id: string) => void
  onMasterRefresh?: () => void
  masterMode?: boolean
  embedded?: boolean
}

export function AnalysisWorkspace({
  analysisId,
  batchId,
  onRunChange,
  onMasterRefresh,
  masterMode = false,
  embedded = false,
}: Props) {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const canEdit = user.role === 'admin' || user.role === 'analyst'
  const [tab, setTab] = useState<Tab>('总览')
  const [page, setPage] = useState(1)
  const [snFilter, setSnFilter] = useState('')
  const [outcomeFilter, setOutcomeFilter] = useState('')
  const [specOpen, setSpecOpen] = useState(false)
  const [mappingOpen, setMappingOpen] = useState(false)

  const runQuery = useQuery({
    queryKey: ['analysis', analysisId],
    queryFn: () => api.analysis(analysisId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && ['completed', 'completed_with_warnings', 'needs_configuration', 'failed', 'cancelled'].includes(status) ? false : 2000
    },
    enabled: Boolean(analysisId),
  })
  const complete = runQuery.data && ['completed', 'completed_with_warnings'].includes(runQuery.data.status)
  const batchIds = runQuery.data ? (JSON.parse(runQuery.data.filters_json).batch_ids ?? []) : []
  const effectiveBatchId = batchId || batchIds[0]
  const optionsQuery = useQuery({
    queryKey: ['config-options', effectiveBatchId],
    queryFn: () => api.configOptions(effectiveBatchId),
    enabled: Boolean(masterMode || effectiveBatchId),
  })
  const summaryQuery = useQuery({
    queryKey: ['summary', analysisId],
    queryFn: () => api.summary(analysisId),
    enabled: Boolean(complete),
  })
  const detailQuery = useQuery({
    queryKey: ['events', analysisId, page, snFilter, outcomeFilter],
    queryFn: () => api.events(analysisId, page, 50, `${snFilter ? `&sn=${encodeURIComponent(snFilter)}` : ''}${outcomeFilter ? `&outcome=${outcomeFilter}` : ''}`),
    enabled: Boolean(complete) && tab === '明细',
    placeholderData: (previous) => previous,
  })
  const rerun = useMutation({
    mutationFn: ({ specId, mappingId }: { specId: string; mappingId: string | null }) =>
      api.rerunWith(analysisId, specId, mappingId),
    onSuccess: (run) => {
      setSpecOpen(false)
      setMappingOpen(false)
      void queryClient.invalidateQueries({ queryKey: ['analysis', run.id] })
      if (effectiveBatchId) {
        void queryClient.invalidateQueries({ queryKey: ['workbench', effectiveBatchId] })
      }
      onRunChange?.(run.id)
    },
  })
  const cancel = useMutation({
    mutationFn: () => api.cancelAnalysis(analysisId),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['analysis', analysisId] }),
  })
  const retry = useMutation({
    mutationFn: () => api.retryAnalysis(analysisId),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['analysis', analysisId] }),
  })

  useEffect(() => {
    if (runQuery.data?.status === 'needs_configuration' && canEdit) setSpecOpen(true)
  }, [runQuery.data?.status, canEdit])

  if (runQuery.isLoading) return <div className="empty-state">正在加载分析结果…</div>
  if (runQuery.isError || !runQuery.data) return <div className="form-error">分析任务不存在</div>
  const run = runQuery.data

  const changeSpec = (specId: string) => {
    setSpecOpen(false)
    setMappingOpen(false)
    rerun.mutate({
      specId,
      mappingId: run.mapping_version_id ?? optionsQuery.data?.active_mapping_id ?? null,
    })
  }
  const changeMapping = (mappingId: string) => {
    setSpecOpen(false)
    setMappingOpen(false)
    rerun.mutate({ specId: run.spec_version_id, mappingId })
  }
  const currentSpecName = optionsQuery.data?.specs.find((item) => item.id === run.spec_version_id)?.name ?? run.spec_version_id
  const currentMappingName = optionsQuery.data?.mappings.find((item) => item.id === run.mapping_version_id)?.name ?? 'Unassigned'

  return (
    <div className={embedded ? 'workspace embedded' : 'workspace'}>
      <div className="workspace-header">
        <div>
          <h2>{run.name}</h2>
          <p>{run.status} · {run.phase} · {run.progress.toFixed(1)}%</p>
        </div>
        <div className="header-actions">
          {canEdit && (masterMode || effectiveBatchId) && (
            <>
              {masterMode ? (
                <>
                  <span className="version-chip">Spec: {currentSpecName}</span>
                  <span className="version-chip">Mapping: {currentMappingName}</span>
                </>
              ) : (
                <>
                  <select
                    aria-label="Spec 版本"
                    value={run.spec_version_id}
                    onChange={(event) => changeSpec(event.target.value)}
                    disabled={rerun.isPending}
                  >
                    {optionsQuery.data?.specs.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.status}</option>)}
                  </select>
                  <select
                    aria-label="Mapping 版本"
                    value={run.mapping_version_id ?? ''}
                    onChange={(event) => changeMapping(event.target.value)}
                    disabled={rerun.isPending}
                  >
                    <option value="">Unassigned</option>
                    {optionsQuery.data?.mappings.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.status}</option>)}
                  </select>
                </>
              )}
              <button className="button ghost" onClick={() => setSpecOpen(true)}><Settings2 size={16} /> Spec</button>
              <button className="button ghost" onClick={() => setMappingOpen(true)}><Settings2 size={16} /> Mapping</button>
            </>
          )}
          {['queued', 'running'].includes(run.status) && <button className="button ghost" onClick={() => cancel.mutate()}><Square size={16} /> 取消</button>}
          {['failed', 'cancelled', 'needs_configuration'].includes(run.status) && <button className="button ghost" onClick={() => retry.mutate()}><RotateCcw size={16} /> 重试</button>}
          {complete && (
            <>
              <a className="button ghost" href={`/api/v1/analyses/${analysisId}/exports/summary.xlsx`}><Download size={16} /> 汇总</a>
              <a className="button ghost" href={`/api/v1/analyses/${analysisId}/exports/details.csv`}><FileText size={16} /> 明细</a>
            </>
          )}
        </div>
      </div>

      {rerun.isError && (
        <div className="form-error">
          配置已保存，但重新分析失败：{rerun.error.message}
        </div>
      )}

      {!complete && (
        <section className="panel running-panel">
          <strong>{run.status === 'needs_configuration' ? '需要确认规格配置' : '任务正在后台处理'}</strong>
          <div className="progress large"><span style={{ width: `${run.progress}%` }} /></div>
          <p>{run.error_message || '页面可保持打开，后台任务会持续处理。'}</p>
        </section>
      )}

      {summaryQuery.isError && <div className="panel form-error">{summaryQuery.error.message}</div>}
      {summaryQuery.data && (
        <>
          {summaryQuery.data.meta.warnings.length > 0 && (
            <div className="warning-banner"><strong>质量提示</strong><span>{summaryQuery.data.meta.warnings.join('；')}</span></div>
          )}
          <nav className="tabs">
            {tabs.map((item) => <button className={tab === item ? 'active' : ''} onClick={() => setTab(item)} key={item}>{item}</button>)}
          </nav>
          {tab === '总览' && <Overview summary={summaryQuery.data} />}
          {tab === '时良率' && <div className="panel"><h2>By Time Yield Chart</h2><TimeYieldChart rows={summaryQuery.data.time_yield} /></div>}
          {tab === '柏拉图' && <div className="panel"><h2>Top Yield Loss Pareto</h2><ParetoChart rows={summaryQuery.data.pareto} /></div>}
          {tab === 'Cell' && <div className="panel"><h2>By Cell Yield Summary</h2><CellYieldPanel rows={summaryQuery.data.cell_yield} /></div>}
          {tab === 'Tester' && <div className="panel"><h2>Production By Tester</h2><TesterYieldPanel rows={summaryQuery.data.tester_yield} /></div>}
          {tab === '分布' && <div className="panel"><h2>Test Point Distribution</h2><DistributionPanel summary={summaryQuery.data} /></div>}
          {tab === '明细' && <DetailPanel page={page} setPage={setPage} snFilter={snFilter} setSnFilter={setSnFilter} outcomeFilter={outcomeFilter} setOutcomeFilter={setOutcomeFilter} data={detailQuery.data} loading={detailQuery.isLoading} />}
        </>
      )}

      {specOpen && canEdit && (
        <SpecEditorModal
          batchId={masterMode ? undefined : effectiveBatchId}
          specId={run.spec_version_id}
          onClose={() => setSpecOpen(false)}
          onSaved={(specId) => {
            setSpecOpen(false)
            if (masterMode) onMasterRefresh?.()
            else changeSpec(specId)
          }}
        />
      )}
      {mappingOpen && canEdit && (masterMode || effectiveBatchId) && (
        <MappingEditorModal
          batchId={masterMode ? undefined : effectiveBatchId}
          mappingId={run.mapping_version_id ?? undefined}
          onClose={() => setMappingOpen(false)}
          onSaved={(mappingId) => {
            setMappingOpen(false)
            if (masterMode) onMasterRefresh?.()
            else changeMapping(mappingId)
          }}
        />
      )}
    </div>
  )
}

function Overview({ summary }: { summary: Summary }) {
  const current = summary.cell_yield.reduce((state, row) => ({ first: state.first + row.first_pass, retest: state.retest + row.retest_pass, ng: state.ng + row.final_ng }), { first: 0, retest: 0, ng: 0 })
  return (
    <div className="stack">
      <KpiGrid kpis={summary.kpis} />
      <div className="grid-2">
        <div className="panel"><h2>结果构成</h2><div className="summary-bars">
          <SummaryBar label="First Pass" value={current.first} total={summary.kpis.total_input} color="#19a974" />
          <SummaryBar label="Retest Pass" value={current.retest} total={summary.kpis.total_input} color="#f4b942" />
          <SummaryBar label="Final NG" value={current.ng} total={summary.kpis.total_input} color="#d64545" />
        </div><p className="muted">最终良率 {formatPct(summary.kpis.final_pass_rate)}，复测通过率 {formatPct(summary.kpis.retest_pass_rate)}。</p></div>
        <div className="panel"><h2>数据质量</h2><div className="quality-grid">
          <div><span>去重事件</span><strong>{summary.meta.event_count.toLocaleString()}</strong></div>
          <div><span>Error 事件</span><strong>{summary.kpis.error_event_qty.toLocaleString()}</strong></div>
          <div><span>原始结果冲突</span><strong>{summary.kpis.mismatch_event_qty.toLocaleString()}</strong></div>
          <div><span>未复测 NG</span><strong>{summary.kpis.unretested_ng_qty.toLocaleString()}</strong></div>
        </div></div>
      </div>
      <div className="panel"><h2>By Time Yield Chart</h2><TimeYieldChart rows={summary.time_yield} /></div>
    </div>
  )
}

function SummaryBar({ label, value, total, color }: { label: string; value: number; total: number; color: string }) {
  const width = total ? (value / total) * 100 : 0
  return <div className="summary-bar"><div><span>{label}</span><strong>{value.toLocaleString()}</strong></div><div className="bar-track"><span style={{ width: `${width}%`, background: color }} /></div></div>
}

function DetailPanel({ page, setPage, snFilter, setSnFilter, outcomeFilter, setOutcomeFilter, data, loading }: {
  page: number; setPage: (value: number) => void; snFilter: string; setSnFilter: (value: string) => void; outcomeFilter: string; setOutcomeFilter: (value: string) => void; data?: { items: EventRow[]; total: number; page: number; page_size: number }; loading: boolean
}) {
  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1
  return <div className="panel"><div className="panel-title"><div><h2>SN / 测试事件明细</h2><p>按启用点重算后的逐事件结果。</p></div></div>
    <div className="toolbar"><input placeholder="搜索 SN" value={snFilter} onChange={(e) => { setSnFilter(e.target.value); setPage(1) }} /><select value={outcomeFilter} onChange={(e) => { setOutcomeFilter(e.target.value); setPage(1) }}><option value="">全部结果</option><option value="PASS">PASS</option><option value="FAIL">FAIL</option><option value="ERROR">ERROR</option></select></div>
    <div className="table-wrap"><table><thead><tr><th>SN</th><th>时间</th><th>Cell/Tester</th><th>QPL</th><th>结果</th><th>原始结果</th><th>耗时</th><th>失败原因</th></tr></thead><tbody>
      {data?.items.map((row) => <tr key={row.event_id}><td className="mono">{row.sn}</td><td>{new Date(row.detected_at).toLocaleString('zh-CN')}</td><td>{row.cell}<small>{row.tester}</small></td><td>{row.qpl}</td><td><span className={`status ${row.event_outcome === 'PASS' ? 'ok' : row.event_outcome === 'FAIL' ? 'bad' : 'warn'}`}>{row.event_outcome}</span></td><td>{row.original_final_result || '—'}</td><td>{row.processing_ms == null ? '—' : `${row.processing_ms} ms`}</td><td className="error-text">{row.error_reason || '—'}</td></tr>)}
    </tbody></table>{loading && <div className="empty-state">读取中…</div>}</div>
    <div className="pagination"><button className="button ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</button><span>第 {page} / {totalPages} 页 · 共 {data?.total.toLocaleString() ?? 0} 条</span><button className="button ghost" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>下一页</button></div>
  </div>
}
