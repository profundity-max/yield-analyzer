import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Save, X } from 'lucide-react'
import { api } from '../api'
import type { Category, MappingEditorRow, PointConfig } from '../types'

function Modal({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <div className="modal-card">
        <div className="modal-head"><h2>{title}</h2><button className="icon-button" onClick={onClose}><X size={18} /></button></div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  )
}

export function SpecEditorModal({ batchId, specId, onClose, onSaved }: { batchId?: string; specId?: string; onClose: () => void; onSaved: (specId: string) => void }) {
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState(specId ?? '')
  const [name, setName] = useState('D-T 标准规格 V2')
  const [points, setPoints] = useState<PointConfig[]>([])
  const specQuery = useQuery({ queryKey: ['spec-editor', selectedId, batchId], queryFn: () => api.specEditor(selectedId || undefined, batchId) })
  const optionsQuery = useQuery({ queryKey: ['config-options', batchId], queryFn: () => api.configOptions(batchId) })
  const save = useMutation({
    mutationFn: () => api.saveSpecEditor({ name, points, source_batch_id: batchId ?? null }),
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ['config-options'] })
      await queryClient.invalidateQueries({ queryKey: ['spec-editor'] })
      onSaved(result.id)
    },
  })
  useEffect(() => {
    if (!specQuery.data) return
    setSelectedId(specQuery.data.id)
    setName(specQuery.data.name)
    setPoints(specQuery.data.points)
  }, [specQuery.data])
  const updatePoint = (code: string, patch: Partial<PointConfig>) => setPoints((current) => current.map((point) => point.code === code ? { ...point, ...patch } : point))
  return (
    <Modal title="规格与启用测试点" onClose={onClose}>
      <div className="config-toolbar">
        <label>版本选择
          <select value={selectedId} onChange={(event) => setSelectedId(event.target.value)}>
            <option value="">当前 active 版本</option>
            {optionsQuery.data?.specs.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.status}</option>)}
          </select>
        </label>
        <label>保存为新版本名称<input value={name} onChange={(event) => setName(event.target.value)} /></label>
      </div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>启用</th><th>测试点</th><th>原始列</th><th>LSL</th><th>USL</th><th>检测状态</th></tr></thead>
          <tbody>{points.map((point) => <tr key={point.code}>
            <td><input type="checkbox" checked={point.enabled} onChange={(event) => updatePoint(point.code, { enabled: event.target.checked })} /></td>
            <td><strong>{point.code}</strong></td>
            <td className="mono">{point.source_column || `Temp_${point.code.replace('-', '_')}`}</td>
            <td><input type="number" step="any" value={point.lsl ?? ''} onChange={(event) => updatePoint(point.code, { lsl: event.target.value === '' ? null : Number(event.target.value) })} /></td>
            <td><input type="number" step="any" value={point.usl ?? ''} onChange={(event) => updatePoint(point.code, { usl: event.target.value === '' ? null : Number(event.target.value) })} /></td>
            <td><span className={point.detected ? 'status ok' : 'status pending'}>{point.detected ? '已检测' : '未检测'}</span></td>
          </tr>)}</tbody>
        </table>
      </div>
      <div className="modal-actions">
        {save.isError && <span className="form-error">{save.error.message}</span>}
        <button className="button primary" disabled={save.isPending || !points.some((point) => point.enabled)} onClick={() => save.mutate()}><Save size={16} /> 保存并立即启用</button>
      </div>
    </Modal>
  )
}

function CategorySelect({ value, categories, onChange }: { value: string; categories: Category[]; onChange: (value: string) => void }) {
  return <select value={value} onChange={(event) => onChange(event.target.value)}><option value="Unassigned">请选择</option>{categories.filter((item) => item.active).map((item) => <option key={item.id} value={item.code}>{item.label}</option>)}</select>
}

