import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../../auth'
import { useRunningJobs } from '../../running-jobs'
import { humanize } from '../../lib/format'
import { ErrorBoundary } from '../ErrorBoundary'
import { GitHubMark, Logo } from '../ui'
import { ChatThreadsProvider } from '../../chat-threads'
import { ProjectsListProvider, useProjectsList } from '../../projects-list'
import ThreadRail from './ThreadRail'
import DocsRail from './DocsRail'
import { RailAction, RailNote, RailRow } from './RailRow'

/**
 * The rail is the product's shape, so it says what the product is.
 *
 * Three destinations at the top — the workspace itself. Then one section per
 * app, each listing the codebases it can act on, because every app is
 * per-codebase and a bare app link in a place with nothing selected only ever
 * leads to a picker.
 *
 * Documents used to sit at the top as a fourth destination, from when
 * documentation was the whole point. It is one app's output, so it belongs
 * under that app rather than beside Codebases and Jobs.
 */
const NAV = [
  { to: '/app', index: '01', label: 'Home', end: true },
  { to: '/app/projects', index: '02', label: 'Codebases' },
  { to: '/app/jobs', index: '03', label: 'Jobs' },
]

/** How many codebases the index at the foot of the rail shows before deferring
 *  to the full list. The rail is a shortcut; Codebases is the index. */
const RAIL_CODEBASES = 5

/** A rule with a name on it. The rail is sections that do different jobs, and
 *  without the divide "Ask the code" reads as a fourth destination rather than
 *  as the heading of the conversations under it. */
function SectionLabel({
  children,
  count,
}: {
  children: React.ReactNode
  count?: number | string
}) {
  return (
    <div className="flex items-center gap-2 px-3 pt-6 pb-1.5">
      <span className="tag text-ink-dim">{children}</span>
      <span className="h-px flex-1 bg-rule" />
      {count !== undefined && <span className="tag text-ink-dim">{count}</span>}
    </div>
  )
}

/** The banner that makes a running job reachable from every screen. */
function RunningJobBar() {
  const { jobs } = useRunningJobs()
  const navigate = useNavigate()
  if (!jobs.length) return null

  return (
    <div className="border-b border-rule">
      {jobs.map(j => {
        const done = j.status === 'completed'
        const bad = j.status === 'failed' || j.status === 'cancelled'
        const review = j.status === 'awaiting_review'
        return (
          <button
            key={j.id}
            onClick={() => navigate(`/app/projects/${j.projectId}/jobs/${j.id}`)}
            className={`flex w-full items-center gap-2.5 px-4 py-1.5 text-left transition-colors ${
              done
                ? 'bg-ok-wash hover:bg-ok-wash/70'
                : bad
                  ? 'bg-bad-wash hover:bg-bad-wash/70'
                  : review
                    ? 'bg-warn-wash hover:bg-warn-wash/70'
                    : 'bg-hot-wash hover:bg-hot-wash/70'
            }`}
          >
            {j.status === 'running' || j.status === 'pending' ? (
              <span className="anim-spin block size-[9px] shrink-0 rounded-full border border-hot border-t-transparent" />
            ) : (
              <span
                className={`block size-[7px] shrink-0 rotate-45 ${
                  done ? 'bg-ok' : bad ? 'bg-bad' : 'bg-warn'
                }`}
              />
            )}
            <span
              className={`tag ${done ? 'text-ok' : bad ? 'text-bad' : review ? 'text-warn' : 'text-hot-ink'}`}
            >
              {humanize(j.jobType)} #{j.id}
            </span>
            <span className="truncate text-[11px] text-ink-mid">
              {j.projectName ? `${j.projectName} · ` : ''}
              {j.status.replace(/_/g, ' ')}
            </span>
            <span className="tag plate-arrow ml-auto shrink-0 text-ink-dim">view →</span>
          </button>
        )
      })}
    </div>
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
          sub={
            p.latest_job?.status === 'running'
              ? 'analysing…'
              : p.apps_ready
                ? 'ready'
                : 'not analysed'
          }
        />
      ))}
      {projects.length > RAIL_CODEBASES && (
        <RailAction to="/app/projects">View all {projects.length} →</RailAction>
      )}
    </>
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

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `relative flex items-center gap-2.5 py-[9px] pr-2 pl-4 text-[12.5px] transition-colors ${
      isActive
        ? 'bg-hot-wash font-semibold text-hot-ink'
        : 'text-ink-mid hover:bg-sunk hover:text-ink'
    }`

  return (
    <div className="flex h-screen overflow-hidden bg-paper">
      <aside className="flex w-[204px] shrink-0 flex-col border-r border-rule bg-panel">
        <button
          onClick={() => navigate('/')}
          title="Back to the landing page"
          className="flex items-center gap-2 border-b border-rule px-3 py-3 text-left transition-colors hover:bg-sunk"
        >
          <Logo size={18} />
          <span className="text-[12px] font-bold tracking-tight text-ink">
            code<span className="text-hot">·</span>lith
          </span>
        </button>

        {/* One scroll container for the whole rail. Sections that scrolled
            independently put two scrollbars side by side at 204px wide. */}
        <div className="min-h-0 flex-1 overflow-y-auto pb-2">
          <nav className="pt-1.5">
            {NAV.map(n => (
              <NavLink key={n.to} to={n.to} end={n.end} className={linkClass}>
                {({ isActive }) => (
                  <>
                    {isActive && <span className="absolute top-0 left-0 h-full w-[3px] bg-hot" />}
                    <span className="tag text-ink-dim">{n.index}</span>
                    {n.label}
                  </>
                )}
              </NavLink>
            ))}
          </nav>

          <SectionLabel>Documentation</SectionLabel>
          <DocsRail />

          <SectionLabel>Ask the code</SectionLabel>
          <ThreadRail />

          <SectionLabel count={projects.length || undefined}>Codebases</SectionLabel>
          <CodebaseRail />
        </div>

        <NavLink to="/app/settings" className={`${linkClass} border-t border-rule`}>
          {({ isActive }) => (
            <>
              {isActive && <span className="absolute top-0 left-0 h-full w-[3px] bg-hot" />}
              <span className="tag text-ink-dim">04</span>
              Settings
            </>
          )}
        </NavLink>

        <div className="flex items-center gap-2 border-t border-rule px-3 py-2">
          <span className="flex size-6 shrink-0 items-center justify-center border border-ink bg-ink text-[10px] font-bold text-paper">
            {(user?.full_name || user?.email || '?').slice(0, 1).toUpperCase()}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[11px] text-ink">
              {user?.full_name || user?.email}
            </span>
            <span className="tag block text-ink-dim">{user?.role}</span>
          </span>
        </div>

        <div className="grid grid-cols-2 gap-px border-t border-rule bg-rule">
          <a
            href="https://github.com/codelith"
            target="_blank"
            rel="noreferrer"
            className="tag flex items-center justify-center gap-1.5 bg-panel py-2 text-ink-dim transition-colors hover:bg-sunk hover:text-ink"
          >
            <GitHubMark size={11} /> src
          </a>
          <button
            onClick={() => {
              signOut()
              navigate('/')
            }}
            className="tag bg-panel py-2 text-ink-dim transition-colors hover:bg-sunk hover:text-bad"
          >
            sign out
          </button>
        </div>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <RunningJobBar />
        <div className="bp-grid min-h-0 flex-1 overflow-y-auto">
          <ErrorBoundary resetKey={location.pathname}>
            <Outlet />
          </ErrorBoundary>
        </div>
      </main>
    </div>
  )
}
