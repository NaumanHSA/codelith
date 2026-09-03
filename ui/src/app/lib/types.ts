/* ------------------------------------------------------------------ *
 * API types, transcribed literally from the contract.
 *
 * IDs are integers everywhere. Do not widen them to string — a previous
 * build did, called .slice() on one, and blanked the app.
 *
 * Enums are typed as a known union widened with (string & {}) so an
 * unrecognised value from a newer backend renders readably instead of
 * crashing a lookup.
 * ------------------------------------------------------------------ */

type Open<T extends string> = T | (string & {})

export type Role = 'admin' | 'manager' | 'reviewer' | 'viewer'

export interface User {
  id: number
  email: string
  full_name: string | null
  role: Open<Role>
  org_id: number
  is_active: boolean
}

export interface Tokens {
  access_token: string
  refresh_token: string
  token_type: string
}

export type SourceType = Open<'github' | 'gitlab' | 'bitbucket' | 'local'>

export interface ProbeResult {
  ok: boolean
  source_type: SourceType
  url_or_path: string
  resolved_path: string | null
  branch: string | null
  commit_sha: string | null
  file_count: number | null
  analysable_files: number | null
  languages: Record<string, number> | null
  error: string | null
}

export interface ProjectSource {
  id: number
  project_id: number
  source_type: SourceType
  url_or_path: string
  branch: string | null
  config_json: {
    probe?: {
      file_count?: number
      analysable_files?: number
      languages?: Record<string, number>
      commit_sha?: string
    }
  } | null
  created_at: string
}

export interface Project {
  id: number
  org_id: number
  name: string
  slug: string
  description: string | null
  status: string
  created_at: string
  updated_at: string
  sources: ProjectSource[] | null
  /** `doc_count` is the legacy single-shot pipeline; `page_count` is written site pages. */
  stats: {
    source_count: number
    job_count: number
    doc_count: number
    page_count: number
  } | null
  latest_job: { id: number; status: JobStatus } | null
  /** Status of the most recent knowledge base, null if never analysed. */
  kb_status: KBStatus | null
  /** Whether features can run. Computed by the server — never re-derive it here. */
  apps_ready: boolean
}

export type JobStatus = Open<
  'pending' | 'running' | 'awaiting_review' | 'completed' | 'failed' | 'cancelled'
>
export type StepStatus = Open<'pending' | 'running' | 'completed' | 'failed'>
export type JobType = Open<'analysis' | 'composition'>

/**
 * Statuses after which the job will never change again — stop polling.
 *
 * `awaiting_review` is deliberately *not* here. It used to be, correctly: the gate
 * could only end a job, so nothing would ever follow it. Now approval resumes the
 * run, so a page that stopped polling at the hold would sit on a stale status while
 * the pipeline published behind it.
 */
export const TERMINAL_JOB_STATUSES = ['completed', 'failed', 'cancelled']
export const isTerminal = (s: JobStatus) => TERMINAL_JOB_STATUSES.includes(s)

export interface JobStep {
  id: number
  name: string
  status: StepStatus
  started_at: string | null
  completed_at: string | null
  duration_seconds: number | null
  output_json: Record<string, unknown> | null
}

export interface Job {
  id: number
  project_id: number
  /** Denormalised so a cross-project job list can label a row without a second call. */
  project_name: string | null
  job_type: JobType
  status: JobStatus
  config_json: Record<string, unknown> | null
  /**
   * What the job was asked to do, in the reader's vocabulary. `labels` are
   * pre-rendered section names, so a job row can be labelled without also
   * fetching the site. Empty for jobs created before scopes existed.
   */
  scope: {
    kind?: 'pages' | 'documents'
    sections?: string[]
    pages?: string[]
    labels?: string[]
  } | null
  doc_types: string[] | null
  output_formats: string[] | null
  requires_human_review: boolean
  error_message: string | null
  started_at: string | null
  completed_at: string | null
  created_at: string
  steps: JobStep[] | null
}

export type LogLevel = Open<'debug' | 'info' | 'warning' | 'error'>

export interface JobLog {
  id: number
  agent: string | null
  level: LogLevel
  message: string
  timestamp: string
  extra: Record<string, unknown> | null
}

export type KBStatus = Open<'pending' | 'running' | 'ready' | 'degraded' | 'failed' | 'stale'>

