/* ------------------------------------------------------------------ *
 * Tabs, the way a browser or n8n has them: a codebase, a conversation and
 * the lists each sit in their own tab, so following "Ask about it" from
 * the knowledge graph leaves the graph where it was.
 *
 * The router keeps one location, the address bar's. A tab is a location
 * of its own; the active tab's is the address bar's. Every navigation is
 * handed to `assign`, which decides whose it is:
 *
 *   - the same kind of place as the active tab: it moves the active tab
 *     (a codebase's overview to its graph; a list to another list)
 *   - another codebase or conversation: the tab already showing that one,
 *     or a new tab. A bare link to a codebase or to the assistant brings
 *     its tab back as it was left, instead of resetting it
 *   - a question handed to the assistant (`ask=`) always gets a new tab
 *
 * Pure: no ids from the clock or chance, so React may run it twice.
 * ------------------------------------------------------------------ */

export interface TabLoc {
  pathname: string
  search: string
  hash: string
  key: string
  state?: unknown
}

export interface Tab {
  id: string
  loc: TabLoc
  /** When it was last shown, on the state's own clock. */
  used: number
}

export interface TabsState {
  tabs: Tab[]
  active: string | null
  /** The last location `assign` has seen, by key. */
  seen: string | null
  clock: number
  /** A tab chosen in the tab bar, waiting for the navigation that shows it. */
  pending: string | null
  /** Where the address bar should go instead, after a tab was brought back. */
  redirect: TabLoc | null
}

export type TabKind =
  | { type: 'page' }
  | { type: 'codebase'; id: string }
  | { type: 'chat'; project: string | null }

export function kindOf(loc: { pathname: string; search: string }): TabKind {
  const m = /^\/app\/projects\/(\d+)(\/|$)/.exec(loc.pathname)
  if (m) return { type: 'codebase', id: m[1] }
  if (/^\/app\/chat\/?$/.test(loc.pathname)) return { type: 'chat', project: new URLSearchParams(loc.search).get('project') }
  return { type: 'page' }
}

function same(a: TabKind, b: TabKind): boolean {
  if (a.type === 'page' && b.type === 'page') return true
  if (a.type === 'codebase' && b.type === 'codebase') return a.id === b.id
  if (a.type === 'chat' && b.type === 'chat') return a.project === b.project
  return false
}

/** Whether a navigation from a tab of one kind to a place of another stays in it.
 *  The assistant's own "choose a codebase" and "change codebase" move it in place. */
function fits(from: TabKind, to: TabKind): boolean {
  if (same(from, to)) return true
  return from.type === 'chat' && to.type === 'chat' && (from.project === null || to.project === null)
}

const params = (loc: TabLoc) => new URLSearchParams(loc.search)

/**
 * Pass as a link's `state` to open the place in a tab of its own, even within the same
 * codebase. For a link that would otherwise replace a page whose progress lives only on
 * it — a finding being read, a diff, a live run — so the reader can come back to it.
 */
export const NEW_TAB = { newTab: true } as const

function wantsNew(loc: TabLoc): boolean {
  const s = loc.state
  return typeof s === 'object' && s !== null && (s as { newTab?: unknown }).newTab === true
}

/** The location without the new-tab request, so going back to the tab does not ask again. */
function settled(loc: TabLoc): TabLoc {
  if (!wantsNew(loc)) return loc
  const { newTab: _drop, ...rest } = loc.state as Record<string, unknown>
  return { ...loc, state: Object.keys(rest).length ? rest : undefined }
}

function opensNew(loc: TabLoc, kind: TabKind): boolean {
  return kind.type === 'chat' && params(loc).has('ask')
}

/** A plain link to a codebase or to the assistant: bring its tab back as it was. */
function isEntry(loc: TabLoc, kind: TabKind): boolean {
  if (kind.type === 'codebase') return /^\/app\/projects\/\d+\/?$/.test(loc.pathname) && !loc.search
  if (kind.type === 'chat') return !params(loc).has('thread') && !params(loc).has('ask')
  return false
}

