import { useEffect, useState, type ReactNode } from 'react'
import { Link, NavLink, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../../auth'
import { api } from '../../lib/api'
import { BrandMark } from '../../lib/brands'
import { humanize } from '../../lib/format'
import { Icon, type IconName } from '../../lib/icons'
import type { ModelRegistry, Project, Tier } from '../../lib/types'
import { Logo } from '../ui'
import { CodebaseMark } from '../primitives'
import { ChatThreadsProvider } from '../../chat-threads'
import { ProjectsListProvider, useProjectsList } from '../../projects-list'
import ThreadRail from './ThreadRail'
import RunDock from './RunDock'
import { TabPanes, TabStrip, useTabs } from './Tabs'
import { RailAction, RailNote, RailRow } from './RailRow'

/**
 * The rail is the product's shape, so it says what the product is.
 *
 * The workspace's destinations at the top, each with its icon. Then one section
 * per app, each listing the codebases it can act on, because every app is
 * per-codebase and a bare app link in a place with nothing selected only ever
 * leads to a picker. The models the installation is using sit at the foot,
 * where a wrong one is noticed before a run rather than after.
 *
 * Per-codebase tools (the knowledge graph, changes) are not destinations here: they
 * need a codebase first, so they are reached from it.
 */
const NAV: { to: string; label: string; icon: IconName; end?: boolean; also?: RegExp }[] = [
  { to: '/app', label: 'Home', icon: 'house', end: true },
  // A codebase and everything per codebase (its knowledge graph, its changes, a run).
  { to: '/app/projects', label: 'Codebases', icon: 'folder-git-2', also: /^\/app\/projects\/\d+(\/(graph|drift|qa|history|review|jobs\/\d+))?$/ },
  { to: '/app/chat', label: 'Ask the code', icon: 'message-square' },
  // Every codebase's documentation, the documents and the published sites; it used to
  // be three destinations and a section of the rail.
  { to: '/app/documentation', label: 'Documentation', icon: 'book-open', also: /\/(docs|documents|published)(\/|$)/ },
  { to: '/app/jobs', label: 'Runs', icon: 'activity' },
]

/** How many codebases the index at the foot of the rail shows before deferring
 *  to the full list. The rail is a shortcut; Codebases is the index. */
const RAIL_CODEBASES = 5

const navClass = ({ isActive }: { isActive: boolean }) =>
  `group flex items-center gap-2.5 rounded-[7px] px-2.5 py-[7px] text-[13.5px] font-medium transition-colors ${
    isActive
      ? 'bg-sunk text-ink shadow-[inset_0_0_0_1px_var(--rule)]'
      : 'text-ink-mid hover:bg-hover hover:text-ink'
  }`

function NavIcon({ name, active }: { name: IconName; active: boolean }) {
  return (
    <Icon
      name={name}
      size={16}
      className={active ? 'text-hot' : 'text-ink-dim transition-colors group-hover:text-ink'}
    />
  )
}

/** A section heading. The rail is sections that do different jobs, and without
 *  one "New chat" reads as a sixth destination rather than as the first row of
 *  the conversations under it. */
function SectionLabel({ children, count }: { children: ReactNode; count?: number }) {
  return (
    <div className="flex items-center justify-between px-2.5 pt-5 pb-1.5">
      <span className="tag text-ink-dim">{children}</span>
      {count !== undefined && <span className="tag text-ink-dim">{count}</span>}
    </div>
  )
}

/** Whether a codebase can be used yet, as a dot: green when it has been read,
 *  the accent while it is being read, and hollow before it ever has been. */
function ReadinessDot({ project }: { project: Project }) {
  if (project.latest_job?.status === 'running')
    return (
      <span
        title="Analysing"
        className="anim-pulse block size-[7px] shrink-0 rounded-full bg-hot"
      />
    )
  return project.apps_ready ? (
    <span title="Analysed" className="block size-[7px] shrink-0 rounded-full bg-ok" />
  ) : (
    <span
      title="Not analysed yet"
      className="block size-[7px] shrink-0 rounded-full border border-ink-dim"
    />
  )
}

/** The index at the foot of the rail. Every codebase is reachable from
 *  Codebases; these are the ones most recently touched. */
function CodebaseRail() {
  const location = useLocation()
  const { projects, loading } = useProjectsList()

  if (loading) return <RailNote>Loading…</RailNote>
  if (!projects.length) return <RailNote>No codebases yet.</RailNote>

  return (
    <>
      {projects.slice(0, RAIL_CODEBASES).map(p => (
        <RailRow
          key={p.id}
          to={`/app/projects/${p.id}`}
          active={location.pathname === `/app/projects/${p.id}`}
          label={p.name}
          title={`${p.name} · ${
            p.latest_job?.status === 'running'
              ? 'analysing'
              : p.apps_ready
                ? 'analysed'
                : 'not analysed yet'
          }`}
          lead={<CodebaseMark project={p} />}
          trail={<ReadinessDot project={p} />}
        />
      ))}
      {projects.length > RAIL_CODEBASES && (
        <RailAction to="/app/projects">
          <Icon name="chevron-right" size={15} />
          View all {projects.length}
        </RailAction>
      )}
    </>
  )
}

const TIERS: { tier: Tier; label: string }[] = [
  { tier: 'quality', label: 'Quality' },
  { tier: 'fast', label: 'Fast' },
  { tier: 'embedding', label: 'Embedding' },
]

/**
 * Which model each tier is using, read from the registry the Settings page
 * edits. Admins only: the registry is an admin endpoint, and a reader who cannot
 * change the models has no use for a panel that sends them to a page they
 * cannot open.
 *
 * A tier with no registered model still resolves from `.env`, so it says that
 * rather than "none". The last connection test is shown only when it failed;
 * an endpoint that answered once is not proof it answers now, so success is
 * not drawn as a green light.
 */
function ModelPanel() {
  const { can } = useAuth()
  const admin = can('admin')
  const [registry, setRegistry] = useState<ModelRegistry | null>(null)

  useEffect(() => {
    if (!admin) return
    const ctrl = new AbortController()
    api
      .models(ctrl.signal)
      .then(setRegistry)
      .catch(() => {})
    return () => ctrl.abort()
  }, [admin])

  if (!admin || !registry) return null

  return (
    <Link
      to="/app/settings"
      title="Models · change them in Settings"
      className="mx-2 mb-2 flex flex-col gap-2 rounded-lg border border-rule px-2.5 py-2.5 transition-colors hover:border-line-2 hover:bg-hover"
    >
      <span className="tag text-ink-dim">Models</span>
      {TIERS.map(({ tier, label }) => {
        const id = registry.tiers[tier]
        const model = id === undefined ? undefined : registry.models.find(m => m.id === id)
        const failed = model?.last_test?.ok === false
        // The quality tier answers questions; one that refuses tools answers from a
        // single retrieval. Worth seeing before an answer, not after.
        const noTools = tier === 'quality' && model?.last_test?.capabilities?.tools === false
        return (
          <span key={tier} className="flex min-w-0 flex-col gap-1">
          <span className="flex min-w-0 items-center gap-2 text-[12.5px] text-ink-mid">
            {model?.provider === 'openai' ? (
              <BrandMark name="openai" size={14} decorative />
            ) : model?.provider === 'anthropic' ? (
              <BrandMark name="anthropic" size={14} decorative />
            ) : (
              <Icon name={tier === 'embedding' ? 'binary' : 'cpu'} size={14} className="text-ink-dim" />
            )}
            <span className="min-w-0 flex-1 truncate">
              <span className="text-ink">{label}</span>
              <span className="text-ink-dim"> · </span>
              {model ? model.model : <span className="text-ink-dim">from .env</span>}
            </span>
            {(failed || noTools) && (
              <span
                title={
                  failed
                    ? model?.last_test?.detail || 'The last connection test failed'
                    : 'Refuses tool calls'
                }
              >
                <Icon name="triangle-alert" size={14} className="text-warn" />
              </span>
            )}
          </span>
          {noTools && !failed && (
            <span className="pl-[22px] text-[11.5px] leading-snug text-warn">
              Refuses tool calls: the assistant cannot search past its first retrieval.
            </span>
          )}
          </span>
        )
      })}
    </Link>
  )
}

/* ------------------------------------------------------------------ *
 * Breadcrumbs, from the route. Every page used to carry its own trail
 * in its heading, or none; the header says where you are on all of
 * them, and the codebase's name is a link back to it.
 * ------------------------------------------------------------------ */

interface Crumb {
  label: string
  to?: string
  lead?: ReactNode
}

const CODEBASE_TABS: Record<string, string> = {
  docs: 'Documentation',
  compose: 'Documentation',
  atlas: 'Knowledge graph',
  code: 'Knowledge graph',
  graph: 'Knowledge graph',
  drift: 'Changes',
  qa: 'QA',
  history: 'History',
  review: 'Review',
}

function useCrumbs(): Crumb[] {
  const { pathname } = useLocation()
  const [params] = useSearchParams()
  const { projects } = useProjectsList()
  const parts = pathname.replace(/^\/app\/?/, '').split('/').filter(Boolean)
  const project = (id: string | null) => projects.find(p => p.id === Number(id))
  const codebase = (id: string, link: boolean): Crumb => {
    const p = project(id)
    return {
      label: p?.name ?? `Codebase ${id}`,
      to: link ? `/app/projects/${id}` : undefined,
      lead: p ? <CodebaseMark project={p} size={14} /> : undefined,
    }
  }

  switch (parts[0]) {
    case undefined:
      return [{ label: 'Home' }]
    case 'projects': {
      if (!parts[1]) return [{ label: 'Codebases' }]
      const trail: Crumb[] = [{ label: 'Codebases', to: '/app/projects' }]
      if (!parts[2]) return [...trail, codebase(parts[1], false)]
      trail.push(codebase(parts[1], true))
      if (parts[2] === 'jobs') return [...trail, { label: `Run #${parts[3]}` }]
      return [...trail, { label: CODEBASE_TABS[parts[2]] ?? humanize(parts[2]) }]
    }
    case 'chat': {
      const p = project(params.get('project'))
      return p
        ? [{ label: 'Ask the code', to: '/app/chat' }, codebase(String(p.id), true)]
        : [{ label: 'Ask the code' }]
    }
    case 'jobs':
      return [{ label: 'Runs' }]
    case 'published':
      return [{ label: 'Documentation', to: '/app/documentation?tab=published' }, { label: 'Publishing' }]
    case 'library':
    case 'documentation':
      return [{ label: 'Documentation' }]
    case 'documents':
      return parts[1]
        ? [{ label: 'Documentation', to: '/app/documentation?tab=documents' }, { label: `Document #${parts[1]}` }]
        : [{ label: 'Documentation' }]
    case 'settings':
      return [{ label: 'Settings' }]
    default:
      return [{ label: humanize(parts[0]) }]
  }
}

function Header({ onMenu }: { onMenu: () => void }) {
  const crumbs = useCrumbs()
  return (
    <header className="flex h-[46px] shrink-0 items-center border-b border-rule bg-paper/85 backdrop-blur-md">
      {/* Below tablet width the sidebar is a panel that slides in; this opens it. */}
      <button
        type="button"
        onClick={onMenu}
        aria-label="Open navigation"
        className="ml-3 grid size-9 shrink-0 place-items-center rounded-lg text-ink-mid transition-colors hover:bg-hover hover:text-ink md:hidden"
      >
        <Icon name="menu" size={18} />
      </button>
      <nav aria-label="Breadcrumb" className="page-frame min-w-0 px-4 md:px-6">
        <ol className="flex min-w-0 items-center gap-2 text-[14px] font-medium">
          {crumbs.map((c, i) => {
            const last = i === crumbs.length - 1
            const body = (
              <>
                {c.lead}
                <span className="truncate">{c.label}</span>
              </>
            )
            return (
              <li key={i} className="flex min-w-0 items-center gap-2">
                {i > 0 && <Icon name="chevron-right" size={14} className="text-ink-dim" />}
                {c.to && !last ? (
                  <Link
                    to={c.to}
                    className="flex min-w-0 items-center gap-1.5 text-ink-mid transition-colors hover:text-ink"
                  >
                    {body}
                  </Link>
                ) : (
                  <span
                    aria-current={last ? 'page' : undefined}
                    className={`flex min-w-0 items-center gap-1.5 ${last ? 'text-ink' : 'text-ink-mid'}`}
                  >
                    {body}
                  </span>
                )}
              </li>
            )
          })}
        </ol>
      </nav>
    </header>
  )
}

export default function Shell() {
  return (
    <ProjectsListProvider>
      <ChatThreadsProvider>
        <ShellBody />
      </ChatThreadsProvider>
    </ProjectsListProvider>
  )
}

function ShellBody() {
  const { user, signOut } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const { projects } = useProjectsList()
  const name = user?.full_name || user?.email || ''
  const [navOpen, setNavOpen] = useState(false)
  const tabs = useTabs(user?.id ?? 'anon')

  // A link followed from the slid-in panel should land on the page, not under it.
  useEffect(() => setNavOpen(false), [location.pathname, location.search])

  return (
    <div className="flex h-screen overflow-hidden bg-paper">
      {navOpen && (
        <div className="anim-fade fixed inset-0 z-40 bg-paper/70 backdrop-blur-[2px] md:hidden" onClick={() => setNavOpen(false)} aria-hidden />
      )}
      <aside
        className={`fixed inset-y-0 left-0 z-50 flex w-[260px] max-w-[85vw] shrink-0 flex-col border-r border-rule bg-paper transition-transform duration-200 md:static md:z-auto md:w-[244px] md:translate-x-0 ${
          navOpen ? 'translate-x-0 shadow-[24px_0_60px_-20px_var(--shadow)]' : '-translate-x-full'
        }`}
      >
        <button
          onClick={() => navigate('/')}
          title="Back to the landing page"
          className="mx-2 mt-3 mb-1 flex items-center gap-2.5 rounded-[7px] px-2.5 py-2 text-left transition-colors hover:bg-hover"
        >
          {/* The product's own mark. The prototype drew a placeholder bar here. */}
          <Logo size={22} />
          <span className="font-head text-[16px] font-semibold tracking-[-0.01em] text-ink">
            Codelith
          </span>
        </button>

        {/* One scroll container for the whole rail. Sections that scrolled
            independently put two scrollbars side by side in a narrow column. */}
        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
          <nav aria-label="Main" className="flex flex-col gap-0.5 pt-2">
            {NAV.map(n => {
              // Matched by hand: a codebase's atlas lives under /projects, and lighting
              // Codebases there would say the reader is somewhere they are not.
              const path = location.pathname.replace(/\/$/, '')
              const isActive = n.end
                ? path === n.to
                : n.also
                  ? path === n.to || n.also.test(path)
                  : path === n.to || path.startsWith(`${n.to}/`)
              return (
                <Link
                  key={n.to}
                  to={n.to}
                  aria-current={isActive ? 'page' : undefined}
                  className={navClass({ isActive })}
                >
                  <NavIcon name={n.icon} active={isActive} />
                  {n.label}
                </Link>
              )
            })}
          </nav>

          <SectionLabel count={projects.length || undefined}>Codebases</SectionLabel>
          <CodebaseRail />

          <SectionLabel>Conversations</SectionLabel>
          <ThreadRail />

        </div>

        <ModelPanel />

        <div className="border-t border-rule px-2 py-2">
          <NavLink to="/app/settings" className={navClass}>
            {({ isActive }) => (
              <>
                <NavIcon name="settings" active={isActive} />
                Settings
              </>
            )}
          </NavLink>

          <div className="mt-1 flex items-center gap-2.5 px-2.5 py-1.5">
            <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-sunk text-[12px] font-semibold text-ink shadow-[inset_0_0_0_1px_var(--line-2)]">
              {(name || '?').slice(0, 1).toUpperCase()}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[12.5px] text-ink">{name}</span>
              <span className="block text-[11px] text-ink-dim capitalize">{user?.role}</span>
            </span>
            <a
              href="https://github.com/NaumanHSA/codelith"
              target="_blank"
              rel="noreferrer"
              title="Source on GitHub"
              aria-label="Source on GitHub"
              className="flex size-7 items-center justify-center rounded-md text-ink-dim transition-colors hover:bg-hover hover:text-ink"
            >
              <BrandMark name="github" size={14} decorative />
            </a>
            <button
              onClick={() => {
                signOut()
                navigate('/')
              }}
              title="Sign out"
              aria-label="Sign out"
              className="flex size-7 items-center justify-center rounded-md text-ink-dim transition-colors hover:bg-bad-wash hover:text-bad"
            >
              <Icon name="log-out" size={15} />
            </button>
          </div>
        </div>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <TabStrip api={tabs} />
        <Header onMenu={() => setNavOpen(true)} />
        {/* One pane per open tab; only the active one shows. */}
        <TabPanes api={tabs} />
        <RunDock />
      </main>
    </div>
  )
}
