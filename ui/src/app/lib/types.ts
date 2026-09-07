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

/** A component that appeared, went, was renamed, or became something else. */
export interface DriftService {
  name: string
  change: 'added' | 'removed' | 'renamed' | 'retyped'
  type_before: string
  type_after: string
  /** Only on `renamed`. Service names are the model's words and two readings do not
   *  always agree on them, so a rename is the common case, not the rare one. */
  name_before: string
}

/** An edge that appeared, went, or changed its verb. */
export interface DriftRelation {
  source: string
  target: string
  change: 'added' | 'removed' | 'reworded'
  kind: string
  kind_before: string
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
  services: DriftService[]
  relations: DriftRelation[]
  /** The same distinction as `comparable`, one level down: both readings have
   *  modules, only readings taken since the architecture agent landed have a map.
   *  False means the shape diff was not attempted, not that the shape held. */
  architecture_comparable: boolean
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
  /** Who imports the target. */
  dependents: string[]
  /** What the target imports. The one leg of the graph that used to be reachable
   *  only through MCP. */
  imports: string[]
  reached: PreflightReached[]
  tests: string[]
  documented_in: PreflightCitedBy[]
  facts: string[]
  /** `reach_weight`: capped reach plus five per written page. The ranking every
   *  caller is meant to sort on. */
  weight: number
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


/* ------------------------------------------------------------------ *
 * Published sites.
 *
 * A publication is an address; a build is what that address is serving.
 * Republishing mints a new build and repoints the address, which is why
 * the panel shows one row per publication rather than one per build.
 * ------------------------------------------------------------------ */

export interface PublicationBuild {
  id: number
  status: 'running' | 'succeeded' | 'failed' | 'cancelled'
  content_hash: string
  renderer: string
  renderer_version: string
  page_count: number
  file_count: number
  bytes_total: number
  commit_sha: string | null
  error: string | null
  verify_json: Record<string, unknown>
  created_at: string
  finished_at: string | null
}

export interface Publication {
  id: number
  project_id: number
  /** Which codebase it came from, for the page that lists every publication. */
  project_name: string
  /** `live`, or the label of a frozen version. */
  target: string
  slug: string
  renderer: string
  visibility: string
  status: 'building' | 'live' | 'failed' | 'unpublished'
  published_at: string | null
  unpublished_at: string | null
  current_build: PublicationBuild | null
  /** Path only. The studio joins it to the API origin, because that is the
   *  host a reader will actually be able to reach. */
  url: string
  /** The commit the newest reading covers, and whether the published build
   *  was written from it. Null on either means there is nothing to compare. */
  latest_commit: string | null
  is_current: boolean | null
}

export interface PublishAccepted {
  /** Nothing was built: what is serving is already what this would produce. */
  unchanged: boolean
  publication: Publication
  job_id: number | null
}

export interface RendererInfo {
  name: string
  version: string
  available: boolean
  reason: string
}


/* ------------------------------------------------------------------ *
 * The architecture, as analysis saw it.
 *
 * Every field is optional in practice: this comes from a column written
 * by a model, and the server coerces it before it gets here. `available`
 * is false for a project analysed before the column existed.
 * ------------------------------------------------------------------ */

export interface ArchService {
  name: string
  /** `service`, `api`, `cli`, `utility` — whatever analysis called it. */
  type: string
  description: string
  modules: string[]
}

export interface ArchRelation {
  source: string
  target: string
  /** `calls`, `configures`, `feeds`, `reads`, `uses`. Drawn on the edge. */
  kind: string
}

export interface ArchLayer {
  name: string
  modules: string[]
}

export interface Architecture {
  available: boolean
  commit_sha: string | null
  services: ArchService[]
  relations: ArchRelation[]
  layers: ArchLayer[]
  patterns: string[]
  entry_points: string[]
  tech_stack: {
    language: string
    frameworks: string[]
    databases: string[]
    infra: string[]
  }
  /** Edges naming a service that does not exist. Not drawable, so reported. */
  dangling_relations: number
}

/* --- Narratives ---------------------------------------------------- *
 * The prose analysis writes per topic. `provenance` is empty for every
 * knowledge base built before the writer started recording its sources,
 * and the reader says so rather than inventing one.
 * ------------------------------------------------------------------- */

export interface NarrativeProvenance {
  generated_by: string
  modules: string[]
  facts: string[]
}

export interface Narrative {
  topic: string
  title: string
  brief: string
  content_md: string
  words: number
  provenance: NarrativeProvenance
}

export interface Narratives {
  available: boolean
  commit_sha: string | null
  /** In reading order from the API: overview first, not alphabetical. */
  narratives: Narrative[]
}

/* --- The source, as the knowledge base kept it --------------------- *
 * Analysis discards the clone, so a file arrives as a reconstruction
 * from stored chunks rather than a string read off disk. The chunks
 * overlap in places and leave holes in others, which is why a file is a
 * list of segments and a hole is a segment of its own.
 * ------------------------------------------------------------------- */

export interface FileEntry {
  path: string
  language: string
  loc: number
  symbols: number
  lines_indexed: number
  /** False means analysis saw the file and kept nothing showable of it. */
  has_source: boolean
}

export interface FileTree {
  available: boolean
  commit_sha: string | null
  files: FileEntry[]
  without_source: number
  total_loc: number
}

export interface CodeSegment {
  kind: 'code' | 'gap'
  start: number
  end: number
  /** Empty for a gap. There is nothing to show, which is the point of it. */
  text: string
}

export interface SymbolEntry {
  name: string
  qname: string
  kind: string
  line: number
  end_line: number | null
  visibility: string
}

export interface SourceFile {
  path: string
  language: string
  loc: number
  commit_sha: string | null
  segments: CodeSegment[]
  symbols: SymbolEntry[]
  lines_indexed: number
  lines_missing: number
  chunks: number
  indexed: boolean
}

/* --- Modules -------------------------------------------------------- *
 * Each one carries the paragraph analysis wrote for it and the files it
 * is made of, so a module can be opened rather than only read about.
 * Test modules are included and flagged: their absence would be a claim
 * about the project.
 * -------------------------------------------------------------------- */

export interface ModuleEntry {
  path: string
  name: string
  kind: string
  /** One of twelve fixed words, the same in every codebase. What the apps consume. */
  role: string
  /** The component analysis named for *this* codebase, e.g. "Worker Face Tracking
   *  Engine". Empty when the architecture pass did not place this module. */
  service: string
  language: string
  file_count: number
  loc: number
  is_test: boolean
  summary: string
  files: string[]
  symbols: number
}

export interface Modules {
  available: boolean
  commit_sha: string | null
  /** Largest first. */
  modules: ModuleEntry[]
  without_summary: number
  total_loc: number
}
