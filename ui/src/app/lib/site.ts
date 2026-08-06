/* ------------------------------------------------------------------ *
 * Reading a documentation site.
 *
 * The API returns the map grouped by section. Everything the reader
 * needs beyond that — a flat reading order, prev/next, coverage totals,
 * search — is derived here rather than in components, because all four
 * have to agree on one thing: **planned pages are part of the site.**
 *
 * A planned page is in the nav, in the reading order, and counted in
 * coverage. Hiding what does not exist yet is what turns a documentation
 * site back into a folder of documents.
 * ------------------------------------------------------------------ */

import { humanize } from './format'
import type { Job, PageStatus, Site, SitePage, SiteSection } from './types'

/** A page plus where it sits, so a component never needs the section again. */
export interface FlatPage {
  page: SitePage
  section: SiteSection
  /** `section-slug/page-slug` — the address the API and the router agree on. */
  address: string
}

export const addressOf = (page: SitePage) => `${page.section_slug}/${page.slug}`

/** Every page in reading order: sections in nav order, pages in theirs. */
export function readingOrder(site: Site | null): FlatPage[] {
  if (!site) return []
  return site.sections.flatMap(section =>
    section.pages.map(page => ({ page, section, address: addressOf(page) })),
  )
}

export function findPage(
  site: Site | null,
  sectionSlug?: string,
  pageSlug?: string,
): FlatPage | null {
  const order = readingOrder(site)
  if (!order.length) return null
  if (!sectionSlug) return order[0]
  if (!pageSlug) return order.find(f => f.section.slug === sectionSlug) ?? null
  return order.find(f => f.section.slug === sectionSlug && f.page.slug === pageSlug) ?? null
}

/**
 * The pages either side, in reading order across section boundaries.
 *
 * Crossing boundaries is deliberate: the end of API Reference should lead to
 * the start of Architecture, the way a book does, not to a dead end.
 */
export function neighbours(
  site: Site | null,
  current: FlatPage | null,
): { prev: FlatPage | null; next: FlatPage | null } {
  const order = readingOrder(site)
  const i = current ? order.findIndex(f => f.address === current.address) : -1
  if (i < 0) return { prev: null, next: null }
  return { prev: order[i - 1] ?? null, next: order[i + 1] ?? null }
}

/** Whether a reader can open this page and find prose. */
export const isReadable = (status: PageStatus) =>
  status === 'ready' || status === 'stale' || status === 'orphaned'

/** Whether this page is waiting to be written. */
export const isPending = (status: PageStatus) =>
  status === 'planned' || status === 'failed'

export interface Coverage {
  total: number
  ready: number
  planned: number
  stale: number
  generating: number
  failed: number
  orphaned: number
  /** Percentage of live (non-orphaned) pages that have been written. */
  pct: number
}

/**
 * The whole map at a glance.
 *
 * Orphans are counted but excluded from the percentage: they are pages the
 * site no longer proposes, so counting them as "not yet written" would make
 * coverage fall every time analysis tidied the map.
 */
export function coverage(site: Site | null): Coverage {
  const counts = site?.page_counts ?? {}
  const n = (k: string) => counts[k] ?? 0
  const orphaned = n('orphaned')
  const total = Object.values(counts).reduce((a, b) => a + b, 0)
  const live = total - orphaned
  const written = n('ready') + n('stale')
  return {
    total,
    ready: n('ready'),
    planned: n('planned'),
    stale: n('stale'),
    generating: n('generating'),
    failed: n('failed'),
    orphaned,
    pct: live > 0 ? Math.round((written / live) * 100) : 0,
  }
}

/**
 * Client-side search over titles, intents and headings.
 *
 * Titles and intents come from the map, so a *planned* page is findable
 * before it exists — which is most of the value: searching for "webhooks"
 * and being offered the button that writes that page beats finding nothing.
 * Full-text over written prose is a later, server-side job.
 */
export function searchPages(site: Site | null, query: string, limit = 12): FlatPage[] {
  const q = query.trim().toLowerCase()
  if (q.length < 2) return []
  const scored: { flat: FlatPage; score: number }[] = []
  for (const flat of readingOrder(site)) {
    const title = flat.page.title.toLowerCase()
    const intent = (flat.page.intent ?? '').toLowerCase()
    const section = flat.section.title.toLowerCase()
    let score = 0
    if (title.startsWith(q)) score = 100
    else if (title.includes(q)) score = 70
    else if (section.includes(q)) score = 40
    else if (intent.includes(q)) score = 20
    if (score) scored.push({ flat, score })
  }
  return scored
    .sort((a, b) => b.score - a.score)
    .slice(0, limit)
    .map(s => s.flat)
}

