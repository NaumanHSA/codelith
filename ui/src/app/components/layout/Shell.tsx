import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../../auth'
import { useRunningJobs } from '../../running-jobs'
import { useAsync } from '../../lib/hooks'
import { api } from '../../lib/api'
import { humanize } from '../../lib/format'
import { ErrorBoundary } from '../ErrorBoundary'
import { GitHubMark, Logo } from '../ui'
import { ChatThreadsProvider } from '../../chat-threads'
import ThreadRail from './ThreadRail'
import QualityRail from './QualityRail'

/**
 * The rail is the product's shape, so it says what the product is.
 *
 * It used to lead with Documents — one feature's output promoted to a top-level
 * destination, from when documentation was the whole point. Documents are reached
 * from the project that produced them now; what belongs at this level is the work
 * itself: the codebases, and the analysis that makes anything possible.
 */
const NAV = [
  { to: '/app', index: '01', label: 'Dashboard', end: true },
  { to: '/app/projects', index: '02', label: 'Codebases' },
  { to: '/app/documents', index: '03', label: 'Documents' },
  { to: '/app/jobs', index: '04', label: 'Jobs' },
]

/** A rule with a name on it. The rail has two halves that do different jobs, and
 *  without the divide "Ask the code" reads as a fifth destination rather than as
 *  the heading of the conversations under it. */
function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 px-3 pt-2.5 pb-1">
      <span className="tag text-ink-dim">{children}</span>
      <span className="h-px flex-1 bg-rule" />
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

export default function Shell() {
  return (
    <ChatThreadsProvider>
      <ShellBody />
    </ChatThreadsProvider>
  )
}

function ShellBody() {
  const { user, signOut } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  // A live index of projects in the rail — the fastest way between them.
  const { data: projects } = useAsync(() => api.projects(30, 0), [])

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `relative flex items-center gap-2 py-[7px] pr-2 pl-4 text-[11.5px] transition-colors ${
      isActive
        ? 'bg-hot-wash font-semibold text-hot-ink'
        : 'text-ink-mid hover:bg-sunk hover:text-ink'
    }`

  return (
    <div className="flex h-screen overflow-hidden bg-paper">
      <aside className="flex w-[188px] shrink-0 flex-col border-r border-rule bg-panel">
        <button
          onClick={() => navigate('/')}
          title="Back to the landing page"
          className="flex items-center gap-2 border-b border-rule px-3 py-2.5 text-left transition-colors hover:bg-sunk"
        >
          <Logo size={17} />
          <span className="text-[11px] font-bold tracking-tight text-ink">
            code<span className="text-hot">·</span>lith
          </span>
        </button>

        <nav className="border-b border-rule pb-1.5">
          <SectionLabel>Workspace</SectionLabel>
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

          <SectionLabel>Ask the code</SectionLabel>
          <ThreadRail />

          <SectionLabel>Quality</SectionLabel>
          <QualityRail />
        </nav>

        <div className="min-h-0 flex-1 overflow-y-auto py-2">
          <div className="flex items-center gap-2 px-3 pb-1.5">
            <span className="tag text-ink-dim">Codebases</span>
            <span className="h-px flex-1 bg-rule" />
            <span className="tag text-ink-dim">{projects?.length ?? '—'}</span>
          </div>
          {projects?.map(p => {
            const active = location.pathname.startsWith(`/app/projects/${p.id}`)
            return (
              <button
                key={p.id}
                onClick={() => navigate(`/app/projects/${p.id}`)}
                className={`group flex w-full items-center gap-2 px-3 py-[5px] text-left transition-colors ${
                  active ? 'bg-sunk' : 'hover:bg-sunk/60'
                }`}
              >
                <span
                  className={`block size-[5px] shrink-0 rotate-45 ${
                    p.latest_job?.status === 'running'
                      ? 'bg-hot'
                      : active
                        ? 'bg-ink'
                        : 'bg-rule group-hover:bg-hot'
                  }`}
                />
                <span
                  className={`min-w-0 flex-1 truncate text-[11px] ${active ? 'text-ink' : 'text-ink-mid'}`}
                >
                  {p.name}
                </span>
                {!!p.stats?.doc_count && (
                  <span className="tag shrink-0 text-ink-dim">{p.stats.doc_count}</span>
                )}
              </button>
            )
          })}
          {projects?.length === 0 && (
            <p className="px-3 py-2 text-[10.5px] leading-snug text-ink-dim">
              No projects yet.
            </p>
          )}
        </div>

        <NavLink to="/app/settings" className={linkClass}>
          {({ isActive }) => (
            <>
              {isActive && <span className="absolute top-0 left-0 h-full w-[3px] bg-hot" />}
              <span className="tag text-ink-dim">05</span>
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
