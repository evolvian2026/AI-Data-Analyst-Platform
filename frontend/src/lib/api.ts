import type {
  Analysis, AskAnswer, Briefing, DataPage, DrilldownResult, Investigation,
  SampleDataset, SessionSummary, Story, SystemConfig, User, ActiveFilter,
} from './types'

const TOKEN_KEY = 'ai-analyst-token'

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* storage unavailable - the session simply will not persist */
  }
}

const BASE = import.meta.env.VITE_API_URL ?? ''

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (init.body && !(init.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }

  let response: Response
  try {
    response = await fetch(`${BASE}/api${path}`, { ...init, headers })
  } catch {
    throw new ApiError('Could not reach the server. Check your connection and try again.', 0)
  }

  if (response.status === 401) {
    setToken(null)
    window.dispatchEvent(new CustomEvent('auth:expired'))
    throw new ApiError('Your session has expired. Sign in again.', 401)
  }

  if (!response.ok) {
    let detail = `Request failed (${response.status})`
    try {
      const body = await response.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      /* the body was not JSON; keep the status message */
    }
    throw new ApiError(detail, response.status)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

async function download(path: string, body: unknown, fallbackName: string): Promise<void> {
  const headers = new Headers({ 'Content-Type': 'application/json' })
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(`${BASE}/api${path}`, {
    method: 'POST', headers, body: JSON.stringify(body),
  })
  if (!response.ok) {
    let detail = `Download failed (${response.status})`
    try {
      const payload = await response.json()
      if (typeof payload?.detail === 'string') detail = payload.detail
    } catch { /* keep the status message */ }
    throw new ApiError(detail, response.status)
  }
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const match = /filename="?([^"]+)"?/.exec(disposition)
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = match?.[1] ?? fallbackName
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

export interface AuthResponse {
  access_token: string
  token_type: string
  expires_in_minutes: number
  user: User
}

export const api = {
  // --- system ---------------------------------------------------------------
  config: () => request<SystemConfig>('/system/config'),

  // --- auth -----------------------------------------------------------------
  register: (payload: {
    email: string; password: string; full_name?: string; organization?: string
  }) => request<AuthResponse>('/auth/register', { method: 'POST', body: JSON.stringify(payload) }),

  login: (payload: { email: string; password: string }) =>
    request<AuthResponse>('/auth/login', { method: 'POST', body: JSON.stringify(payload) }),

  me: () => request<User>('/auth/me'),

  // --- sessions -------------------------------------------------------------
  listSessions: () => request<SessionSummary[]>('/sessions'),

  getSession: (id: string) => request<SessionSummary>(`/sessions/${id}`),

  status: (id: string) => request<{
    id: string; status: string; error: string; progress: SessionSummary['progress']
    sheets: SessionSummary['workbook_meta']['sheets']
  }>(`/sessions/${id}/status`),

  analysis: (id: string) => request<Analysis>(`/sessions/${id}/analysis`),

  upload: (file: File, name?: string) => {
    const form = new FormData()
    form.append('file', file)
    if (name) form.append('name', name)
    return request<SessionSummary>('/datasets/upload', { method: 'POST', body: form })
  },

  reanalyze: (id: string, scope: 'workbook' | 'sheet', sheet?: string) =>
    request<SessionSummary>(`/sessions/${id}/analyze`, {
      method: 'POST', body: JSON.stringify({ scope, sheet: sheet ?? null }),
    }),

  updateSession: (id: string, payload: {
    name?: string; notes?: Record<string, string>; bookmarks?: string[]
  }) => request<SessionSummary>(`/sessions/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),

  deleteSession: (id: string) => request<void>(`/sessions/${id}`, { method: 'DELETE' }),

  // --- interactive analysis --------------------------------------------------
  filter: (id: string, filters: ActiveFilter[]) =>
    request<Analysis>(`/sessions/${id}/filter`, {
      method: 'POST', body: JSON.stringify({ filters }),
    }),

  drilldown: (id: string, dimension: string, value: string, filters: ActiveFilter[] = []) =>
    request<DrilldownResult>(`/sessions/${id}/drilldown`, {
      method: 'POST', body: JSON.stringify({ dimension, value, filters }),
    }),

  ask: (id: string, question: string, filters: ActiveFilter[] = []) =>
    request<AskAnswer>(`/sessions/${id}/ask`, {
      method: 'POST', body: JSON.stringify({ question, filters }),
    }),

  askSuggestions: (id: string) =>
    request<{ questions: string[] }>(`/sessions/${id}/ask/suggestions`),

  askHistory: (id: string) => request<{
    history: { id: string; question: string; intent: string; answer: Record<string, string>; created_at: string }[]
  }>(`/sessions/${id}/ask/history`),

  investigate: (id: string, anomalyId: string) =>
    request<Investigation>(`/sessions/${id}/anomalies/${anomalyId}/investigate`),

  story: (id: string, audience: string) =>
    request<Story>(`/sessions/${id}/story?audience=${encodeURIComponent(audience)}`),

  briefing: (id: string, audience = 'executive') =>
    request<Briefing>(`/sessions/${id}/briefing?audience=${encodeURIComponent(audience)}`),

  data: (id: string, query: {
    limit?: number; offset?: number; sort_by?: string | null; sort_desc?: boolean
    search?: string | null; columns?: string[] | null; filters?: ActiveFilter[]
  }) => request<DataPage>(`/sessions/${id}/data`, { method: 'POST', body: JSON.stringify(query) }),

  // --- exports ---------------------------------------------------------------
  downloadPdf: (id: string, payload: Record<string, unknown>, name: string) =>
    download(`/sessions/${id}/report/pdf`, payload, name),

  downloadExcel: (id: string, payload: Record<string, unknown>, name: string) =>
    download(`/sessions/${id}/export/excel`, payload, name),

  downloadData: (id: string, payload: Record<string, unknown>, name: string) =>
    download(`/sessions/${id}/export/data`, payload, name),

  reportStyles: () => request<{
    styles: { key: string; label: string; pages: string; sections: string[] }[]
    audiences: Record<string, { label: string; depth: string; description: string }>
  }>('/reports/styles'),

  share: (id: string, hours = 72) =>
    request<{ token: string; expires_at: string; path: string; note: string }>(
      `/sessions/${id}/share`, { method: 'POST', body: JSON.stringify({ expires_in_hours: hours }) },
    ),

  // --- samples ---------------------------------------------------------------
  samples: () => request<{ samples: SampleDataset[] }>('/samples'),

  loadSample: (key: string) =>
    request<SessionSummary>(`/samples/${key}/load`, { method: 'POST' }),
}
