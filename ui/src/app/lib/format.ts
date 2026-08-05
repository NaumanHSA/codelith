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
  if (seconds == null || Number.isNaN(seconds)) return '—'
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`
  if (seconds < 60) return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)}s`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  if (m < 60) return `${m}m ${s}s`
  return `${Math.floor(m / 60)}h ${m % 60}m`
}

/** Wall-clock elapsed between two ISO timestamps (or now). */
export function elapsedSeconds(from: string | null, to: string | null): number | null {
  if (!from) return null
  const start = new Date(from).getTime()
  const end = to ? new Date(to).getTime() : Date.now()
  if (Number.isNaN(start) || Number.isNaN(end)) return null
  return Math.max(0, (end - start) / 1000)
}

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return '—'
  const secs = Math.round((Date.now() - t) / 1000)
  if (secs < 45) return 'just now'
  if (secs < 90) return 'a minute ago'
  const mins = Math.round(secs / 60)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.round(hrs / 24)
  if (days < 30) return `${days}d ago`
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export const shortSha = (sha: string | null | undefined) => (sha ? sha.slice(0, 7) : '—')

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
