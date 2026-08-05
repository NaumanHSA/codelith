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
  stats: { source_count: number; job_count: number; doc_count: number } | null
  latest_job: { id: number; status: JobStatus } | null
}

export type JobStatus = Open<
  'pending' | 'running' | 'awaiting_review' | 'completed' | 'failed' | 'cancelled'
>
export type StepStatus = Open<'pending' | 'running' | 'completed' | 'failed'>
export type JobType = Open<'analysis' | 'composition'>

/** Statuses after which the job will never change again — stop polling. */
export const TERMINAL_JOB_STATUSES = ['completed', 'failed', 'cancelled', 'awaiting_review']
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
  job_type: JobType
  status: JobStatus
  config_json: Record<string, unknown> | null
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
  top_modules:
    | { path: string; name: string; role: ModuleRole; loc: number | null; summary: string | null }[]
    | null
  sample_routes: { kind: EntityKind; name: string; detail: string | null }[] | null
  key_dependencies: string[] | null
  entrypoints: string[] | null
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

export interface LLMSettings {
  base_url: string
  api_key: string
  default_model: string
  quality_model: string
  fast_model: string
  temperature: number
  max_tokens: number
  max_react_iterations: number
}
