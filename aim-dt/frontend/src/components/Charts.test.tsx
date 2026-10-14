import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { KpiGrid, formatPct } from './Charts'

describe('KpiGrid', () => {
  it('renders AIM processing time in milliseconds', () => {
    render(
      <KpiGrid
        kpis={{
          total_input: 90,
          first_pass_qty: 0,
          final_pass_qty: 0,
          final_ng_qty: 90,
          first_pass_rate: 0,
          final_pass_rate: 0,
          retest_pass_qty: 0,
          retest_pass_rate: null,
          avg_processing_ms: 8.989,
          max_tester_yield_gap: 0,
          unretested_ng_qty: 89,
          error_event_qty: 0,
          mismatch_event_qty: 0,
        }}
      />,
    )
    expect(screen.getByText('8.99 ms')).toBeInTheDocument()
    expect(screen.getAllByText('90').length).toBeGreaterThan(0)
  })

  it('formats null percentages consistently', () => {
    expect(formatPct(null)).toBe('—')
    expect(formatPct(0.5)).toBe('50.00%')
  })
})
