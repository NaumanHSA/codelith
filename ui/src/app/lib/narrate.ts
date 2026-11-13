/* ------------------------------------------------------------------ *
 * Turns each agent + its output_json into a line a human wants to read.
 *
 * "Mapped 45 modules and found 77 facts" beats "structured_extractor:
 * {modules: 45, entities: 77}". The copy below is tuned — reuse the
 * table even if the component around it is rebuilt.
 *
 * Every output key is optional. A missing key means "not reported",
 * never zero, so each narrator checks for undefined before speaking.
 * ------------------------------------------------------------------ */

import { countLabel } from './format'
import type { IconName } from './icons'
import type { JobStep, JobType } from './types'

/** Expected stages in order, so queued work is visible before it starts. */
export const EXPECTED_STAGES: Record<string, string[]> = {
  analysis: [
    'repo_analyzer_agent',
    'structured_extractor_agent',
    'semantic_indexer_agent',
    'module_summarizer_agent',
    'architecture_synthesizer_agent',
    'narrative_writer_agent',
    'site_planner_agent',
    'question_seeder_agent',
    'kb_persister_agent',
  ],
  // A revision is three nodes: it neither plans nor chooses what to write, because
  // the subject is already decided and the existing prose is an input.
  // A QA run reports the checks its areas need; this is all of them, in order.
  qa: ['qa_prepare', 'qa_code', 'qa_flows', 'qa_secrets', 'qa_deploy', 'qa_environment', 'qa_dependencies', 'qa_online', 'qa_untested', 'qa_review', 'qa_sandbox', 'qa_report'],
  revision: [
    'reviser_agent',
    'linker_agent',
    'publisher_agent',
  ],
  composition: [
    'kb_loader_agent',
    'composition_strategy_agent',
    'composition_planner_agent',
    'composition_writer_agent',
    'linker_agent',
    'diagram_agent',
    'qa_agent',
    'gate',
    'formatter_agent',
    'publisher_agent',
  ],
}

/** diagram_agent and qa_agent run concurrently; gate is a no-op join. */
export const PARALLEL_STAGES = ['diagram_agent', 'qa_agent']

/**
 * Stages that exist in the graph but never record a JobStep.
 *
 * `gate` is a no-op join node in the workflow, so the backend reports
 * nothing for it. It earns a row because it is where the parallel lanes
 * rejoin, but counting it as work means a finished composition reports
 * 8/9 stages and stops at 89%.
 */
export const SYNTHETIC_STAGES = ['gate']

export function expectedStages(jobType: JobType): string[] {
  return EXPECTED_STAGES[jobType] ?? []
}

/** Expected stages that actually report progress — the progress denominator. */
export function progressStages(jobType: JobType): string[] {
  return expectedStages(jobType).filter(s => !SYNTHETIC_STAGES.includes(s))
}

/** What each stage is doing, shown while it runs and before it starts. */
const PURPOSE: Record<string, string> = {
  repo_analyzer: 'Cloning and walking every file in the repository',
  structured_extractor: 'Recording routes, entrypoints, dependencies and config',
  semantic_indexer: 'Chunking and embedding the codebase into the vector store',
  module_summarizer: 'Writing a summary for every module',
  architecture_synthesizer: 'Assembling components into an architecture',
  narrative_writer: 'Drafting narrative topics from the evidence',
  site_planner: 'Planning the documentation site: sections and pages',
  question_seeder: 'Writing the questions worth asking about this codebase',
  kb_persister: 'Committing the knowledge base',
  kb_loader: 'Loading the knowledge base for this commit',
  composition_strategy: 'Deciding what each document should cover',
  composition_planner: 'Planning sections',
  composition_writer: 'Writing the prose',
  reviser: 'Applying the change you asked for',
  linker: 'Resolving cross-page links and checking every anchor',
  diagram: 'Generating diagrams',
  qa: 'Checking every claim against source',
  gate: 'Waiting for both branches to finish',
  formatter: 'Rendering the requested output formats',
  publisher: 'Saving documents',
  qa_prepare: "Opening the reading's files and deciding what is in scope",
  qa_code: "Running each language's rules over every source file",
  qa_flows: 'Following each route through its calls: who can reach it, and where its data goes',
  qa_secrets: 'Looking for keys, tokens and passwords in every file',
  qa_deploy: 'Checking Dockerfiles, compose files and CI workflows',
  qa_environment: 'Comparing the environment the code reads with what files declare',
  qa_dependencies: 'Reading manifests, lockfiles and imports: what is declared, locked and used',
  qa_online: 'Asking OSV.dev and the package registries about the versions in use',
  qa_untested: 'Finding the routes and commands no test reaches',
  qa_review: 'The model reading the riskiest functions, each claim checked twice',
  qa_sandbox: 'Installing it in a clean container, then running its tests and tools with no network',
  qa_report: 'Saying what each finding touches, and what is new or fixed',
}