/**
 * What a job did, in one line.
 *
 * "Job 12 · wrote API Reference (3 pages)" instead of "composition completed".
 * Falls back to the doc types for jobs created before scopes existed, and to null
 * when there is nothing better to say than the status already says.
 */
export function describeJobScope(job: Job): string | null {
  const scope = job.scope
  if (scope?.kind === 'pages') {
    const labels = scope.labels?.length ? scope.labels.join(', ') : 'the site'
    const n = scope.pages?.length ?? 0
    return `${labels} · ${n} page${n === 1 ? '' : 's'}`
  }
  const types = scope?.labels?.length ? scope.labels : (job.doc_types ?? [])
  return types.length ? types.map(humanize).join(', ') : null
}

/* ------------------------------------------------------------------ *
 * Regeneration as a diff.
 *
 * A rewritten page arriving as a fresh blob asks the reader to spot
 * what changed by reading the whole thing again, which nobody does.
 * Showing the change turns it into a review.
 *
 * Line-level LCS, computed here rather than pulled in as a dependency:
 * the inputs are two versions of one page, so the quadratic table is
 * a few hundred rows and the whole thing is forty lines.
 * ------------------------------------------------------------------ */

export type DiffOp = 'same' | 'add' | 'remove'

export interface DiffLine {
  op: DiffOp
  text: string
}

export function diffLines(before: string, after: string): DiffLine[] {
  const a = before.split('\n')
  const b = after.split('\n')

  // lcs[i][j] = length of the longest common subsequence of a[i:] and b[j:].
  const lcs: number[][] = Array.from({ length: a.length + 1 }, () =>
    new Array(b.length + 1).fill(0),
  )
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1])
    }
  }

  const out: DiffLine[] = []
  let i = 0
  let j = 0
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      out.push({ op: 'same', text: a[i] })
      i++
      j++
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      out.push({ op: 'remove', text: a[i++] })
    } else {
      out.push({ op: 'add', text: b[j++] })
    }
  }
  while (i < a.length) out.push({ op: 'remove', text: a[i++] })
  while (j < b.length) out.push({ op: 'add', text: b[j++] })
  return out
}

/**
 * The diff, with long runs of unchanged lines collapsed.
 *
 * `context` lines survive either side of a change; everything else becomes a
 * single `null` marker the caller renders as a gap. A regenerated page is mostly
 * unchanged, and scrolling past four hundred identical lines to find the edit is
 * the thing this feature exists to prevent.
 */
export function collapseDiff(lines: DiffLine[], context = 3): (DiffLine | null)[] {
  const keep = new Array(lines.length).fill(false)
  lines.forEach((line, i) => {
    if (line.op === 'same') return
    for (let k = Math.max(0, i - context); k <= Math.min(lines.length - 1, i + context); k++) {
      keep[k] = true
    }
  })

  const out: (DiffLine | null)[] = []
  let gap = false
  lines.forEach((line, i) => {
    if (keep[i]) {
      out.push(line)
      gap = false
    } else if (!gap) {
      out.push(null)
      gap = true
    }
  })
  return out
}

export const diffStat = (lines: DiffLine[]) => ({
  added: lines.filter(l => l.op === 'add').length,
  removed: lines.filter(l => l.op === 'remove').length,
})

/** Headings of one page, for the right-hand table of contents. */
export interface Heading {
  depth: number
  text: string
  id: string
}

/**
 * The id stamped onto a rendered heading.
 *
 * Must agree exactly with `anchor_id` in `app/knowledge/sites.py`: the linker
 * validates `[text](#anchor)` links against the ids it expects us to produce, so a
 * divergence turns every accented heading link into a dead one. Accents are folded
 * (NFKD, then combining marks dropped) rather than replaced with hyphens, which is
 * what a bare `[^a-z0-9]` pass would do.
 */
export const anchorId = (s: string) =>
  s
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')

export function headingsOf(markdown: string | null | undefined): Heading[] {
  if (!markdown) return []
  const out: Heading[] = []
  let inFence = false
  for (const line of markdown.split('\n')) {
    if (line.trim().startsWith('```')) inFence = !inFence
    if (inFence) continue
    const m = /^(#{1,3})\s+(.*)$/.exec(line)
    if (m) {
      const text = m[2].trim()
      out.push({ depth: m[1].length, text, id: anchorId(text) })
    }
  }
  return out
}