export type ModuleRole = Open<
  | 'api' | 'service' | 'data_access' | 'model' | 'schema' | 'worker'
  | 'ui' | 'cli' | 'config' | 'infra' | 'test' | 'utility' | 'unknown'
>

export type EntityKind = Open<
  | 'route' | 'entrypoint' | 'service' | 'dependency' | 'env_var' | 'config_file'
  | 'datastore' | 'external_api' | 'cli_command' | 'scheduled_task' | 'event'
  | 'infra_resource' | 'test_suite'
>

export type DocType = Open<
  'architecture' | 'api' | 'getting_started' | 'deployment' | 'modules'
>

/** pdf is deliberately absent — the backend does not implement it. */
export type OutputFormat = Open<'markdown' | 'docx' | 'mkdocs' | 'docusaurus'>

export interface KnowledgeBase {
  knowledge_base: {
    id: number
    project_id: number
    job_id: number | null
    commit_sha: string | null
    status: KBStatus
    schema_version: number
    /** Whatever kb_persister recorded. Keys are the backend's, not ours. */
    stats: {
      modules?: number
      entities?: number
      indexed_chunks?: number
      summarised_modules?: number
      missing_summaries?: number
      languages?: string[]
    } | null
    error_message: string | null
    created_at: string
    completed_at: string | null
  }
  module_count: number
  entity_count: number
  narrative_topics: string[] | null
  languages: string[] | null
  roles: Record<string, number> | null
  entity_kinds: Record<string, number> | null
  suggested_doc_types: { doc_type: DocType; confidence: number; reason: string }[] | null
  /** Questions worth asking about this codebase, written during analysis. Empty for a
   *  reading taken before this existed — the chat page then offers nothing rather than
   *  falling back to generic ones that say nothing has been read. */
  suggested_questions: string[] | null
  top_modules:
    | { path: string; name: string; role: ModuleRole; loc: number | null; summary: string | null }[]
    | null
  sample_routes: { kind: EntityKind; name: string; detail: string | null }[] | null
  key_dependencies: string[] | null
  entrypoints: string[] | null
}

/* ------------------------------------------------------------------ *
 * Documentation site
 *
 * One site per project, grown a section at a time. Most pages are
 * `planned`: in the nav, not yet written — which is the point. The nav
 * doubles as the roadmap for a project's documentation, so planned
 * pages are shown greyed with a Generate action rather than hidden.
 * ------------------------------------------------------------------ */

export type PageStatus = Open<
  'planned' | 'generating' | 'ready' | 'stale' | 'orphaned' | 'failed'
>

export interface SitePage {
  id: number
  section_slug: string
  slug: string
  title: string
  doc_type: DocType
  intent: string | null
  status: PageStatus
  order_index: number
  pinned: boolean
  word_count: number
  /** Provenance. Null until the page has been written. */
  job_id: number | null
  kb_id: number | null
  commit_sha: string | null
  /** Files the page was actually written from. */
  source_files: string[] | null
  /** Anchor files analysis proposed, before anything was written. */
  key_files: string[] | null
  confidence: number | null
  reason: string | null
  /** QA's verdict on this page, and the claim checks behind it. */
  qa_score: number | null
  qa: {
    score?: number
    approved?: boolean
    issues?: string[]
    claims_checked?: number
    claims_passed?: number
  } | null
  updated_at: string | null
}

/** One page with its prose — fetched a page at a time, not with the map. */
export interface SitePageDetail extends SitePage {
  content_markdown: string | null
  /** What the page said before its last rewrite — null if written only once. */
  previous_markdown: string | null
  /** Share of paragraphs naming things that exist, plus the ones that did not. */
  grounding?: {
    paragraphs: number
    grounded: number
    unverified: number
    unchecked: number
    score: number
    problems: { paragraph: number; excerpt: string; unknown: string[] }[]
  }
  section_title: string | null
}

export interface SiteVersion {
  id: number
  site_id: number
  label: string
  notes: string | null
  commit_sha: string | null
  page_count: number
  snapshot_at: string | null
  created_at: string
}

export interface SiteSection {
  slug: string
  title: string
  order_index: number
  pinned: boolean
  pages: SitePage[]
}

