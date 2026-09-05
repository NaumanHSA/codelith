/* ------------------------------------------------------------------ *
 * Formatting helpers.
 *
 * These exist because the old UI rendered "43 Dependencys" and
 * "24 Env Vars". Route every count and every humanised enum through
 * here rather than interpolating raw strings.
 * ------------------------------------------------------------------ */

/** Words the naive "+s" rule gets wrong. */
const IRREGULAR: Record<string, string> = {
  dependency: 'dependencies',
  entity: 'entities',
  entry: 'entries',
  category: 'categories',
  directory: 'directories',
  repository: 'repositories',
  summary: 'summaries',
  query: 'queries',
  property: 'properties',
  index: 'indexes',
  schema: 'schemas',
  analysis: 'analyses',
}

export function pluralize(word: string, n: number): string {
  if (n === 1) return word
  const lower = word.toLowerCase()
  const irregular = IRREGULAR[lower]
  if (irregular) {
    // preserve the caller's capitalisation
    return word[0] === word[0].toUpperCase()
      ? irregular[0].toUpperCase() + irregular.slice(1)
      : irregular
  }
  if (/(s|x|z|ch|sh)$/i.test(word)) return `${word}es`
  if (/[^aeiou]y$/i.test(word)) return `${word.slice(0, -1)}ies`
  return `${word}s`
}

/** "1 module" · "30 modules" · "0 modules" */
export function countLabel(n: number, word: string): string {
  return `${n.toLocaleString()} ${pluralize(word, n)}`
}

/** Acronyms and terms that must not be title-cased into nonsense. */
const ACRONYMS: Record<string, string> = {
  api: 'API',
  http: 'HTTP',
  url: 'URL',
  uri: 'URI',
  id: 'ID',
  ui: 'UI',
  cli: 'CLI',
  db: 'DB',
  sql: 'SQL',
  llm: 'LLM',
  kb: 'KB',
  qa: 'QA',
  env: 'Env',
  vars: 'Vars',
  var: 'Var',
  json: 'JSON',
  yaml: 'YAML',
  sha: 'SHA',
  jwt: 'JWT',
  sse: 'SSE',
  loc: 'LOC',
  os: 'OS',
  io: 'IO',
  ci: 'CI',
  cd: 'CD',
  pdf: 'PDF',
  docx: 'DOCX',
  md: 'MD',
}

/** "env_var" → "Env Var" · "data_access" → "Data Access" · "api" → "API" */
export function humanize(raw: string): string {
  if (!raw) return ''
  return raw
    .replace(/[_-]+/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .trim()
    .split(/\s+/)
    .map(w => ACRONYMS[w.toLowerCase()] ?? w[0].toUpperCase() + w.slice(1).toLowerCase())
    .join(' ')
}

/** Agent names arrive as `module_summarizer_agent`; drop the suffix. */
export function agentLabel(name: string): string {
  return humanize(name.replace(/_agent$/, ''))
}

/** 29.4 → "29.4s" · 141 → "2m 21s" · 0.4 → "412ms" */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) return '-'
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`
  if (seconds < 60) return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)}s`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  if (m < 60) return `${m}m ${s}s`
  return `${Math.floor(m / 60)}h ${m % 60}m`
}

/**
 * Wall-clock elapsed between two ISO timestamps (or now).
 *
 * Both ends go through `parseApiDate`. With two API timestamps the offsets cancel and
 * a naive read happens to be right, but a running job compares one against `Date.now()`
 * and is wrong by the machine's offset, which is how long every unfinished job claimed
 * to have been going.
 */
export function elapsedSeconds(from: string | null, to: string | null): number | null {
  if (!from) return null
  const start = parseApiDate(from).getTime()
  const end = to ? parseApiDate(to).getTime() : Date.now()
  if (Number.isNaN(start) || Number.isNaN(end)) return null
  return Math.max(0, (end - start) / 1000)
}

/**
 * A timestamp from the API, as a real instant.
 *
 * Every datetime the API returns is UTC, but SQLite does not keep the offset, so it
 * arrives without one: `2026-09-05T17:49:59` rather than `...Z`. Javascript reads a
 * bare ISO string as *local* time, which silently shifts every timestamp in the
 * studio by the machine's offset. On a three-day-old row nobody notices; on something
 * published a second ago it reads "4h ago", which is how this was found.
 *
 * Anything already carrying a zone or an offset is left exactly as it is.
 */
export function parseApiDate(iso: string): Date {
  const zoned = /(?:Z|[+-]\d{2}:?\d{2})$/.test(iso)
  return new Date(zoned ? iso : `${iso}Z`)
}

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return '-'
  const t = parseApiDate(iso).getTime()
  if (Number.isNaN(t)) return '-'
  const secs = Math.round((Date.now() - t) / 1000)
  if (secs < 45) return 'just now'
  if (secs < 90) return 'a minute ago'
  const mins = Math.round(secs / 60)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.round(hrs / 24)
  if (days < 30) return `${days}d ago`
  return parseApiDate(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '-'
  const d = parseApiDate(iso)
  if (Number.isNaN(d.getTime())) return '-'
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export const shortSha = (sha: string | null | undefined) => (sha ? sha.slice(0, 7) : '-')

/** Language byte/file counts → percentage shares, largest first. */
export function languageShares(
  languages: Record<string, number> | null | undefined,
): { name: string; count: number; pct: number }[] {
  if (!languages) return []
  const entries = Object.entries(languages).filter(([, v]) => v > 0)
  const total = entries.reduce((sum, [, v]) => sum + v, 0)
  if (!total) return []
  return entries
    .map(([name, count]) => ({ name, count, pct: (count / total) * 100 }))
    .sort((a, b) => b.count - a.count)
}