const num = (v: unknown): number | undefined =>
  typeof v === 'number' && Number.isFinite(v) ? v : undefined

const bool = (v: unknown): boolean | undefined => (typeof v === 'boolean' ? v : undefined)

const list = (v: unknown): unknown[] | undefined => (Array.isArray(v) ? v : undefined)

type Narrator = (o: Record<string, unknown>) => string | null

const NARRATORS: Record<string, Narrator> = {
  repo_analyzer: o => {
    const files = num(o.total_files)
    const sources = num(o.sources_processed)
    const parts: string[] = []
    if (files !== undefined) parts.push(`Walked ${countLabel(files, 'file')}`)
    if (sources !== undefined) parts.push(`${countLabel(sources, 'source')} processed`)
    return parts.join(' · ') || null
  },

  structured_extractor: o => {
    const m = num(o.modules)
    const e = num(o.entities)
    if (m !== undefined && e !== undefined)
      return `Mapped ${countLabel(m, 'module')} and found ${countLabel(e, 'fact')}`
    if (m !== undefined) return `Mapped ${countLabel(m, 'module')}`
    if (e !== undefined) return `Found ${countLabel(e, 'fact')}`
    return null
  },

  semantic_indexer: o => {
    const c = num(o.chunks)
    const f = num(o.embed_failures)
    if (c === undefined) return null
    return f ? `Embedded ${countLabel(c, 'chunk')} · ${f} failed` : `Embedded ${countLabel(c, 'chunk')}`
  },

  module_summarizer: o => {
    const s = num(o.summarised)
    const f = num(o.failed)
    if (s === undefined) return null
    return f ? `Summarised ${s} modules · ${f} failed` : `Summarised ${countLabel(s, 'module')}`
  },

  architecture_synthesizer: o => {
    const s = num(o.services)
    const degraded = bool(o.degraded)
    if (s === undefined) return degraded ? 'Architecture partially synthesised' : null
    return degraded
      ? `Mapped ${countLabel(s, 'component')} · partial`
      : `Mapped ${countLabel(s, 'component')}`
  },

  narrative_writer: o => {
    const w = num(o.written)
    const s = num(o.skipped)
    if (w === undefined) return null
    return s ? `Wrote ${countLabel(w, 'narrative')} · ${s} skipped` : `Wrote ${countLabel(w, 'narrative')}`
  },

  site_planner: o => {
    const pages = num(o.pages)
    const sections = num(o.sections)
    if (pages === undefined) return null
    // "3 new" is the part that matters on a re-analysis: the map is mostly the
    // same every run, and what changed is the only news.
    const added = num(o.inserted)
    const base =
      sections === undefined
        ? `Mapped ${countLabel(pages, 'page')}`
        : `Mapped ${countLabel(pages, 'page')} across ${countLabel(sections, 'section')}`
    return added ? `${base} · ${added} new` : base
  },

  question_seeder: o =>
    o.questions ? `${o.questions} questions written` : 'no questions written',
  kb_persister: o =>
    typeof o.status === 'string' ? `Knowledge base ${o.status}` : 'Knowledge base saved',

  kb_loader: o => {
    const d = list(o.doc_types)
    return d?.length ? `Loaded evidence for ${d.join(', ')}` : null
  },

  composition_planner: o => {
    const s = num(o.sections)
    return s === undefined ? null : `Planned ${countLabel(s, 'section')}`
  },

  composition_writer: o => {
    const d = num(o.doc_count)
    return d === undefined ? null : `Wrote ${countLabel(d, 'document')}`
  },

  reviser: o => {
    if (typeof o.error === 'string') return o.error
    const section = typeof o.section === 'string' ? o.section : null
    const words = num(o.words)
    if (!section) return null
    return words === undefined ? `Revised “${section}”` : `Revised “${section}” · ${words} words`
  },

  linker: o => {
    const resolved = num(o.resolved)
    const broken = num(o.broken)
    if (resolved === undefined) return null
    const base = `Resolved ${countLabel(resolved, 'link')}`
    // A broken link is the one thing here worth interrupting for: a docs
    // site with dead links reads as broken however good its prose is.
    return broken ? `${base} · ${broken} unresolved` : base
  },

  diagram: o => {
    const d = num(o.diagrams)
    const s = num(o.skipped)
    if (d === undefined) return null
    return s ? `Generated ${countLabel(d, 'diagram')} · ${s} skipped` : `Generated ${countLabel(d, 'diagram')}`
  },

  qa: o => {
    const all = bool(o.all_approved)
    if (all === undefined) return null
    return all ? 'Every claim verified against source' : 'Some claims could not be verified'
  },

  formatter: o => {
    const f = list(o.formats)
    return f?.length ? `Rendered ${f.join(', ')}` : null
  },

  publisher: o => {
    const ids = list(o.saved_doc_ids)
    return ids?.length ? `Saved ${countLabel(ids.length, 'document')}` : null
  },
}