export interface Site {
  id: number
  project_id: number
  title: string
  kb_id: number | null
  sections: SiteSection[]
  /** No longer proposed by analysis. Never deleted, off the live nav. */
  orphaned_pages: SitePage[] | null
  /** PageStatus → count, across every page including orphans. */
  page_counts: Record<string, number> | null
  /** The version being read. Null is the live site — the one that gets written. */
  version: string | null
  /** Every frozen snapshot, newest first. */
  versions: SiteVersion[] | null
  /**
   * The landing page, derived from the map on every read so it cannot go
   * stale. Prose only — the index of sections and pages is `sections`
   * above, rendered by the reader.
   */
  home_markdown: string | null
  updated_at: string | null
}

export interface Doc {
  id: number
  project_id: number
  job_id: number | null
  doc_type: DocType
  title: string
  content_markdown: string
  storage_path: string | null
  version: number
  status: Open<'draft' | 'review' | 'published'>
  created_at: string
}

/**
 * What each model tier is pointed at.
 *
 * Shaped per tier, because the tiers choose their provider independently — the
 * quality one can be hosted while the fast one stays local. `api_key` is never
 * returned; `openai_key_set` says only whether one is configured.
 */
export interface LLMSettings {
  quality_provider: string
  quality_model: string
  quality_base_url: string
  quality_context_window: number

  fast_provider: string
  fast_model: string
  fast_base_url: string
  fast_context_window: number

  embedding_provider: string
  embedding_model: string
  embedding_base_url: string

  openai_key_set: boolean

  /** False while models come from `.env`. The page renders facts, not inputs. */
  editable: boolean
  /** Anything the startup check found — an openai tier with no key, say. */
  problems: string[]

  temperature: number
  max_tokens: number
  max_react_iterations: number
}

/** Optional stages that may be switched off in config. */
export interface Features {
  diagrams_enabled: boolean
}

/* ------------------------------------------------------------------ *
 * Asking the codebase.
 * ------------------------------------------------------------------ */

export interface ChatSource {
  kind: string
  title: string
  why: string
}

/** The material behind one citation, fetched on demand rather than stored on the
 *  message — forty spans of several kilobytes each would multiply a conversation by
 *  the size of the code it quoted. */
export interface EvidenceBody {
  path: string
  start_line: number | null
  end_line: number | null
  content: string
  /** The cited lines are no longer stored — the file has been re-chunked since. */
  partial: boolean
  language: string | null
}

export interface ChatMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  token_count: number
  evidence: {
    counts?: Record<string, number>
    intents?: string[]
    routed_by?: string
    sources?: ChatSource[]
  }
  citations: string[]
  /** Citations the model produced that did not resolve, and were demoted. */
  stripped: string[]
}

export interface ChatThread {
  id: number
  title: string
  messages: ChatMessage[]
  token_count: number
  context_window: number
}

/** One row in the rail. No messages — the list carries forty of these. */
export interface ChatThreadSummary {
  id: number
  project_id: number
  project_name: string
  title: string
  message_count: number
  last_message_at: string | null
}

/** One frame of a streamed answer. */
export type ChatEvent =
  | { type: 'thread'; thread_id: number; title: string }
  | {
      type: 'evidence'
      counts: Record<string, number>
      intents: string[]
      routed_by: string
      sources: ChatSource[]
    }
  | { type: 'token'; text: string }
  | { type: 'usage'; prompt_tokens: number; answer_tokens: number; context_window: number }
  | { type: 'done'; text: string; citations: string[]; stripped: string[] }
  | { type: 'stopped' }
  | { type: 'error'; message: string }

/** One thing an analysed codebase unlocks. Mirrors `app/features/registry.py`. */
export interface ProjectApp {
  id: string
  label: string
  blurb: string
  /** The one-line form, for a card beside two others. */
  short: string
  needs: string[]
  route: string
  /** `available` · `locked` · `planned` */
  state: 'available' | 'locked' | 'planned'
  /** Why it is not available. Says what to do, not what went wrong. */
  reason: string
}

/** The feature catalogue, independent of any codebase. `GET /features`. */
export interface AppCatalogItem {
  id: string
  label: string
  blurb: string
  /** The one-line form, for a card beside two others. */
  short: string
  needs: string[]
  /** Contains `{id}` — substitute a project id. */
  route_template: string
  built: boolean
}


