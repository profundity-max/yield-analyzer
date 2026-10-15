import { useEffect, useState } from 'react'
import ReactECharts from 'echarts-for-react'
import type { CellYieldPoint, DistributionPoint, Kpis, ParetoPoint, Summary, TesterYieldPoint, TimeYieldPoint } from '../types'

const PASS_GREEN = '#19a974'
const FAIL_RED = '#d64545'
const ERROR_YELLOW = '#e6b422'
const NEUTRAL_BLUE = '#1d70b8'
const colors = [PASS_GREEN, FAIL_RED, ERROR_YELLOW, NEUTRAL_BLUE, '#7b61ff', '#00a6a6']

export function formatPct(value: number | null | undefined) {
  return value == null ? '—' : `${(value * 100).toFixed(2)}%`
}

export function KpiGrid({ kpis }: { kpis: Kpis }) {
  const items = [
    ['Total Input', kpis.total_input.toLocaleString(), '去重 SN'],
    ['Final Pass Qty', kpis.final_pass_qty.toLocaleString(), formatPct(kpis.final_pass_rate)],
    ['Final NG Qty', kpis.final_ng_qty.toLocaleString(), '含 Error'],
    ['1st Pass Qty', kpis.first_pass_qty.toLocaleString(), formatPct(kpis.first_pass_rate)],
    ['Retest Pass Qty', kpis.retest_pass_qty.toLocaleString(), formatPct(kpis.retest_pass_rate)],
    ['Avg Processing Time', kpis.avg_processing_ms == null ? '—' : `${kpis.avg_processing_ms.toFixed(2)} ms`, '逐事件均值'],
    ['Max Tester Yield Gap', formatPct(kpis.max_tester_yield_gap), 'Tester 最大差值'],
    ['Unretested NG', kpis.unretested_ng_qty.toLocaleString(), '无后续测试'],
  ]
  return (
    <div className="kpi-grid">
      {items.map(([label, value, hint]) => (
        <div className="kpi-card" key={label}>
          <span>{label}</span>
          <strong>{value}</strong>
          <small>{hint}</small>
        </div>
      ))}
    </div>
  )
}

export function TimeYieldChart({ rows }: { rows: TimeYieldPoint[] }) {
  return (
    <ReactECharts
      style={{ height: 390 }}
      option={{
        color: colors,
        tooltip: { trigger: 'axis' },
        legend: { bottom: 0 },
        grid: { left: 55, right: 60, top: 35, bottom: 65 },
        xAxis: { type: 'category', data: rows.map((row) => row.bucket.slice(5, 16)), axisLabel: { rotate: 35 } },
        yAxis: [
          { type: 'value', name: 'Qty' },
          { type: 'value', name: 'Yield', min: 0, max: 1, axisLabel: { formatter: (value: number) => `${Math.round(value * 100)}%` } },
        ],
        series: [
          { name: 'Input Qty', type: 'bar', itemStyle: { color: NEUTRAL_BLUE }, data: rows.map((row) => row.input_qty) },
          { name: 'Pass Qty', type: 'bar', itemStyle: { color: PASS_GREEN }, data: rows.map((row) => row.pass_qty) },
          { name: 'Fail Qty', type: 'bar', itemStyle: { color: FAIL_RED }, data: rows.map((row) => row.fail_qty) },
          { name: 'Error Qty', type: 'bar', itemStyle: { color: ERROR_YELLOW }, data: rows.map((row) => row.error_qty) },
          { name: 'Yield Rate', type: 'line', yAxisIndex: 1, data: rows.map((row) => row.yield_rate), smooth: true },
        ],
      }}
    />
  )
}

export function ParetoChart({ rows }: { rows: ParetoPoint[] }) {
  let cumulative = 0
  const cumulativeRows = rows.map((row) => {
    cumulative += row.count
    return cumulative
  })
  const total = cumulative || 1
  return (
    <ReactECharts
      style={{ height: 360 }}
      option={{
        color: ['#173b75', '#de5b50'],
        tooltip: { trigger: 'axis' },
        legend: { bottom: 0 },
        grid: { left: 55, right: 55, top: 30, bottom: 70 },
        xAxis: { type: 'category', data: rows.map((row) => row.point), axisLabel: { rotate: 25 } },
        yAxis: [
          { type: 'value', name: 'NG Count' },
          { type: 'value', name: 'Cumulative', min: 0, max: 1, axisLabel: { formatter: (value: number) => `${Math.round(value * 100)}%` } },
        ],
        series: [
          { name: 'NG Count', type: 'bar', barMaxWidth: 54, data: rows.map((row) => ({ value: row.count, itemStyle: { color: row.outcome === 'ERROR' ? ERROR_YELLOW : FAIL_RED } })) },
          { name: 'Cumulative %', type: 'line', yAxisIndex: 1, symbolSize: 7, data: cumulativeRows.map((value) => value / total) },
        ],
      }}
    />
  )
}