const stem = (agent: string) => agent.replace(/_agent$/, '')

/** What the stage is for — shown before and during the run. */
export function stagePurpose(agent: string): string | null {
  return PURPOSE[stem(agent)] ?? null
}

/** What the stage actually did — shown once it has output. */
export function narrateStep(step: Pick<JobStep, 'name' | 'output_json' | 'status'>): string | null {
  const out = step.output_json
  if (!out || typeof out !== 'object') return null
  const narrator = NARRATORS[stem(step.name)]
  if (!narrator) return null
  try {
    return narrator(out as Record<string, unknown>)
  } catch {
    return null
  }
}

/** Best single line for a step in any state. */
export function describeStep(
  step: Pick<JobStep, 'name' | 'output_json' | 'status'>,
): string | null {
  return narrateStep(step) ?? stagePurpose(step.name)
}

/** The icon of each stage, by what it does. */
const STAGE_ICONS: Record<string, IconName> = {
  repo_analyzer: 'folder-git-2',
  structured_extractor: 'hash',
  semantic_indexer: 'database',
  module_summarizer: 'layers',
  architecture_synthesizer: 'boxes',
  narrative_writer: 'book-open-text',
  site_planner: 'list-tree',
  question_seeder: 'message-square',
  kb_persister: 'hard-drive',
  kb_loader: 'download',
  composition_strategy: 'lightbulb',
  composition_planner: 'list-tree',
  composition_writer: 'pencil',
  reviser: 'pencil',
  linker: 'link',
  diagram: 'workflow',
  qa: 'shield-check',
  gate: 'git-fork',
  formatter: 'file-text',
  publisher: 'upload',
  qa_prepare: 'folder-git-2',
  qa_code: 'file-code',
  qa_flows: 'route',
  qa_secrets: 'key-round',
  qa_deploy: 'container',
  qa_environment: 'settings',
  qa_dependencies: 'package',
  qa_online: 'globe',
  qa_untested: 'flask-conical',
  qa_review: 'sparkles',
  qa_sandbox: 'box',
  qa_report: 'shield-check',
}

export function stageIcon(agent: string): IconName {
  return STAGE_ICONS[stem(agent)] ?? 'circle-dot'
}
