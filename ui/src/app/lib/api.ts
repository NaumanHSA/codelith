/* ------------------------------------------------------------------ *
 * The single HTTP client. Every request in the studio goes through
 * request() — it attaches the JWT, refreshes once on 401, retries the
 * original call, and only then bounces to sign-in.
 *
 * The base URL comes from VITE_API_URL. Never hardcode a host or port.
 * ------------------------------------------------------------------ */

import type {
  Doc, Features, Job, JobLog, KnowledgeBase, LLMSettings, ProbeResult,
  Project, ProjectSource, Site, SitePageDetail, SiteVersion, Tokens, User,
  DocType, OutputFormat, SourceType,
  ChatEvent, ChatThread, ChatThreadSummary, ProjectApp, AppCatalogItem,
  JobReview, Drift, Preflight, Depth,
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
      doc_types?: DocType[]
      /**
       * Page addresses (`api/endpoints`) or whole sections (`api`) to write
       * into the project's documentation site. Present means page mode;
       * absent falls back to the one-document-per-type path.
       *
       * A section writes only its unwritten, evidence-backed pages; naming a
       * page outright always writes it, which is how you regenerate one.
       * An unknown address or an over-budget scope comes back 422.
       */
      page_slugs?: string[]
      output_formats: OutputFormat[]
      human_review: boolean
      /** How much each page should say. Omitted means `standard`, which is what
       *  every page written before this option existed used. */
      depth?: Depth
      kb_id?: number | null
    },
  ) =>
    request<Job>(`/projects/${id}/compose`, {
      method: 'POST',
      body: { kb_id: null, doc_types: [], page_slugs: [], ...body },
    }),

  /* --- documentation site --- */
  /** Resolves to null when the project has never been analysed. */
  /** Omit `version` for the live site; pass a label to read a frozen snapshot. */
  site: (id: number, version?: string | null, signal?: AbortSignal) =>
    request<Site | null>(`/projects/${id}/site${version ? `?version=${encodeURIComponent(version)}` : ''}`, { signal }),

  /** One page with its prose. Planned pages resolve too, with null content. */
  sitePage: (
    id: number, section: string, slug: string,
    version?: string | null, signal?: AbortSignal,
  ) =>
    request<SitePageDetail>(
      `/projects/${id}/site/pages/${encodeURIComponent(section)}/${encodeURIComponent(slug)}` +
        (version ? `?version=${encodeURIComponent(version)}` : ''),
      { signal },
    ),

  /**
   * Ask for a page the site does not have. Returns it `planned`, with the anchor
   * files retrieval chose — nothing is written until you say so.
   */
  addSitePage: (
    id: number,
    body: { section_slug: string; request: string; title?: string | null },
  ) => request<SitePageDetail>(`/projects/${id}/site/pages`, { method: 'POST', body }),

  /**
   * Rewrite one heading of a page, or the whole page, against instructions.
   * `anchor` is the id stamped on the rendered heading; omit it for the whole page.
   */
  revisePage: (
    id: number, section: string, slug: string,
    body: { instructions: string; anchor?: string | null },
  ) =>
    request<Job>(
      `/projects/${id}/site/pages/${encodeURIComponent(section)}/${encodeURIComponent(slug)}/revise`,
      { method: 'POST', body },
    ),

  /** The revision turns against one heading, oldest first — the conversation. */
  pageRevisions: (id: number, section: string, slug: string, anchor?: string | null) =>
    request<Job[]>(
      `/projects/${id}/site/pages/${encodeURIComponent(section)}/${encodeURIComponent(slug)}/revisions` +
        (anchor ? `?anchor=${encodeURIComponent(anchor)}` : ''),
    ),

  /**
   * Remove a page from the live site. Frozen versions keep their copy, and a page
   * being written right now is refused with a 422 rather than deleted.
   */
  deleteSitePage: (id: number, section: string, slug: string) =>
    request<void>(
      `/projects/${id}/site/pages/${encodeURIComponent(section)}/${encodeURIComponent(slug)}`,
      { method: 'DELETE' },
    ),

  createSiteVersion: (id: number, body: { label: string; notes?: string | null }) =>
    request<SiteVersion>(`/projects/${id}/site/versions`, { method: 'POST', body }),

  /**
   * Download the site as an archive.
   *
   * Fetched rather than navigated to, so the JWT stays in the header where it
   * belongs — a navigation cannot set one, and a token in a URL ends up in
   * history and server logs. The blob is saved client-side.
   */
  exportSite: async (id: number, format: string, version?: string | null) => {
    const query = `format=${encodeURIComponent(format)}` +
      (version ? `&version=${encodeURIComponent(version)}` : '')
    const res = await fetch(`${ROOT}/projects/${id}/site/export?${query}`, {
      headers: tokenStore.access ? { Authorization: `Bearer ${tokenStore.access}` } : {},
    })
    if (!res.ok) {
      let parsed: unknown = null
      try {
        parsed = await res.json()
      } catch {
        parsed = null
      }
      throw new ApiError(res.status, readError(parsed, res.status))
    }
    const disposition = res.headers.get('content-disposition') ?? ''
    const name = /filename="([^"]+)"/.exec(disposition)?.[1] ?? `site-${format}.zip`
    return { blob: await res.blob(), filename: name }
  },

  /* --- jobs --- */
  projectJobs: (id: number, limit = 50, offset = 0) =>
    request<Job[]>(`/projects/${id}/jobs?limit=${limit}&offset=${offset}`),

  /** Every job across the org's projects, newest first. */
  jobs: (limit = 50, offset = 0, status?: string | null, signal?: AbortSignal) =>
    request<Job[]>(
      `/jobs?limit=${limit}&offset=${offset}${status ? `&status=${status}` : ''}`,
      { signal },
    ),

  /** Cancels first when the job is live — deleting a row does not stop a worker. */
  deleteJob: (id: number) => request<void>(`/jobs/${id}`, { method: 'DELETE' }),

  job: (id: number, signal?: AbortSignal) => request<Job>(`/jobs/${id}`, { signal }),

  jobLogs: (id: number, signal?: AbortSignal) =>
    request<JobLog[]>(`/jobs/${id}/logs`, { signal }),

  cancelJob: (id: number) => request<Job>(`/jobs/${id}/cancel`, { method: 'POST' }),

  /**
   * What a held composition is waiting on — the pages QA doubted, flagged first.
   * Project-scoped because approving publishes, and publishing belongs to the
   * documentation feature rather than to jobs in general.
   */
  jobReview: (projectId: number, jobId: number, signal?: AbortSignal) =>
    request<JobReview>(`/projects/${projectId}/compose/${jobId}/review`, { signal }),

  /** Approve publishes the pages already written; reject ends the job. */
  approveJob: (projectId: number, jobId: number, approved: boolean, comment?: string) =>
    request<Job>(`/projects/${projectId}/compose/${jobId}/approve`, {
      method: 'POST',
      body: { approved, comment },
    }),

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

  /* --- ask the codebase --- */
  chatThread: (projectId: number, threadId?: number) =>
    request<ChatThread | null>(
      `/projects/${projectId}/chat/thread${threadId ? `?thread_id=${threadId}` : ''}`,
    ),

  clearChat: (projectId: number, threadId: number) =>
    request<void>(`/projects/${projectId}/chat/thread/${threadId}`, { method: 'DELETE' }),

  /** Recent conversations across every project, for the rail. */
  /** Every feature, with no codebase in the picture. For Home.
   *  Named `appCatalog` because `features` is the settings feature-flag call. */
  /** What changed between the two most recent readings of this codebase. */
  drift: (projectId: number, signal?: AbortSignal) =>
    request<Drift>(`/projects/${projectId}/drift`, { signal }),

  /** What an edit to a file or symbol would touch. The same answer a connected
   *  agent gets from the `before_edit` MCP tool. */
  preflight: (projectId: number, target: string, signal?: AbortSignal) =>
    request<Preflight>(
      `/projects/${projectId}/preflight?target=${encodeURIComponent(target)}`,
      { signal },
    ),

  appCatalog: (signal?: AbortSignal) =>
    request<AppCatalogItem[]>('/apps', { signal }),

  /** What this codebase unlocks, and what it does not yet. */
  projectApps: (projectId: number, signal?: AbortSignal) =>
    request<ProjectApp[]>(`/projects/${projectId}/apps`, { signal }),

  chatThreads: (limit = 40) =>
    request<ChatThreadSummary[]>(`/chat/threads?limit=${limit}`),

  /** Remove a conversation entirely, unlike `clearChat` which empties it. */
  deleteChatThread: (projectId: number, threadId: number) =>
    request<void>(`/projects/${projectId}/chat/threads/${threadId}`, { method: 'DELETE' }),

  /**
   * Download a conversation as Markdown.
   *
   * Fetched rather than linked: the export needs the `Authorization` header, and an
   * `<a download>` cannot send one. The blob is handed to a temporary link so the
   * browser saves it with the filename the server chose.
   */
  exportChatThread: async (projectId: number, threadId: number, fallbackName: string) => {
    const response = await fetch(
      `${ROOT}/projects/${projectId}/chat/threads/${threadId}/export`,
      { headers: { Authorization: `Bearer ${tokenStore.access ?? ''}` } },
    )
    if (!response.ok) throw new ApiError(response.status, 'The conversation could not be exported.')

    const disposition = response.headers.get('Content-Disposition') ?? ''
    const named = /filename="([^"]+)"/.exec(disposition)?.[1]
    const url = URL.createObjectURL(await response.blob())
    const link = document.createElement('a')
    link.href = url
    link.download = named || `${fallbackName || 'conversation'}.md`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  },

  /**
   * Ask a question and read the answer as it is written.
   *
   * Not `EventSource`: it cannot set headers, which is why the job-log stream
   * puts its JWT in the query string — a credential that then lands in server
   * logs and browser history. A question is also a body rather than a query
   * string. So this is a POST read through a stream reader, and the token stays
   * in the Authorization header.
   *
   * The `signal` is what makes the stop button real: aborting the fetch closes
   * the connection, and the server treats that as a cancellation and stops the
   * model rather than generating into a void.
   */
  askStream: async (
    projectId: number,
    body: { question: string; thread_id?: number | null },
    onEvent: (event: ChatEvent) => void,
    signal?: AbortSignal,
  ): Promise<void> => {
    const response = await fetch(`${ROOT}/projects/${projectId}/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${tokenStore.access ?? ''}`,
      },
      body: JSON.stringify(body),
      signal,
    })

    if (!response.ok || !response.body) {
      const detail = await response.text().catch(() => '')
      throw new ApiError(response.status, detail || 'The answer could not be started.')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      // Events are separated by a blank line. A partial one stays in the buffer
      // until the rest of it arrives — a token split across two chunks is
      // ordinary, not an error.
      const parts = buffer.split('\n\n')
      buffer = parts.pop() ?? ''
      for (const part of parts) {
        const line = part.trim()
        if (!line.startsWith('data:')) continue
        try {
          onEvent(JSON.parse(line.slice(5).trim()) as ChatEvent)
        } catch {
          // A malformed frame is not worth killing the answer for.
        }
      }
    }
  },

  /* --- settings --- */
  // Readable by any signed-in user, unlike the rest of /settings: the pipeline
  // view needs it to avoid showing a disabled stage as merely queued.
  features: () => request<Features>('/settings/features'),
  /** Read-only: models are configured in `.env` and resolved at call time. The
   *  PUT that used to sit beside this wrote a row nothing read back. */
  llmSettings: () => request<LLMSettings>('/settings/llm'),
}
