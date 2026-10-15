import type {
  AnalysisRun,
  Batch,
  Category,
  ConfigOptions,
  EventRow,
  MappingEditor,
  MappingVersion,
  MasterWorkbench,
  SessionResponse,
  SpecEditor,
  SpecVersion,
  Summary,
  User,
  WorkbenchState,
} from './types'

let csrfToken = ''

export function setCsrfToken(value: string) {
  csrfToken = value
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body && !(init.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }
  if (csrfToken && init.method && init.method !== 'GET') {
    headers.set('X-CSRF-Token', csrfToken)
  }
  const response = await fetch(path, {
    ...init,
    headers,
    credentials: 'include',
  })
  if (!response.ok) {
    let message = response.statusText
    try {
      const payload = await response.json()
      message = payload.detail || payload.title || message
    } catch {
      // keep status text
    }
    throw new ApiError(response.status, message)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const api = {
  me: () => apiFetch<SessionResponse>('/api/v1/auth/me'),
  login: (username: string, password: string) =>
    apiFetch<SessionResponse>('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),
  logout: () => apiFetch<void>('/api/v1/auth/logout', { method: 'POST' }),
  changePassword: (current_password: string, new_password: string) =>
    apiFetch<User>('/api/v1/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({ current_password, new_password }),
    }),
  batches: () => apiFetch<Batch[]>('/api/v1/batches'),
  workbench: (batchId: string) => apiFetch<WorkbenchState>(`/api/v1/batches/${batchId}/workbench`),
  configOptions: (batchId?: string) =>
    apiFetch<ConfigOptions>(`/api/v1/config/options${batchId ? `?batch_id=${batchId}` : ''}`),
  masterWorkbench: () => apiFetch<MasterWorkbench>('/api/v1/master/workbench'),
  refreshMaster: () => apiFetch<AnalysisRun>('/api/v1/master/refresh', { method: 'POST' }),
  replaceModule: (moduleId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return apiFetch<Batch>(`/api/v1/master/modules/${moduleId}/replace`, {
      method: 'POST',
      body: form,
    })
  },
  revertModule: (moduleId: string) =>
    apiFetch<AnalysisRun>(`/api/v1/master/modules/${moduleId}/revert`, { method: 'POST' }),
  uploadBatch: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return apiFetch<Batch>('/api/v1/batches', { method: 'POST', body: form })
  },
  deleteBatch: (id: string) => apiFetch<void>(`/api/v1/batches/${id}`, { method: 'DELETE' }),
  analyses: () => apiFetch<AnalysisRun[]>('/api/v1/analyses'),
  analysis: (id: string) => apiFetch<AnalysisRun>(`/api/v1/analyses/${id}`),
  summary: (id: string) => apiFetch<Summary>(`/api/v1/analyses/${id}/summary`),
  events: (id: string, page = 1, pageSize = 50, filters = '') =>
    apiFetch<{ items: EventRow[]; total: number; page: number; page_size: number }>(
      `/api/v1/analyses/${id}/events?page=${page}&page_size=${pageSize}${filters}`,
    ),
  rerunWith: (id: string, specVersionId: string, mappingVersionId: string | null) =>
    apiFetch<AnalysisRun>(`/api/v1/analyses/${id}/rerun-with`, {
      method: 'POST',
      body: JSON.stringify({ spec_version_id: specVersionId, mapping_version_id: mappingVersionId }),
    }),
  specEditor: (specId?: string, batchId?: string) => {
    const params = new URLSearchParams()
    if (specId) params.set('spec_id', specId)
    if (batchId) params.set('batch_id', batchId)
    return apiFetch<SpecEditor>(`/api/v1/specs/editor?${params.toString()}`)
  },
  saveSpecEditor: (payload: Record<string, unknown>) =>
    apiFetch<SpecEditor>('/api/v1/specs/editor', { method: 'POST', body: JSON.stringify(payload) }),
  mappingEditor: (batchId?: string, mappingVersionId?: string) => {
    const params = new URLSearchParams()
    if (batchId) params.set('batch_id', batchId)
    if (mappingVersionId) params.set('mapping_version_id', mappingVersionId)
    return apiFetch<MappingEditor>(`/api/v1/mapping-editor?${params.toString()}`)
  },
  saveMappingEditor: (batchId: string | null, name: string, rows: unknown[]) =>
    apiFetch<MappingEditor>('/api/v1/mappings/editor', {
      method: 'POST',
      body: JSON.stringify({ batch_id: batchId, name, rows }),
    }),
  categories: (includeInactive = true) =>
    apiFetch<Category[]>(`/api/v1/categories?include_inactive=${includeInactive}`),
  createCategory: (payload: Record<string, unknown>) =>
    apiFetch<Category>('/api/v1/categories', { method: 'POST', body: JSON.stringify(payload) }),
  updateCategory: (id: string, payload: Record<string, unknown>) =>
    apiFetch<Category>(`/api/v1/categories/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  createAnalysis: (payload: Record<string, unknown>) =>
    apiFetch<AnalysisRun>('/api/v1/analyses', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  cancelAnalysis: (id: string) =>
    apiFetch<AnalysisRun>(`/api/v1/analyses/${id}/cancel`, { method: 'POST' }),
  retryAnalysis: (id: string) =>
    apiFetch<AnalysisRun>(`/api/v1/analyses/${id}/retry`, { method: 'POST' }),
  specs: () => apiFetch<SpecVersion[]>('/api/v1/admin/specs'),
  createSpec: (payload: Record<string, unknown>) =>
    apiFetch<SpecVersion>('/api/v1/admin/specs', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  confirmSpec: (id: string) =>
    apiFetch<SpecVersion>(`/api/v1/admin/specs/${id}/confirm`, { method: 'POST' }),
  mappings: () => apiFetch<MappingVersion[]>('/api/v1/admin/mappings'),
  createMapping: (name: string, rules: unknown[]) =>
    apiFetch<MappingVersion>('/api/v1/admin/mappings', {
      method: 'POST',
      body: JSON.stringify({ name, rules }),
    }),
  users: () => apiFetch<User[]>('/api/v1/admin/users'),
  createUser: (username: string, password: string, role: string) =>
    apiFetch<User>('/api/v1/admin/users', {
      method: 'POST',
      body: JSON.stringify({ username, password, role }),
    }),
  auditLogs: () => apiFetch<{ items: unknown[] }>('/api/v1/admin/audit-logs'),
}
