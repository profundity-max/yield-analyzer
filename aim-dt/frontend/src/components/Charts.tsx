import { useEffect, useState } from 'react'
import ReactECharts from 'echarts-for-react'
import type { CellYieldPoint, DistributionPoint, Kpis, ParetoPoint, Summary, TesterYieldPoint, TimeYieldPoint } from '../types'

const colors = ['#1d70b8', '#19a974', '#f4a261', '#d64545', '#7b61ff', '#00a6a6']

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
          { name: 'Input Qty', type: 'bar', data: rows.map((row) => row.input_qty) },
          { name: 'Pass Qty', type: 'bar', data: rows.map((row) => row.pass_qty) },
          { name: 'Fail & Error Qty', type: 'bar', data: rows.map((row) => row.fail_error_qty) },
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
          { name: 'NG Count', type: 'bar', barMaxWidth: 54, data: rows.map((row) => row.count) },
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
              color: ['#19a974', '#f4b942', '#d64545'],
              tooltip: { trigger: 'item' },
              series: [
                {
                  type: 'pie',
                  radius: ['38%', '72%'],
                  label: { formatter: '{b}\n{d}%' },
                  data: [
                    { name: 'First Pass', value: row.first_pass },
                    { name: 'Retest Pass', value: row.retest_pass },
                    { name: 'Final NG', value: row.final_ng },
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
                { name: 'Pass Qty', type: 'bar', data: items.map((item) => item.pass_qty) },
                { name: 'Fail Qty', type: 'bar', data: items.map((item) => item.fail_qty) },
                { name: 'Error Qty', type: 'bar', data: items.map((item) => item.error_qty) },
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
  const rows = summary.distribution.filter((row) => row.cell === cell)
  return (
    <div>
      <div className="toolbar">
        <label>
          Cell
          <select value={cell} onChange={(event) => setCell(event.target.value)}>
            {cells.map((item) => <option key={item}>{item}</option>)}
          </select>
        </label>
      </div>
      <div className="distribution-grid">
        {rows.map((row) => <DistributionCard key={row.point} row={row} />)}
      </div>
    </div>
  )
}

function DistributionCard({ row }: { row: DistributionPoint }) {
  const kde = row.density.map((item) => [item.x, item.density])
  return (
    <div className="distribution-card">
      <div className="distribution-head">
        <strong>{row.point}</strong>
        <span>{row.count.toLocaleString()} 条{row.sampled ? ' · 抽样 KDE' : ''}</span>
      </div>
      <ReactECharts
        style={{ height: 220 }}
        option={{
          color: ['#7b61ff'],
          tooltip: { trigger: 'axis' },
          grid: { left: 45, right: 20, top: 15, bottom: 35 },
          xAxis: { type: 'value', name: 'Value' },
          yAxis: { type: 'value', name: 'Density', axisLabel: { show: false }, splitLine: { show: false } },
          series: [
            {
              type: 'line',
              data: kde,
              smooth: true,
              showSymbol: false,
              areaStyle: { opacity: 0.3 },
              markLine: {
                symbol: 'none',
                data: [
                  ...(row.lsl == null ? [] : [{ xAxis: row.lsl, name: 'LSL' }]),
                  ...(row.usl == null ? [] : [{ xAxis: row.usl, name: 'USL' }]),
                ],
              },
            },
          ],
        }}
      />
      <div className="mini-stats">
        <span>Min {row.min}</span><span>Q1 {row.q1}</span><span>Median {row.median}</span><span>Q3 {row.q3}</span><span>Max {row.max}</span>
      </div>
    </div>
  )
}
