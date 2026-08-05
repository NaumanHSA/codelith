/* ------------------------------------------------------------------ *
 * The single HTTP client. Every request in the studio goes through
 * request() — it attaches the JWT, refreshes once on 401, retries the
 * original call, and only then bounces to sign-in.
 *
 * The base URL comes from VITE_API_URL. Never hardcode a host or port.
 * ------------------------------------------------------------------ */

import type {
  Doc, Job, JobLog, KnowledgeBase, LLMSettings, ProbeResult,
  Project, ProjectSource, Tokens, User, DocType, OutputFormat, SourceType,
} from './types'

export const API_BASE =
  (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ??
  'http://localhost:8000'

const ROOT = `${API_BASE}/api/v1`

const ACCESS = 'da.access_token'
const REFRESH = 'da.refresh_token'

export const tokenStore = {
  get access() {
    return localStorage.getItem(ACCESS)
  },
  get refresh() {
    return localStorage.getItem(REFRESH)
  },
  set(t: Tokens) {
    localStorage.setItem(ACCESS, t.access_token)
    localStorage.setItem(REFRESH, t.refresh_token)
  },
  clear() {
    localStorage.removeItem(ACCESS)
    localStorage.removeItem(REFRESH)
  },
}

/** Thrown for every non-2xx. `status` lets callers treat 403/404 specially. */
export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/**
 * The contract returns three different error shapes. Read `error` first,
 * fall back to `detail`, and remember `detail` is sometimes an array of
 * validation objects rather than a string.
 */
function readError(body: unknown, status: number): string {
  if (typeof body === 'string' && body.trim()) return body
  if (body && typeof body === 'object') {
    const b = body as Record<string, unknown>
    if (typeof b.error === 'string') return b.error
    const d = b.detail
    if (typeof d === 'string') return d
    if (Array.isArray(d)) {
      const msgs = d
        .map(v => {
          if (typeof v === 'string') return v
          const o = v as Record<string, unknown>
          const loc = Array.isArray(o.loc) ? o.loc.filter(p => p !== 'body').join('.') : ''
          const msg = typeof o.msg === 'string' ? o.msg : ''
          return loc ? `${loc}: ${msg}` : msg
        })
        .filter(Boolean)
      if (msgs.length) return msgs.join(' · ')
    }
  }
  if (status === 403) return 'You do not have permission to do that.'
  if (status === 404) return 'Not found.'
  if (status === 0) return 'Cannot reach the API. Is the backend running?'
  return `Request failed (${status}).`
}

/** Session-expiry broadcast so the auth provider can react from anywhere. */
export const AUTH_EXPIRED = 'da:auth-expired'
const expire = () => {
  tokenStore.clear()
  window.dispatchEvent(new Event(AUTH_EXPIRED))
}

let refreshing: Promise<boolean> | null = null

/** Refresh at most once concurrently, however many calls 401 together. */
function refreshOnce(): Promise<boolean> {
  if (refreshing) return refreshing
  const token = tokenStore.refresh
  if (!token) return Promise.resolve(false)

  refreshing = fetch(`${ROOT}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: token }),
  })
    .then(async r => {
      if (!r.ok) return false
      tokenStore.set((await r.json()) as Tokens)
      return true
    })
    .catch(() => false)
    .finally(() => {
      refreshing = null
    })

  return refreshing
}

interface Options {
  method?: string
  body?: unknown
  /** Auth endpoints must not trigger the refresh-and-retry dance. */
  anonymous?: boolean
  signal?: AbortSignal
  formData?: FormData
}

async function request<T>(path: string, opts: Options = {}): Promise<T> {
  const { method = 'GET', body, anonymous, signal, formData } = opts

  const send = async (): Promise<Response> => {
    const headers: Record<string, string> = {}
    if (!formData) headers['Content-Type'] = 'application/json'
    const access = tokenStore.access
    if (access && !anonymous) headers.Authorization = `Bearer ${access}`

    return fetch(`${ROOT}${path}`, {
      method,
      headers,
      signal,
      body: formData ?? (body === undefined ? undefined : JSON.stringify(body)),
    })
  }

  let res: Response
  try {
    res = await send()
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new ApiError(0, readError(null, 0))
  }

  // 401 → refresh once, retry once, and only then bounce to sign-in.
  if (res.status === 401 && !anonymous) {
    if (await refreshOnce()) {
      try {
        res = await send()
      } catch (e) {
        if ((e as Error).name === 'AbortError') throw e
        throw new ApiError(0, readError(null, 0))
      }
    }
    if (res.status === 401) {
      expire()
      throw new ApiError(401, 'Your session expired. Please sign in again.')
    }
  }

  if (res.status === 204) return undefined as T

  const text = await res.text()
  let parsed: unknown = null
  if (text) {
    try {
      parsed = JSON.parse(text)
    } catch {
      parsed = text
    }
  }

  if (!res.ok) throw new ApiError(res.status, readError(parsed, res.status))
  return parsed as T
}

/* ------------------------------------------------------------------ *
 * Endpoints
 * ------------------------------------------------------------------ */

export const api = {
  /* --- auth --- */
  register: (body: { email: string; password: string; full_name: string }) =>
    request<User>('/auth/register', { method: 'POST', body, anonymous: true }),

  login: (body: { email: string; password: string }) =>
    request<Tokens>('/auth/login', { method: 'POST', body, anonymous: true }),

  me: () => request<User>('/auth/me'),

  /* --- projects --- */
  projects: (limit = 50, offset = 0) =>
    request<Project[]>(`/projects?limit=${limit}&offset=${offset}`),

  project: (id: number) => request<Project>(`/projects/${id}`),

  patchProject: (id: number, body: { name?: string; description?: string; status?: string }) =>
    request<Project>(`/projects/${id}`, { method: 'PATCH', body }),

  deleteProject: (id: number) => request<void>(`/projects/${id}`, { method: 'DELETE' }),

  /**
   * Inspect a source without creating anything. Clones, so it takes
   * seconds. Note ok:false still arrives as HTTP 200 — check `.ok`.
   */
  probe: (body: { source_type: SourceType; url_or_path: string; branch?: string | null }) =>
    request<ProbeResult>('/projects/sources:probe', {
      method: 'POST',
      body: { branch: null, ...body },
    }),

  /** Creates project + first source atomically; 422 writes nothing. */
  createProjectWithSource: (body: {
    name: string
    description?: string | null
    source_type: SourceType
    url_or_path: string
    branch?: string | null
    config_json?: Record<string, unknown> | null
  }) => request<Project>('/projects/with-source', { method: 'POST', body }),

  addSource: (
    id: number,
    body: { source_type: SourceType; url_or_path: string; branch?: string | null },
  ) => request<ProjectSource>(`/projects/${id}/sources`, { method: 'POST', body }),

  deleteSource: (id: number, sourceId: number) =>
    request<void>(`/projects/${id}/sources/${sourceId}`, { method: 'DELETE' }),

  upload: (id: number, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return request<ProjectSource>(`/projects/${id}/upload`, { method: 'POST', formData: fd })
  },

  /* --- phase 1: analyse --- */
  analyze: (id: number, force = false) =>
    request<Job>(`/projects/${id}/analyze`, { method: 'POST', body: { force } }),

  /** Resolves to null when the project has never been analysed. */
  knowledgeBase: (id: number, signal?: AbortSignal) =>
    request<KnowledgeBase | null>(`/projects/${id}/knowledge-base`, { signal }),

  /* --- phase 2: compose --- */
  compose: (
    id: number,
    body: {
      doc_types: DocType[]
      output_formats: OutputFormat[]
      human_review: boolean
      kb_id?: number | null
    },
  ) => request<Job>(`/projects/${id}/compose`, { method: 'POST', body: { kb_id: null, ...body } }),

  /* --- jobs --- */
  projectJobs: (id: number, limit = 50, offset = 0) =>
    request<Job[]>(`/projects/${id}/jobs?limit=${limit}&offset=${offset}`),

  job: (id: number, signal?: AbortSignal) => request<Job>(`/jobs/${id}`, { signal }),

  jobLogs: (id: number, signal?: AbortSignal) =>
    request<JobLog[]>(`/jobs/${id}/logs`, { signal }),

  cancelJob: (id: number) => request<Job>(`/jobs/${id}/cancel`, { method: 'POST' }),

  approveJob: (id: number, approved: boolean, comment?: string) =>
    request<Job>(`/jobs/${id}/approve`, { method: 'POST', body: { approved, comment } }),

  /** EventSource cannot set headers, so the JWT rides as a query param. */
  streamUrl: (id: number) =>
    `${ROOT}/jobs/${id}/stream?token=${encodeURIComponent(tokenStore.access ?? '')}`,

  /* --- documents --- */
  documents: (projectId?: number, limit = 50, offset = 0) =>
    request<Doc[]>(
      `/documents?${projectId ? `project_id=${projectId}&` : ''}limit=${limit}&offset=${offset}`,
    ),

  document: (id: number) => request<Doc>(`/documents/${id}`),

  patchDocument: (id: number, body: { title?: string; content_markdown?: string }) =>
    request<Doc>(`/documents/${id}`, { method: 'PATCH', body }),

  publishDocument: (id: number) => request<Doc>(`/documents/${id}/publish`, { method: 'POST' }),

  /* --- settings (admin) --- */
  llmSettings: () => request<LLMSettings>('/settings/llm'),
  putLlmSettings: (body: LLMSettings) =>
    request<LLMSettings>('/settings/llm', { method: 'PUT', body }),
}
