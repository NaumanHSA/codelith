import type { IconName } from '../../lib/icons'
import type { DiffRow, QADesignedOutcome, QASeverity } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * How QA's severities and areas are drawn. Severity uses the status
 * colours and always comes with its icon and its word, never colour
 * alone.
 * ------------------------------------------------------------------ */

export const SEVERITY: Record<QASeverity, { label: string; icon: IconName; color: string; tone: 'bad' | 'warn' | 'plain' }> = {
  critical: { label: 'Critical', icon: 'octagon-alert', color: 'var(--bad)', tone: 'bad' },
  high: { label: 'High', icon: 'triangle-alert', color: 'var(--bad)', tone: 'bad' },
  medium: { label: 'Medium', icon: 'triangle-alert', color: 'var(--warn)', tone: 'warn' },
  low: { label: 'Low', icon: 'info', color: 'var(--ink-mid)', tone: 'plain' },
  info: { label: 'Info', icon: 'info', color: 'var(--ink-dim)', tone: 'plain' },
}

export const SEVERITIES: QASeverity[] = ['critical', 'high', 'medium', 'low', 'info']

export const CONFIDENCE: Record<string, { label: string; title: string }> = {
  confirmed: { label: 'Confirmed', title: 'An exact pattern, a tool, or a failing test' },
  likely: { label: 'Likely', title: 'A heuristic that is usually right, or a designed test that fails: worth a look before acting' },
  suspected: { label: 'Suspected', title: "The model's, after its quote was checked and a second call agreed" },
}

export const EXPOSURE: Record<string, string> = {
  public: 'A route anyone can call reaches it',
  authenticated: 'Only routes that need a signed-in caller reach it',
  route: 'Reached from a route',
  entry: 'Reached from a command or job',
  internal: 'No route, command or job was seen reaching it',
}

/** An area's icon, from the catalog's name, with a fallback for one this build has no icon for. */
export function areaIcon(icon: string | undefined): IconName {
  const known: IconName[] = ['shield-alert', 'key-round', 'package', 'triangle-alert', 'bug', 'gauge', 'container', 'flask-conical']
  return (known as string[]).includes(icon ?? '') ? (icon as IconName) : 'shield-check'
}

const LANGUAGE_BY_EXTENSION: Record<string, string> = {
  py: 'python',
  ts: 'typescript',
  tsx: 'typescript',
  js: 'javascript',
  jsx: 'javascript',
  mjs: 'javascript',
  go: 'go',
  java: 'java',
  yml: 'yaml',
  yaml: 'yaml',
  toml: 'toml',
  json: 'json',
  md: 'markdown',
  ini: 'ini',
  cfg: 'ini',
}

/** The highlighter's name for a file's language, from its name. */
export function languageOf(path: string | null) {
  if (!path) return ''
  const name = path.split('/').pop() ?? ''
  if (/dockerfile/i.test(name)) return 'dockerfile'
  if (name.startsWith('.env')) return 'env'
  if (/^(GNU)?makefile$/i.test(name)) return 'makefile'
  return LANGUAGE_BY_EXTENSION[name.split('.').pop()?.toLowerCase() ?? ''] ?? ''
}

export const OUTCOME: Record<QADesignedOutcome, { label: string; icon: IconName; tone: 'good' | 'bad' | 'plain'; color: string; title: string }> = {
  bug: { label: 'Found a bug', icon: 'bug', tone: 'bad', color: 'var(--bad)', title: 'It fails, and a second look judged the code at fault' },
  passed: { label: 'Passes', icon: 'circle-check', tone: 'good', color: 'var(--ok)', title: 'It passes: coverage the codebase did not have' },
  wrong: { label: 'Gave up', icon: 'ban', tone: 'plain', color: 'var(--ink-dim)', title: 'Judged a wrong test, and still wrong after two corrections' },
  'did-not-run': { label: 'Not written', icon: 'minus', tone: 'plain', color: 'var(--ink-dim)', title: 'The model wrote no test' },
}

/** Each area's name, for pages that do not load the QA catalog. Mirrors `apps/qa/areas.py`. */
export const AREA_LABEL: Record<string, string> = {
  security: 'Security',
  leakage: 'Data leakage',
  dependencies: 'Dependencies & compatibility',
  errors: 'Error handling',
  breaks: 'Things that will break',
  performance: 'Performance & concurrency',
  config: 'Configuration & deployment',
  tests: 'Tests',
}

/** A unified diff as the diff viewer's rows. */
export function patchRows(text: string): DiffRow[] {
  const rows: DiffRow[] = []
  let o = 0
  let n = 0
  let inHunk = false
  for (const line of text.split('\n')) {
    if (line.startsWith('--- ') || line.startsWith('+++ ')) continue
    const h = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(line)
    if (h) {
      o = Number(h[1])
      n = Number(h[2])
      inHunk = true
      continue
    }
    if (!inHunk) continue
    if (line.startsWith('+')) rows.push({ kind: 'add', old: null, new: n++, text: line.slice(1), marks: [] })
    else if (line.startsWith('-')) rows.push({ kind: 'del', old: o++, new: null, text: line.slice(1), marks: [] })
    else if (line.startsWith(' ')) rows.push({ kind: 'context', old: o++, new: n++, text: line.slice(1), marks: [] })
  }
  return rows
}
