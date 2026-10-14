export type Role = 'admin' | 'analyst' | 'viewer'

export interface User {
  id: string
  username: string
  role: Role
  is_active: boolean
  must_change_password: boolean
  created_at: string
}

export interface SessionResponse {
  user: User
  csrf_token: string
}

export interface Batch {
  id: string
  original_name: string
  file_format: string
  file_size: number
  file_sha256: string
  status: string
  row_count: number
  event_count: number
  duplicate_count: number
  error_count: number
  error_message?: string | null
  created_at: string
  ready_at?: string | null
}

export interface SpecVersion {
  id: string
  name: string
  fingerprint: string
  status: 'draft' | 'active' | 'retired'
  enabled_points_json: string
  rules_json: string
  source_batch_id?: string | null
  created_at: string
  confirmed_at?: string | null
}

export interface MappingVersion {
  id: string
  name: string
  fingerprint: string
  status: 'draft' | 'active' | 'retired'
  rules_json: string
  created_at: string
  confirmed_at?: string | null
}

export interface AnalysisRun {
  id: string
  name: string
  status: string
  phase: string
  progress: number
  filters_json: string
  spec_version_id: string
  mapping_version_id?: string | null
  warnings_json: string
  error_message?: string | null
  summary_json?: string | null
  created_at: string
  started_at?: string | null
  completed_at?: string | null
}

export interface Kpis {
  total_input: number
  first_pass_qty: number
  final_pass_qty: number
  final_ng_qty: number
  first_pass_rate: number | null
  final_pass_rate: number | null
  retest_pass_qty: number
  retest_pass_rate: number | null
  avg_processing_ms: number | null
  max_tester_yield_gap: number
  unretested_ng_qty: number
  error_event_qty: number
  mismatch_event_qty: number
}

export interface TimeYieldPoint {
  bucket: string
  input_qty: number
  pass_qty: number
  fail_error_qty: number
  yield_rate: number | null
}

export interface ParetoPoint {
  point: string
  count: number
  pct_total_input: number | null
}

export interface CellYieldPoint {
  cell: string
  first_pass: number
  retest_pass: number
  final_ng: number
  total: number
}

export interface TesterYieldPoint {
  cell: string
  qpl: string
  tester: string
  pass_qty: number
  fail_qty: number
  error_qty: number
  yield_rate: number | null
}

export interface DistributionPoint {
  cell: string
  point: string
  count: number
  sampled: boolean
  min: number
  q1: number
  median: number
  q3: number
  max: number
  mean: number
  lsl: number | null
  usl: number | null
  density: Array<{ x: number; density: number }>
}

export interface Summary {
  meta: {
    generated_at: string
    timezone: string
    day_cutoff_hour: number
    event_count: number
    warnings: string[]
  }
  kpis: Kpis
  time_yield: TimeYieldPoint[]
  pareto: ParetoPoint[]
  cell_yield: CellYieldPoint[]
  tester_yield: TesterYieldPoint[]
  distribution: DistributionPoint[]
  quality: Record<string, unknown>
}

export interface EventRow {
  event_id: string
  sn: string
  detected_at: string
  production_day: string
  config?: string
  equipment_id?: string
  slot?: string
  cell: string
  tester: string
  qpl: string
  processing_ms?: number | null
  original_final_result?: string | null
  event_outcome: string
  error_reason?: string
  measurement_json: string
  point_results_json: string
}