export function MappingEditorModal({ batchId, mappingId, onClose, onSaved }: { batchId: string; mappingId?: string; onClose: () => void; onSaved: (mappingId: string) => void }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState('D-T Mapping V2')
  const [rows, setRows] = useState<MappingEditorRow[]>([])
  const editorQuery = useQuery({ queryKey: ['mapping-editor', batchId, mappingId], queryFn: () => api.mappingEditor(batchId, mappingId) })
  const save = useMutation({
    mutationFn: () => api.saveMappingEditor(batchId, name, rows),
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ['mapping-editor'] })
      await queryClient.invalidateQueries({ queryKey: ['config-options'] })
      if (result.mapping_version_id) onSaved(result.mapping_version_id)
    },
  })
  useEffect(() => {
    if (!editorQuery.data) return
    setName(editorQuery.data.mapping_name || 'D-T Mapping V2')
    setRows([...editorQuery.data.rules, ...editorQuery.data.unmapped])
  }, [editorQuery.data])
  const categories = editorQuery.data?.categories
  const updateTarget = (index: number, kind: 'cell' | 'tester' | 'qpl', value: string) => setRows((current) => current.map((row, rowIndex) => rowIndex === index ? { ...row, target: { ...row.target, [kind]: value }, status: row.status === 'unmapped' ? 'mapped' : row.status } : row))
  const toggleRule = (index: number, enabled: boolean) => setRows((current) => current.map((row, rowIndex) => rowIndex === index ? { ...row, status: enabled ? 'mapped' : 'disabled' } : row))
  const pendingIncomplete = rows.some((row) => row.status === 'mapped' && Object.values(row.target).some((value) => !value || value === 'Unassigned'))
  const mappedRows = rows.map((row, index) => ({ row, index })).filter(({ row }) => row.status !== 'unmapped')
  const unmappedRows = rows.map((row, index) => ({ row, index })).filter(({ row }) => row.status === 'unmapped')
  return (
    <Modal title="设备值映射到 Cell / Tester / QPL" onClose={onClose}>
      <div className="config-toolbar"><label>版本名称<input value={name} onChange={(event) => setName(event.target.value)} /></label><span className="muted">未映射事件：{editorQuery.data?.unmapped.reduce((sum, row) => sum + row.match_count, 0).toLocaleString() ?? 0}</span></div>
      <h3>当前映射</h3>
      <div className="table-wrap"><table><thead><tr><th>启用</th><th>站点</th><th>设备</th><th>config</th><th>Slot</th><th>Cell</th><th>Tester</th><th>QPL</th><th>命中</th></tr></thead><tbody>
        {mappedRows.map(({ row, index }) => <tr key={`m-${index}`}><td><input type="checkbox" checked={row.status !== 'disabled'} onChange={(event) => toggleRule(index, event.target.checked)} /></td><td>{row.source.site_name || '—'}</td><td>{row.source.equipment_id || '—'}</td><td>{row.source.config || '—'}</td><td>{row.source.slot || '—'}</td><td><CategorySelect value={row.target.cell} categories={categories?.cell ?? []} onChange={(value) => updateTarget(index, 'cell', value)} /></td><td><CategorySelect value={row.target.tester} categories={categories?.tester ?? []} onChange={(value) => updateTarget(index, 'tester', value)} /></td><td><CategorySelect value={row.target.qpl} categories={categories?.qpl ?? []} onChange={(value) => updateTarget(index, 'qpl', value)} /></td><td>{row.match_count.toLocaleString()}</td></tr>)}
      </tbody></table></div>
      <h3>待识别值</h3>
      <div className="table-wrap"><table><thead><tr><th>站点</th><th>设备</th><th>config</th><th>Slot</th><th>Cell</th><th>Tester</th><th>QPL</th><th>事件数</th></tr></thead><tbody>
        {unmappedRows.map(({ row, index }) => <tr key={`u-${index}`}><td>{row.source.site_name || '—'}</td><td>{row.source.equipment_id || '—'}</td><td>{row.source.config || '—'}</td><td>{row.source.slot || '—'}</td><td><CategorySelect value={row.target.cell} categories={categories?.cell ?? []} onChange={(value) => updateTarget(index, 'cell', value)} /></td><td><CategorySelect value={row.target.tester} categories={categories?.tester ?? []} onChange={(value) => updateTarget(index, 'tester', value)} /></td><td><CategorySelect value={row.target.qpl} categories={categories?.qpl ?? []} onChange={(value) => updateTarget(index, 'qpl', value)} /></td><td>{row.match_count.toLocaleString()}</td></tr>)}
      </tbody></table></div>
      <div className="modal-actions">
        {save.isError && <span className="form-error">{save.error.message}</span>}
        <button className="button primary" disabled={save.isPending || pendingIncomplete} onClick={() => save.mutate()}><Save size={16} /> 保存并立即生效</button>
      </div>
    </Modal>
  )
}
