import {
  Activity,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import {
  UNSAFE_NavigationContext as NavigationContext,
  parsePath,
  useLocation,
  useNavigate,
  type Location,
  type To,
} from 'react-router-dom'
import { Icon, type IconName } from '../../lib/icons'
import { APP_LOOKS } from '../../lib/kinds'
import type { Project } from '../../lib/types'
import { useProjectsList } from '../../projects-list'
import { CodebaseMark } from '../primitives'
import { ErrorBoundary } from '../ErrorBoundary'
import { AppRoutes } from '../../routes'
import { assign, closeTab, kindOf, loadTabs, saveTabs, type Tab, type TabLoc, type TabsState } from './tabState'

/* ------------------------------------------------------------------ *
 * The tab strip and the tabs' pages. `tabState.ts` decides which tab a
 * navigation belongs to; this keeps the state, draws the strip, and
 * renders every tab's page, the hidden ones inside <Activity>: their
 * state stays (a graph's selection, a conversation's draft) while their
 * effects stop, so a hidden map does not draw and a hidden run does not
 * poll.
 * ------------------------------------------------------------------ */

const toLoc = (l: Location): TabLoc => ({ pathname: l.pathname, search: l.search, hash: l.hash, key: l.key, state: l.state })
const toPath = (l: TabLoc) => ({ pathname: l.pathname, search: l.search, hash: l.hash })

export interface TabsApi {
  state: TabsState
  select: (id: string) => void
  close: (id: string) => void
  open: () => void
  /** Move a hidden tab without touching the address bar. */
  move: (id: string, loc: TabLoc) => void
}

export function useTabs(user: string | number): TabsApi {
  const location = useLocation()
  const navigate = useNavigate()
  const [stored, setStored] = useState<TabsState>(() => loadTabs(user))

  // Every navigation goes to a tab before anything is drawn: deciding afterwards
  // would draw the old tab at the new address for a frame, and lose its page.
  let state = stored
  if (stored.seen !== location.key) {
    state = assign(stored, toLoc(location))
    setStored(state)
  }

  const ref = useRef(state)
  useLayoutEffect(() => {
    ref.current = state
  })

  useEffect(() => {
    if (state.redirect) navigate(toPath(state.redirect), { replace: true, state: state.redirect.state })
  }, [state.redirect, navigate])

  useEffect(() => saveTabs(user, state), [user, state])

  const select = useCallback(
    (id: string) => {
      const t = ref.current.tabs.find(x => x.id === id)
      if (!t || id === ref.current.active) return
      setStored(s => ({ ...s, active: id, pending: id }))
      navigate(toPath(t.loc), { state: t.loc.state })
    },
    [navigate],
  )

  const close = useCallback(
    (id: string) => {
      const { state: next, go } = closeTab(ref.current, id)
      setStored(next)
      if (go) navigate(toPath(go), { state: go.state })
    },
    [navigate],
  )

  const open = useCallback(() => {
    const s = ref.current
    const id = `t${s.clock + 1}`
    const home: TabLoc = { pathname: '/app', search: '', hash: '', key: `new-${id}` }
    const at = s.tabs.findIndex(t => t.id === s.active)
    const tabs = [...s.tabs]
    tabs.splice(at < 0 ? tabs.length : at + 1, 0, { id, loc: home, used: s.clock + 1 })
    setStored({ ...s, clock: s.clock + 1, tabs, active: id, pending: id })
    navigate('/app')
  }, [navigate])

  const move = useCallback(
    (id: string, loc: TabLoc) =>
      setStored(s => ({ ...s, tabs: s.tabs.map(t => (t.id === id ? { ...t, loc } : t)) })),
    [],
  )

  return { state, select, close, open, move }
}

/* ── what a tab is called ───────────────────────────────────────────── */

const CODEBASE_PAGES: Record<string, string> = {
  graph: 'Knowledge graph',
  atlas: 'Knowledge graph',
  code: 'Knowledge graph',
  docs: 'Documentation',
  compose: 'Documentation',
  drift: 'Changes',
  qa: 'QA',
  history: 'History',
  review: 'Review',
}

const PAGES: Record<string, { title: string; icon: IconName }> = {
  '': { title: 'Home', icon: 'house' },
  projects: { title: 'Codebases', icon: 'folder-git-2' },
  documentation: { title: 'Documentation', icon: 'book-open' },
  library: { title: 'Documentation', icon: 'book-open' },
  documents: { title: 'Documentation', icon: 'book-open' },
  published: { title: 'Publishing', icon: 'book-open' },
  jobs: { title: 'Runs', icon: 'activity' },
  settings: { title: 'Settings', icon: 'settings' },
}

function describe(loc: TabLoc, projects: Project[]): { title: string; sub?: string; icon?: IconName; color?: string; project?: Project } {
  const kind = kindOf(loc)
  if (kind.type === 'codebase') {
    const project = projects.find(p => p.id === Number(kind.id))
    const rest = loc.pathname.split('/').slice(4)
    const sub = !rest[0] ? 'Overview' : rest[0] === 'jobs' ? `Run #${rest[1]}` : (CODEBASE_PAGES[rest[0]] ?? rest[0])
    return { title: project?.name ?? `Codebase ${kind.id}`, sub, project }
  }
  if (kind.type === 'chat') {
    const project = projects.find(p => p.id === Number(kind.project))
    return { title: project ? project.name : 'Ask the code', sub: project ? 'Ask' : undefined, icon: APP_LOOKS.assistant.icon, color: APP_LOOKS.assistant.color }
  }
  const page = PAGES[loc.pathname.split('/')[2] ?? ''] ?? { title: 'Codelith', icon: 'house' }
  return { title: page.title, icon: page.icon }
}

/* ── the strip ──────────────────────────────────────────────────────── */

export function TabStrip({ api }: { api: TabsApi }) {
  const { projects } = useProjectsList()
  const { tabs, active } = api.state
  const strip = useRef<HTMLDivElement>(null)

  // Keep the active tab in view when there are more than fit.
  useEffect(() => {
    strip.current?.querySelector<HTMLElement>('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [active])

  return (
    <div className="flex h-[40px] shrink-0 items-end gap-1 border-b border-rule bg-panel/50 px-2">
      <div ref={strip} role="tablist" aria-label="Open tabs" className="tab-strip flex min-w-0 items-end gap-0.5 overflow-x-auto">
        {tabs.map(t => {
          const on = t.id === active
          const d = describe(t.loc, projects)
          return (
            <div
              key={t.id}
              role="tab"
              tabIndex={0}
              aria-selected={on}
              title={d.sub ? `${d.title} · ${d.sub}` : d.title}
              onClick={() => api.select(t.id)}
              onAuxClick={e => {
                if (e.button === 1) {
                  e.preventDefault()
                  api.close(t.id)
                }
              }}
              onKeyDown={e => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  api.select(t.id)
                }
              }}
              className={`group relative -mb-px flex h-[33px] max-w-[240px] min-w-[132px] shrink-0 cursor-pointer items-center gap-2 rounded-t-lg border border-b-0 pr-1.5 pl-3 text-[12.5px] transition-colors select-none ${
                on
                  ? 'border-rule bg-paper text-ink'
                  : 'border-transparent text-ink-mid hover:bg-hover hover:text-ink'
              }`}
            >
              {on && <span className="absolute inset-x-3 top-0 h-[2px] rounded-b bg-hot" aria-hidden />}
              {d.project ? (
                <CodebaseMark project={d.project} size={14} />
              ) : d.icon ? (
                <Icon name={d.icon} size={14} style={d.color ? { color: d.color } : undefined} className={d.color ? '' : 'text-ink-dim'} />
              ) : null}
              <span className="min-w-0 flex-1 truncate">
                <span className="font-medium">{d.title}</span>
                {d.sub && <span className="text-ink-dim"> · {d.sub}</span>}
              </span>
              <button
                type="button"
                onClick={e => {
                  e.stopPropagation()
                  api.close(t.id)
                }}
                aria-label={`Close ${d.title}${d.sub ? ` · ${d.sub}` : ''}`}
                title="Close tab"
                className={`grid size-5 shrink-0 place-items-center rounded text-ink-dim transition-opacity hover:bg-hover hover:text-ink ${
                  on ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 focus-visible:opacity-100'
                }`}
              >
                <Icon name="x" size={13} />
              </button>
            </div>
          )
        })}
      </div>
      <button
        type="button"
        onClick={api.open}
        aria-label="New tab"
        title="New tab"
        className="mb-[5px] grid size-7 shrink-0 place-items-center rounded-md text-ink-dim transition-colors hover:bg-hover hover:text-ink"
      >
        <Icon name="plus" size={15} />
      </button>
    </div>
  )
}

/* ── the pages ──────────────────────────────────────────────────────── */

/**
 * A tab's own navigator. The showing tab navigates as any page does. A hidden one
 * (an answer still streaming, a run finishing) moves only itself: through the shared
 * router it would take the address bar, and with it the reader, back to that tab.
 */
function TabNavigation({ tab, activeRef, move, children }: {
  tab: Tab
  activeRef: { current: string | null }
  move: (id: string, loc: TabLoc) => void
  children: ReactNode
}) {
  const ctx = useContext(NavigationContext)
  const id = tab.id
  const pathname = tab.loc.pathname
  const value = useMemo(() => {
    const nav = ctx.navigator
    const hidden = () => activeRef.current !== id
    const resolve = (to: To, state: unknown): TabLoc => {
      const p = typeof to === 'string' ? parsePath(to) : to
      return {
        pathname: p.pathname ?? pathname,
        search: p.search ?? '',
        hash: p.hash ?? '',
        key: `${id}-${Math.random().toString(36).slice(2, 8)}`,
        state,
      }
    }
    return {
      ...ctx,
      navigator: {
        createHref: (to: To) => nav.createHref(to),
        encodeLocation: nav.encodeLocation ? (to: To) => nav.encodeLocation!(to) : undefined,
        go: (delta: number) => {
          if (!hidden()) nav.go(delta)
        },
        push: (to: To, state?: unknown, opts?: Parameters<typeof nav.push>[2]) =>
          hidden() ? move(id, resolve(to, state)) : nav.push(to, state, opts),
        replace: (to: To, state?: unknown, opts?: Parameters<typeof nav.replace>[2]) =>
          hidden() ? move(id, resolve(to, state)) : nav.replace(to, state, opts),
      },
    }
  }, [ctx, id, pathname, activeRef, move])
  return <NavigationContext.Provider value={value}>{children}</NavigationContext.Provider>
}

/** One tab's page in its own scroll pane, which remembers where it was scrolled. */
function TabPane({ tab }: { tab: Tab }) {
  const pane = useRef<HTMLDivElement>(null)
  const top = useRef(0)
  // Runs again each time the tab is shown: <Activity> remounts effects on show.
  useLayoutEffect(() => {
    if (pane.current && top.current) pane.current.scrollTop = top.current
  }, [])
  return (
    <div
      ref={pane}
      data-tab-pane={tab.id}
      onScroll={e => {
        top.current = e.currentTarget.scrollTop
      }}
      className="min-h-0 flex-1 overflow-y-auto"
    >
      {/* Pages sit in a centred frame of a normal website's width, and the frame is
          the full height of the window, so a tool page (assistant, graph, live run)
          can fill it. Width is capped; height is not. */}
      <div className="page-frame h-full">
        <ErrorBoundary resetKey={tab.loc.pathname}>
          <AppRoutes location={tab.loc} />
        </ErrorBoundary>
      </div>
    </div>
  )
}

export function TabPanes({ api }: { api: TabsApi }) {
  const activeRef = useRef(api.state.active)
  activeRef.current = api.state.active
  return (
    <>
      {api.state.tabs.map(t => (
        <Activity key={t.id} mode={t.id === api.state.active ? 'visible' : 'hidden'}>
          <TabNavigation tab={t} activeRef={activeRef} move={api.move}>
            <TabPane tab={t} />
          </TabNavigation>
        </Activity>
      ))}
    </>
  )
}
