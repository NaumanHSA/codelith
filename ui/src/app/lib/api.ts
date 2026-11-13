/* ------------------------------------------------------------------ *
 * The single HTTP client. Every request in the studio goes through
 * request() — it attaches the JWT, refreshes once on 401, retries the
 * original call, and only then bounces to sign-in.
 *
 * The base URL comes from VITE_API_URL. Never hardcode a host or port.
 * ------------------------------------------------------------------ */

import type {
  Comparison,
  QACatalog,
  QASandbox,
  QADesignedTest,
  FindingsMap,
  HistoryStep,
  FileHistoryStep,
  CommitsBetween,
  Storage,
  QAFinding,
  QAFindingDetail,
  QARun,
  FileDiff,
  Reading,
  Runbook,
  Doc, Features, Job, JobLog, KnowledgeBase, LLMSettings, ProbeResult,
  Project, ProjectSource, Site, SitePageDetail, SiteVersion, Tokens, User,
  DocType, OutputFormat, SourceType,
  ChatEvent, ChatThread, ChatThreadSummary, ProjectApp, AppCatalogItem,
  JobReview, Drift, Preflight, Depth, AnalysisPreview, AutoRead, ReviewDetail, ReviewList, FlowSummary, FlowDetail,
  ModelRegistry, ModelDraft, ModelTest, Tier, EvidenceBody, Atlas, FileCalls, RetrievalInspection, Facts, RiskRanking, AgentActivity, CodebaseDocs,
  Publication, PublishAccepted, RendererInfo, Architecture, Narratives,
  FileTree, SourceFile, Modules,
  Tour, Hotspots, TimelineReading,
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

/** `?before=&after=` for the two readings a comparison is between, when named. */
function pairQuery(before?: number, after?: number) {
  const q = new URLSearchParams()
  if (before) q.set('before', String(before))
  if (after) q.set('after', String(after))
  const text = q.toString()
  return text ? `?${text}` : ''
}

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

  /** Liveness, plus whether the API is inside a container. The browser cannot
   *  work the second one out, and it changes what a model endpoint should say. */
  health: () =>
    fetch(`${API_BASE}/health`).then(
      r => r.json() as Promise<{ status: string; env: string; container: boolean }>,
    ),

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

  /** Whether analysing again would read anything new. One `git ls-remote`, no
   *  clone — fast enough to sit behind a dialog with a spinner. */
  analysisPreview: (id: number, signal?: AbortSignal) =>
    request<AnalysisPreview>(`/projects/${id}/analyze/preview`, { signal }),

  /** Files that change often, that much depends on, and that no test reaches. */
  hotspots: (id: number, limit = 15, signal?: AbortSignal) =>
    request<Hotspots>(`/projects/${id}/hotspots?limit=${limit}`, { signal }),
  /** Each kept reading's size and links between parts, oldest first. */
  timeline: (id: number, signal?: AbortSignal) =>
    request<{ readings: TimelineReading[] }>(`/projects/${id}/timeline`, { signal }),

  /** A guided walk through a codebase, built from its reading (`apps/tour`). */
  tour: (id: number, signal?: AbortSignal) => request<Tour>(`/projects/${id}/tour`, { signal }),
  tourMarkdown: (id: number, signal?: AbortSignal) =>
    request<{ filename: string; markdown: string }>(`/projects/${id}/tour/markdown`, { signal }),

  /** What it needs, and how to install, run and test it (`knowledge/runbook.py`). */
  runbook: (id: number, signal?: AbortSignal) => request<Runbook>(`/projects/${id}/runbook`, { signal }),

  /** The instruction file coding agents read, written from the reading (`knowledge/guide.py`). */
  agentGuide: (id: number, format: 'agents' | 'claude' = 'agents', signal?: AbortSignal) =>
    request<{ commit: string | null; filename: string; markdown: string; recipes: { id: string; title: string; lines: string[] }[] }>(
      `/projects/${id}/agent-guide?format=${format}`,
      { signal },
    ),

  /** Every way into a codebase, and one's path through it (`knowledge/flows.py`). */
  flows: (id: number, signal?: AbortSignal) =>
    request<{ commit: string | null; flows: FlowSummary[] }>(`/projects/${id}/flows`, { signal }),
  flow: (id: number, flowId: string, signal?: AbortSignal) =>
    request<FlowDetail>(`/projects/${id}/flows/${encodeURIComponent(flowId)}`, { signal }),

  /** Reviews of changes to a codebase, from the studio, a terminal or an agent. */
  reviews: (id: number, signal?: AbortSignal) => request<ReviewList>(`/projects/${id}/reviews`, { signal }),
  review: (id: number, reviewId: number, signal?: AbortSignal) =>
    request<ReviewDetail>(`/projects/${id}/reviews/${reviewId}`, { signal }),
  /** Review the working copy of a codebase read from a folder on this machine. */
  reviewWorkingCopy: (id: number, against?: string) =>
    request<ReviewDetail>(`/projects/${id}/reviews`, { method: 'POST', body: { against: against || null, source: 'studio' } }),

  /** Switch "read every commit" for a local codebase. */
  setAutoRead: (id: number, on: boolean) =>
    request<AutoRead>(`/projects/${id}/auto-read`, { method: 'PUT', body: { on } }),

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
  /** What changed between two readings: the two most recent unless named. */
  drift: (projectId: number, signal?: AbortSignal, before?: number, after?: number) =>
    request<Drift>(`/projects/${projectId}/drift${pairQuery(before, after)}`, { signal }),

  /** QA (`apps/qa`): what can be checked, runs, findings, decisions. */
  qaCatalog: (projectId: number, signal?: AbortSignal) => request<QACatalog>(`/projects/${projectId}/qa/catalog`, { signal }),
  qaRuns: (projectId: number, signal?: AbortSignal) => request<QARun[]>(`/projects/${projectId}/qa/runs`, { signal }),
  /** What QA has checked and what is open, per file (`api/v1/findings.py`). */
  findingsMap: (projectId: number, signal?: AbortSignal) => request<FindingsMap>(`/projects/${projectId}/findings`, { signal }),
  /** A run written out: the fix plan as Markdown, or SARIF. Fetched with the token, like the exports. */
  qaReport: async (projectId: number, runId: number, format: 'markdown' | 'sarif') => {
    const response = await fetch(`${ROOT}/projects/${projectId}/qa/runs/${runId}/report?format=${format}`, {
      headers: { Authorization: `Bearer ${tokenStore.access ?? ''}` },
    })
    if (!response.ok) throw new ApiError(response.status, 'The report could not be written.')
    const named = /filename="([^"]+)"/.exec(response.headers.get('Content-Disposition') ?? '')?.[1]
    return { text: await response.text(), filename: named || `qa-run-${runId}.${format === 'sarif' ? 'sarif' : 'md'}` }
  },
  qaSandbox: (projectId: number, signal?: AbortSignal) => request<QASandbox>(`/projects/${projectId}/qa/sandbox`, { signal }),
  qaDesigned: (projectId: number, runId: number, signal?: AbortSignal) =>
    request<QADesignedTest[]>(`/projects/${projectId}/qa/runs/${runId}/designed`, { signal }),
  /** The designed tests worth keeping, as a ZIP. Fetched for the same reason as the exports below. */
  qaDesignedArchive: async (projectId: number, runId: number) => {
    const response = await fetch(`${ROOT}/projects/${projectId}/qa/runs/${runId}/designed/archive`, {
      headers: { Authorization: `Bearer ${tokenStore.access ?? ''}` },
    })
    if (!response.ok) throw new ApiError(response.status, 'The tests could not be downloaded.')
    const named = /filename="([^"]+)"/.exec(response.headers.get('Content-Disposition') ?? '')?.[1]
    saveBlob(await response.blob(), named || `qa-run-${runId}-designed-tests.zip`)
  },
  qaRun: (projectId: number, runId: number, signal?: AbortSignal) =>
    request<QARun>(`/projects/${projectId}/qa/runs/${runId}`, { signal }),
  qaStart: (projectId: number, body: { areas: string[]; depth: string; scope: QARun['scope']; online: boolean }) =>
    request<QARun>(`/projects/${projectId}/qa/runs`, { method: 'POST', body }),
  qaCancel: (projectId: number, runId: number) =>
    request<QARun>(`/projects/${projectId}/qa/runs/${runId}/cancel`, { method: 'POST' }),
  qaFindings: (projectId: number, runId: number, signal?: AbortSignal) =>
    request<QAFinding[]>(`/projects/${projectId}/qa/runs/${runId}/findings`, { signal }),
  qaFinding: (projectId: number, findingId: number, signal?: AbortSignal) =>
    request<QAFindingDetail>(`/projects/${projectId}/qa/findings/${findingId}`, { signal }),
  qaSetState: (projectId: number, fingerprint: string, status: 'open' | 'dismissed' | 'accepted', reason = '') =>
    request<null>(`/projects/${projectId}/qa/findings/${fingerprint}/state`, {
      method: 'PUT',
      body: { status, reason },
    }),

  /** Every finished reading, newest first (`api/v1/readings.py`). */
  readings: (projectId: number, signal?: AbortSignal) => request<Reading[]>(`/projects/${projectId}/readings`, { signal }),
  /** Every reading against the one before it, newest first. */
  history: (projectId: number, signal?: AbortSignal) => request<HistoryStep[]>(`/projects/${projectId}/history`, { signal }),
  /** The readings where one file changed. */
  fileHistory: (projectId: number, path: string, signal?: AbortSignal) =>
    request<FileHistoryStep[]>(`/projects/${projectId}/file-history?path=${encodeURIComponent(path)}`, { signal }),
  /** The commits between two readings: reachable from the later one, not the earlier. */
  compareCommits: (projectId: number, before?: number, after?: number, signal?: AbortSignal) => {
    const q = new URLSearchParams()
    if (before) q.set('before', String(before))
    if (after) q.set('after', String(after))
    return request<CommitsBetween>(`/projects/${projectId}/compare/commits?${q}`, { signal })
  },
  /** Read the codebase's commits from its source, for readings taken before they were kept. */
  fetchHistory: (projectId: number) =>
    request<{ ok: boolean; reason: string; commits: number; new: number }>(`/projects/${projectId}/history/fetch`, { method: 'POST' }),
  /** What the kept source takes, overall and per codebase. */
  storage: (signal?: AbortSignal) => request<Storage>('/settings/storage', { signal }),
  /** Keep the files of a reading taken before readings kept them, from git. */
  fetchReadingFiles: (projectId: number, kbId: number) =>
    request<{ ok: boolean; reason: string; files: number; project_files: number; new_blobs: number }>(
      `/projects/${projectId}/readings/${kbId}/files`,
      { method: 'POST' },
    ),
  /** The files that changed between two readings (`knowledge/compare.py`). */
  compare: (projectId: number, before?: number, after?: number, signal?: AbortSignal) =>
    request<Comparison>(`/projects/${projectId}/compare${pairQuery(before, after)}`, { signal }),
  /** One file between two readings, line by line. */
  compareFile: (
    projectId: number,
    path: string,
    opts: { before?: number; after?: number; oldPath?: string | null },
    signal?: AbortSignal,
  ) => {
    const q = new URLSearchParams({ path })
    if (opts.before) q.set('before', String(opts.before))
    if (opts.after) q.set('after', String(opts.after))
    if (opts.oldPath) q.set('old_path', opts.oldPath)
    return request<FileDiff>(`/projects/${projectId}/compare/file?${q}`, { signal })
  },

  /** Everything a question retrieves, with bodies and scores. Development builds
   *  only: the server answers 404 in production. Calls no model to answer. */
  inspectRetrieval: (projectId: number, question: string, signal?: AbortSignal) =>
    request<RetrievalInspection>(`/retrieval/projects/${projectId}/inspect`, {
      method: 'POST',
      body: { question },
      signal,
    }),

  /** The facts analysis extracted: counts for every kind, and the facts of `kinds`. */
  facts: (projectId: number, kinds: string[] = [], signal?: AbortSignal) =>
    request<Facts>(
      `/projects/${projectId}/entities${kinds.length ? '?' + kinds.map(k => `kind=${encodeURIComponent(k)}`).join('&') : ''}`,
      { signal },
    ),

  /** Files ranked by what an edit to them would touch. */
  risk: (projectId: number, limit = 15, signal?: AbortSignal) =>
    request<RiskRanking>(`/projects/${projectId}/risk?limit=${limit}`, { signal }),

  /** Documentation counted per codebase: pages by state, words, versions, publishing. */
  documentationOverview: (signal?: AbortSignal) =>
    request<CodebaseDocs[]>('/documentation/overview', { signal }),

  /** Which agents have called the MCP server, and their most recent calls. Admin only. */
  /** What agents asked and could not get: empty answers, and questions asked again and again. */
  agentGaps: (signal?: AbortSignal) =>
    request<
      {
        tool: string
        asked: string
        project_id: number | null
        project_name: string | null
        times: number
        empty: boolean
        clients: string[]
        last_seen: string
      }[]
    >('/agents/gaps', { signal }),
  agentActivity: (limit = 30, signal?: AbortSignal) =>
    request<AgentActivity>(`/agents/activity?limit=${limit}`, { signal }),

  /** The codebase as a map: every file with its kind and component, facts as
   *  nodes, and the import edges. */
  atlas: (projectId: number, signal?: AbortSignal) =>
    request<Atlas>(`/projects/${projectId}/graph`, { signal }),

  /** One file from the inside: its functions and classes, and the calls in and out. */
  fileCalls: (projectId: number, path: string, signal?: AbortSignal) =>
    request<FileCalls>(
      `/projects/${projectId}/graph/calls?path=${encodeURIComponent(path)}`,
      { signal },
    ),

  /** What an edit to a file or symbol would touch. The same answer a connected
   *  agent gets from the `before_edit` MCP tool. */
  preflight: (projectId: number, target: string, signal?: AbortSignal) =>
    request<Preflight>(
      `/projects/${projectId}/preflight?target=${encodeURIComponent(target)}`,
      { signal },
    ),

  /* ── Publishing ─────────────────────────────────────────────────── *
   * Export downloads a ZIP; publishing gives the site a URL that other
   * people can open. The publish call is the one worth reading: it
   * answers 202 whether or not it started anything, and `unchanged`
   * says which happened.
   * ---------------------------------------------------------------- */

  /** What this machine can build. Asked before anything is offered. */
  renderers: (signal?: AbortSignal) =>
    request<RendererInfo[]>('/publishing/renderers', { signal }),

  /** Everything published for this project, newest first. */
  publications: (projectId: number, signal?: AbortSignal) =>
    request<Publication[]>(`/projects/${projectId}/site/publications`, { signal }),

  /** Everything published anywhere. Once a link is out there, the question has no
   *  project in it. */
  allPublications: (signal?: AbortSignal) =>
    request<Publication[]>('/publications', { signal }),

  /**
   * Publish the live site, or a frozen version.
   *
   * `force` is sent only after the reader has been told that nothing has
   * changed, so the unchanged answer is never something they have to
   * dismiss twice.
   */
  publishSite: (
    projectId: number,
    body: { target?: string; renderer?: string | null; force?: boolean } = {},
  ) =>
    // `request` serialises for us, so this passes the object rather than a string.
    request<PublishAccepted>(`/projects/${projectId}/site/publish`, {
      method: 'POST',
      body: { target: 'live', force: false, ...body },
    }),

  /** Mint a new address. Every link that was ever shared stops working. */
  rotatePublication: (publicationId: number) =>
    request<Publication>(`/publications/${publicationId}/rotate`, { method: 'POST' }),

  /** Point the address back at the build before this one. */
  rollbackPublication: (publicationId: number) =>
    request<Publication>(`/publications/${publicationId}/rollback`, { method: 'POST' }),

  /** Stop serving, and delete the files. The record of it survives. */
  unpublish: (publicationId: number) =>
    request<Publication>(`/publications/${publicationId}`, { method: 'DELETE' }),

  appCatalog: (signal?: AbortSignal) =>
    request<AppCatalogItem[]>('/apps', { signal }),

  /**
   * The shape of the system: services, the relations between them, layers,
   * patterns and the stack. Stored on every analysis and, until now, read by
   * nothing.
   */
  architecture: (projectId: number, signal?: AbortSignal) =>
    request<Architecture>(`/projects/${projectId}/architecture`, { signal }),

  narratives: (projectId: number, signal?: AbortSignal) =>
    request<Narratives>(`/projects/${projectId}/narratives`, { signal }),

  modules: (projectId: number, signal?: AbortSignal) =>
    request<Modules>(`/projects/${projectId}/modules`, { signal }),

  /** Every file of the latest reading, or of `reading`. */
  files: (projectId: number, signal?: AbortSignal, reading?: number | null) =>
    request<FileTree>(`/projects/${projectId}/files${reading ? `?reading=${reading}` : ''}`, { signal }),

  /** A path has slashes in it, and each segment needs encoding while the
   *  separators do not - `encodeURIComponent` on the whole thing would turn
   *  `src/a.js` into one unmatchable segment. */
  file: (projectId: number, path: string, signal?: AbortSignal, reading?: number | null) =>
    request<SourceFile>(
      `/projects/${projectId}/files/${path.split('/').map(encodeURIComponent).join('/')}${reading ? `?reading=${reading}` : ''}`,
      { signal },
    ),

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

  /** The source behind one citation — `path/to/file.py:12-48`. */
  evidence: (projectId: number, ref: string, signal?: AbortSignal) =>
    request<EvidenceBody>(
      `/projects/${projectId}/evidence?ref=${encodeURIComponent(ref)}`,
      { signal },
    ),

  /* --- the model registry: what this installation can talk to --- */
  models: (signal?: AbortSignal) =>
    request<ModelRegistry>('/settings/models', { signal }),

  addModel: (body: ModelDraft) =>
    request<ModelRegistry>('/settings/models', { method: 'POST', body }),

  updateModel: (id: number, body: ModelDraft) =>
    request<ModelRegistry>(`/settings/models/${id}`, { method: 'PUT', body }),

  deleteModel: (id: number) =>
    request<ModelRegistry>(`/settings/models/${id}`, { method: 'DELETE' }),

  assignTier: (tier: Tier, model_id: number) =>
    request<ModelRegistry>('/settings/models/tiers', {
      method: 'PUT',
      body: { tier, model_id },
    }),

  /** Places a real call against a stored endpoint. */
  testModel: (id: number, tier: Tier) =>
    request<ModelTest>(`/settings/models/${id}/test?tier=${tier}`, { method: 'POST' }),

  /** Places a real call against fields that have not been saved yet — the useful
   *  moment to learn an endpoint is unreachable is while the form is still open. */
  testDraft: (body: ModelDraft) =>
    request<ModelTest>('/settings/models/test', { method: 'POST', body }),
}

/** Hand a blob to the browser to save, under this name. */
export function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = name
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
