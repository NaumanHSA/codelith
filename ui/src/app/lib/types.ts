export type UserRole = 'admin' | 'manager' | 'reviewer' | 'user';

export interface User {
  id: number;
  email: string;
  full_name: string;
  role: UserRole;
  created_at: string;
}

export interface Organization {
  id: number;
  name: string;
  slug: string;
  logo_url?: string;
  default_output_formats: OutputFormat[];
}

export interface Source {
  id: number;
  project_id: number;
  type: 'github' | 'gitlab' | 'bitbucket' | 'local';
  source_type?: string;
  url_or_path: string;
  branch?: string;
  config_json?: { original_filename?: string; [key: string]: unknown };
  created_at: string;
}

export interface Project {
  id: number;
  name: string;
  description?: string;
  created_at: string;
  updated_at: string;
  sources?: Source[];
  stats?: {
    source_count: number;
    job_count: number;
    doc_count: number;
  };
  latest_job?: Job;
}

export type JobStatus = 'pending' | 'running' | 'awaiting_review' | 'completed' | 'failed' | 'cancelled';
export type StepStatus = 'pending' | 'running' | 'completed' | 'failed';
export type DocType = 'architecture' | 'api' | 'modules' | 'getting_started' | 'deployment' | 'contributing' | 'changelog';
export type OutputFormat = 'markdown' | 'docx' | 'mkdocs' | 'docusaurus';

export interface JobStep {
  id: number;
  name: string;
  status: StepStatus;
  started_at?: string;
  completed_at?: string;
  duration_seconds?: number;
  output_json?: Record<string, unknown>;
}

export type JobType = 'analysis' | 'composition';

export interface Job {
  id: number;
  project_id: number;
  project_name?: string;
  /** "analysis" builds the knowledge base; "composition" writes docs from one. */
  job_type: JobType;
  status: JobStatus;
  doc_types: DocType[];
  output_formats: OutputFormat[];
  requires_human_review: boolean;
  started_at?: string;
  completed_at?: string;
  duration_seconds?: number;
  steps: JobStep[];
  review_comment?: string;
}

// ── Knowledge base (Phase 1 output) ─────────────────────────────────────────

export type KBStatus = 'pending' | 'running' | 'ready' | 'degraded' | 'failed' | 'stale';

export interface KnowledgeBase {
  id: number;
  project_id: number;
  job_id?: number;
  commit_sha?: string;
  status: KBStatus;
  schema_version: number;
  stats: Record<string, unknown>;
  error_message?: string;
  created_at: string;
  completed_at?: string;
}

/** A document type worth offering, with the evidence behind it. */
export interface DocTypeSuggestion {
  doc_type: string;
  confidence: number;
  reason: string;
}

export interface KnowledgeBaseSummary {
  knowledge_base: KnowledgeBase;
  module_count: number;
  entity_count: number;
  narrative_topics: string[];
  languages: string[];
  roles: Record<string, number>;
  entity_kinds: Record<string, number>;
  suggested_doc_types: DocTypeSuggestion[];
}

export type DocStatus = 'draft' | 'published';

export interface Document {
  id: number;
  project_id: number;
  project_name?: string;
  job_id: number;
  doc_type: DocType;
  title: string;
  status: DocStatus;
  content_markdown?: string;
  word_count?: number;
  published_at?: string;
  created_at: string;
  output_formats: OutputFormat[];
}

export interface AgentLog {
  id: number;
  agent: string;
  level: 'info' | 'warn' | 'error';
  message: string;
  timestamp: string;
  extra?: Record<string, unknown>;
}

export interface LLMSettings {
  base_url: string;
  api_key: string;
  default_model: string;
  quality_model: string;
  fast_model: string;
  max_tokens: number;
  temperature: number;
  max_react_iterations: number;
}

export interface TemplateSettings {
  doc_type: DocType;
  name: string;
  system_prompt: string;
}

export interface ApiError {
  detail: string;
}
