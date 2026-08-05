/* ------------------------------------------------------------------ *
 * What each document type actually contains, for the picker.
 *
 * The API returns `suggested_doc_types` with a confidence and a reason;
 * this table supplies the human-facing name, the promise, and a rough
 * cost so the picker can total an estimate before you commit.
 * ------------------------------------------------------------------ */

import type { DocType, OutputFormat } from './types'

export interface DocTypeMeta {
  title: string
  blurb: string
  /** What ends up in the document, shown as a contents preview. */
  contains: string[]
  /** Rough minutes on a local model — for "≈ 12 min" on the compose button. */
  estMinutes: number
}

export const DOC_TYPES: Record<string, DocTypeMeta> = {
  architecture: {
    title: 'Architecture Guide',
    blurb:
      'How the system is put together — the components, how a request moves through them, and where the boundaries are.',
    contains: ['System overview', 'Component map', 'Request lifecycle', 'Data model', 'Diagrams'],
    estMinutes: 6,
  },
  api: {
    title: 'API Reference',
    blurb:
      'Every endpoint the service exposes, with methods, paths, parameters and responses taken from the routes found in source.',
    contains: ['Endpoint tables', 'Request/response shapes', 'Auth requirements', 'Error codes'],
    estMinutes: 8,
  },
  getting_started: {
    title: 'Getting Started',
    blurb:
      'What a new developer needs on day one — prerequisites, install, configuration and the first successful run.',
    contains: ['Prerequisites', 'Installation', 'Configuration', 'First run', 'Troubleshooting'],
    estMinutes: 4,
  },
  deployment: {
    title: 'Deployment Guide',
    blurb:
      'How the service is built, configured and shipped, based on the infrastructure and config files found in the repository.',
    contains: ['Build', 'Environment variables', 'Infrastructure', 'Runbook'],
    estMinutes: 5,
  },
  modules: {
    title: 'Module Reference',
    blurb:
      'A page per significant module — what it owns, what it depends on, and what calls it.',
    contains: ['Per-module summaries', 'Responsibilities', 'Dependencies', 'Call graph'],
    estMinutes: 9,
  },
}

/** Unknown types from a newer backend still render readably. */
export function docTypeMeta(t: DocType): DocTypeMeta {
  return (
    DOC_TYPES[t] ?? {
      title: String(t)
        .replace(/[_-]+/g, ' ')
        .replace(/\b\w/g, c => c.toUpperCase()),
      blurb: 'Generated from the knowledge base.',
      contains: [],
      estMinutes: 5,
    }
  )
}

export const docTypeTitle = (t: DocType) => docTypeMeta(t).title

/** pdf is absent on purpose — the backend does not implement it. */
export const OUTPUT_FORMATS: { value: OutputFormat; label: string; note?: string }[] = [
  { value: 'markdown', label: 'Markdown' },
  { value: 'docx', label: 'DOCX' },
  { value: 'mkdocs', label: 'MkDocs' },
  { value: 'docusaurus', label: 'Docusaurus' },
]

/** Confidence → the word we put next to the bar. */
export function confidenceLabel(c: number): string {
  if (c >= 0.85) return 'strong evidence'
  if (c >= 0.65) return 'good evidence'
  if (c >= 0.4) return 'some evidence'
  return 'thin evidence'
}
