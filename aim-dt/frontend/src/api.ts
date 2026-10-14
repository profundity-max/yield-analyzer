import type {
  AnalysisRun,
  Batch,
  EventRow,
  MappingVersion,
  SessionResponse,
  SpecVersion,
  Summary,
  User,
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