export function CellYieldPanel({ rows }: { rows: CellYieldPoint[] }) {
  return (
    <div className="pie-grid">
      {rows.map((row) => (
        <div className="pie-card" key={row.cell}>
          <h4>{row.cell}</h4>
          <ReactECharts
            style={{ height: 230 }}
            option={{
              color: [PASS_GREEN, '#72c89f', FAIL_RED, ERROR_YELLOW],
              tooltip: { trigger: 'item' },
              series: [
                {
                  type: 'pie',
                  radius: ['38%', '72%'],
                  label: { formatter: '{b}\n{d}%' },
                  data: [
                    { name: 'First Pass', value: row.first_pass },
                    { name: 'Retest Pass', value: row.retest_pass },
                    { name: 'Final Fail', value: row.final_fail },
                    { name: 'Final Error', value: row.final_error },
                  ],
                },
              ],
            }}
          />
        </div>
      ))}
    </div>
  )
}

function groupTesterRows(rows: TesterYieldPoint[]) {
  const groups = new Map<string, TesterYieldPoint[]>()
  for (const row of rows) {
    const key = `${row.cell} / ${row.qpl}`
    groups.set(key, [...(groups.get(key) ?? []), row])
  }
  return groups
}

export function TesterYieldPanel({ rows }: { rows: TesterYieldPoint[] }) {
  const groups = groupTesterRows(rows)
  return (
    <div className="stack">
      {[...groups.entries()].map(([group, items]) => (
        <div className="chart-card" key={group}>
          <h4>{group}</h4>
          <ReactECharts
            style={{ height: 330 }}
            option={{
              color: colors,
              tooltip: { trigger: 'axis' },
              legend: { bottom: 0 },
              grid: { left: 55, right: 60, top: 25, bottom: 60 },
              xAxis: { type: 'category', data: items.map((item) => item.tester) },
              yAxis: [
                { type: 'value', name: 'Qty' },
                { type: 'value', name: 'Yield', min: 0, max: 1, axisLabel: { formatter: (value: number) => `${Math.round(value * 100)}%` } },
              ],
              series: [
                { name: 'Pass Qty', type: 'bar', itemStyle: { color: PASS_GREEN }, data: items.map((item) => item.pass_qty) },
                { name: 'Fail Qty', type: 'bar', itemStyle: { color: FAIL_RED }, data: items.map((item) => item.fail_qty) },
                { name: 'Error Qty', type: 'bar', itemStyle: { color: ERROR_YELLOW }, data: items.map((item) => item.error_qty) },
                { name: 'Yield Rate', type: 'line', yAxisIndex: 1, data: items.map((item) => item.yield_rate) },
              ],
            }}
          />
        </div>
      ))}
    </div>
  )
}

export function DistributionPanel({ summary }: { summary: Summary }) {
  const cells = [...new Set(summary.distribution.map((row) => row.cell))]
  const [cell, setCell] = useState(cells[0] ?? 'Unassigned')
  useEffect(() => {
    if (!cells.includes(cell)) setCell(cells[0] ?? 'Unassigned')
  }, [cell, cells])
  const rows = summary.distribution
    .filter((row) => row.cell === cell)
    .sort((a, b) => a.point.localeCompare(b.point, undefined, { numeric: true }))
  return (
    <div>
      <div className="toolbar">
        <label>
          Cell
          <select value={cell} onChange={(event) => setCell(event.target.value)}>
            {cells.map((item) => <option key={item}>{item}</option>)}
          </select>
        </label>
        <span className="muted">箱线图：从上到下排列测试点，数值分布沿横向展开</span>
      </div>
      <ReactECharts
        style={{ height: Math.max(320, rows.length * 62) }}
        option={{
          color: [NEUTRAL_BLUE],
          tooltip: { trigger: 'item' },
          grid: { left: 105, right: 45, top: 30, bottom: 45 },
          xAxis: { type: 'value', name: '测量值' },
          yAxis: { type: 'category', inverse: true, data: rows.map((row) => row.point) },
          series: [
            {
              name: '数据分布',
              type: 'boxplot',
              itemStyle: { color: '#dcecff', borderColor: NEUTRAL_BLUE, borderWidth: 2 },
              data: rows.map((row) => [row.min, row.q1, row.median, row.q3, row.max]),
              markPoint: {
                symbol: 'diamond',
                symbolSize: 9,
                data: rows.map((row) => ({ coord: [row.mean, row.point], value: row.mean })),
                itemStyle: { color: PASS_GREEN },
                label: { formatter: (params: { data: { value: number } }) => `均值 ${params.data.value}` },
              },
            },
          ],
        }}
      />
      <div className="table-wrap">
        <table>
          <thead><tr><th>测试点</th><th>样本数</th><th>均值</th><th>最小值</th><th>最大值</th><th>σ</th><th>LSL</th><th>USL</th></tr></thead>
          <tbody>{rows.map((row) => <tr key={row.point}><td><strong>{row.point}</strong></td><td>{row.count.toLocaleString()}</td><td className="stat-mean">{row.mean}</td><td>{row.min}</td><td>{row.max}</td><td className="stat-sigma">{row.stddev}</td><td>{row.lsl ?? '—'}</td><td>{row.usl ?? '—'}</td></tr>)}</tbody>
        </table>
      </div>
    </div>
  )
}