export function emptyTabs(): TabsState {
  return { tabs: [], active: null, seen: null, clock: 0, pending: null, redirect: null }
}

export function assign(s: TabsState, loc: TabLoc): TabsState {
  const clock = s.clock + 1
  const base = { ...s, clock, seen: loc.key, pending: null, redirect: null }
  const put = (id: string, to?: TabLoc) =>
    s.tabs.map(t => (t.id === id ? { ...t, loc: to ?? t.loc, used: clock } : t))

  if (s.pending && s.tabs.some(t => t.id === s.pending)) return { ...base, active: s.pending, tabs: put(s.pending, loc) }

  const kind = kindOf(loc)
  const fresh = wantsNew(loc)
  const act = s.tabs.find(t => t.id === s.active)
  if (!fresh && act && fits(kindOf(act.loc), kind)) return { ...base, tabs: put(act.id, loc) }

  if (!fresh && !opensNew(loc, kind)) {
    const recent = (pick: (k: TabKind) => boolean) =>
      s.tabs.filter(t => pick(kindOf(t.loc))).sort((a, b) => b.used - a.used)[0]
    const match =
      recent(k => same(k, kind)) ??
      // "Ask the code" with no codebase: whichever conversation was open last.
      (kind.type === 'chat' && kind.project === null ? recent(k => k.type === 'chat') : undefined)
    if (match) {
      if (isEntry(loc, kind)) return { ...base, active: match.id, tabs: put(match.id), redirect: match.loc }
      return { ...base, active: match.id, tabs: put(match.id, loc) }
    }
  }

  const tab: Tab = { id: `t${clock}`, loc: settled(loc), used: clock }
  const at = s.tabs.findIndex(t => t.id === s.active)
  const tabs = [...s.tabs]
  tabs.splice(at < 0 ? tabs.length : at + 1, 0, tab)
  return { ...base, active: tab.id, tabs }
}

/** Close a tab. Returns where the address bar should go when the active one closed. */
export function closeTab(s: TabsState, id: string): { state: TabsState; go: TabLoc | null } {
  const i = s.tabs.findIndex(t => t.id === id)
  if (i < 0) return { state: s, go: null }
  const tabs = s.tabs.filter(t => t.id !== id)
  if (id !== s.active) return { state: { ...s, tabs }, go: null }
  const next = tabs[Math.min(i, tabs.length - 1)]
  if (!next) return { state: { ...s, tabs, active: null }, go: { pathname: '/app', search: '', hash: '', key: 'home' } }
  return { state: { ...s, tabs, active: next.id, pending: next.id }, go: next.loc }
}

/* ── kept between visits, per person, in this browser ───────────────── */

const storeKey = (user: string | number) => `codelith.tabs.v1:${user}`

export function loadTabs(user: string | number): TabsState {
  try {
    const raw = localStorage.getItem(storeKey(user))
    if (!raw) return emptyTabs()
    const saved = JSON.parse(raw) as { tabs: { id: string; pathname: string; search: string; hash: string; used: number }[]; active: string | null; clock: number }
    const tabs: Tab[] = saved.tabs
      .filter(t => typeof t.pathname === 'string' && t.pathname.startsWith('/app'))
      .map(t => ({ id: t.id, used: t.used, loc: { pathname: t.pathname, search: t.search ?? '', hash: t.hash ?? '', key: `saved-${t.id}` } }))
    return { ...emptyTabs(), tabs, active: tabs.some(t => t.id === saved.active) ? saved.active : (tabs[0]?.id ?? null), clock: saved.clock ?? 0 }
  } catch {
    return emptyTabs()
  }
}

export function saveTabs(user: string | number, s: TabsState) {
  try {
    localStorage.setItem(
      storeKey(user),
      JSON.stringify({
        active: s.active,
        clock: s.clock,
        tabs: s.tabs.map(t => ({ id: t.id, used: t.used, pathname: t.loc.pathname, search: t.loc.search, hash: t.loc.hash })),
      }),
    )
  } catch {
    /* storage blocked: the tabs last as long as the page */
  }
}