/** One page's QA verdict, as the review panel shows it. */
export interface ReviewPage {
  key: string
  title: string
  approved: boolean
  score: number | null
  claims_total: number
  claims_passed: number | null
  notes: string | null
}

/** What a composition held at the review gate is waiting on. */
export interface JobReview {
  job_id: number
  status: JobStatus
  awaiting_review: boolean
  pages_written: number
  flagged_count: number
  pages: ReviewPage[]
}


/* ── Drift: what changed between two readings ─────────────────────────────── */

export interface DriftModule {
  path: string
  name: string
  change: 'added' | 'removed' | 'rewritten' | 'grew' | 'shrank'
  loc_before: number
  loc_after: number
  loc_delta: number
}

export interface DriftEntity {
  kind: string
  name: string
  change: 'added' | 'removed'
  source_path: string | null
}

/** A written page whose source has moved under it. */
export interface DriftPageAtRisk {
  address: string
  title: string
  changed_files: string[]
  reason: string
}

export interface Drift {
  project_id: number
  from_commit: string | null
  to_commit: string | null
  summary: string
  /** False when the codebase has been read only once — which is not the same as
   *  "nothing changed", and must not be rendered as an empty diff. */
  comparable: boolean
  modules: DriftModule[]
  entities: DriftEntity[]
  pages_at_risk: DriftPageAtRisk[]
}

/* ── Pre-flight: what an edit would touch ─────────────────────────────────── */

export interface PreflightCaller {
  file: string
  symbol: string
}

/** A file that imports the target, directly or through others. */
export interface PreflightReached {
  path: string
  distance: number
  is_test: boolean
}

export interface PreflightCitedBy {
  address: string
  title: string
}

export interface Preflight {
  target: string
  /** False when nothing in the codebase resolves to the target — a real answer,
   *  not an error, and rendered as one. */
  found: boolean
  kind: 'file' | 'symbol' | 'unknown'
  risk: 'low' | 'moderate' | 'high' | 'unknown'
  headline: string
  /** The prose a connected agent gets over MCP, verbatim. */
  brief: string
  files: string[]
  defined_at: string[]
  callers: PreflightCaller[]
  dependents: string[]
  reached: PreflightReached[]
  tests: string[]
  documented_in: PreflightCitedBy[]
  facts: string[]
}

/** How much detail a written page goes into. Mirrors `apps/documentation/depth.py`;
 *  `tests/unit/apps/test_depth.py` fails if the two lists stop agreeing. */
export type Depth = 'concise' | 'standard' | 'detailed'

/** Whether analysing again would read anything new. See `services/head_check.py`. */
export interface AnalysisPreview {
  /** False when the current commit could not be determined — never a reason to
   *  refuse the run, only a caveat to show above the button. */
  checked: boolean
  never_analysed: boolean
  changed: boolean
  analysed_commit: string | null
  current_commit: string | null
  branch: string | null
  reason: string | null
  summary: string
}

/* ── Model registry: what this installation can talk to ──────────────────── */

export type Provider = 'openai' | 'anthropic' | 'local'
export type Tier = 'quality' | 'fast' | 'embedding'

export interface ConfiguredModel {
  id: number
  label: string
  provider: Provider
  model: string
  /** `chat` | `embedding` — which tiers may be pointed at it. Stored, because the
   *  fields are identical and only the call differs. */
  kind: 'chat' | 'embedding'
  /** `local` only. The hosted providers have a fixed endpoint. */
  base_url: string | null
  context_window: number | null
  /** Whether a key is stored. Never the key itself. */
  api_key_set: boolean
  last_test: {
    ok?: boolean
    detail?: string
    dimensions?: number | null
    served_model?: string | null
    at?: string
  }
  /** Tiers currently pointed at this one. */
  serving: Tier[]
}

export interface ModelRegistry {
  models: ConfiguredModel[]
  /** A tier missing from this still resolves from `.env`. */
  tiers: Partial<Record<Tier, number>>
  unassigned: Tier[]
}

export interface ModelTest {
  ok: boolean
  detail: string
  dimensions: number | null
  served_model: string | null
}

/** What a form sends. `api_key` blank on an update means "leave the stored one". */
export interface ModelDraft {
  label: string
  provider: Provider
  model: string
  base_url?: string | null
  context_window?: number | null
  api_key?: string | null
  tier_hint?: Tier | null
}
