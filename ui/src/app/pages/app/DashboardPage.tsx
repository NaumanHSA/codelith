import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useAsync } from '../../lib/hooks'
import { api } from '../../lib/api'
import { countLabel, formatDateTime, relativeTime } from '../../lib/format'
import { StatusBadge, Eyebrow, Panel } from '../../components/ui'
import { EmptyState, ErrorState, SkeletonPanel } from '../../components/States'
import type { Doc, Job, Project } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * Dashboard — cross-project summary: recent jobs, docs, project stats.
 * Three independent fetches so a single error doesn't blank the page.
 * ------------------------------------------------------------------ */

function StatBar({
  label, value, sub,
}: {
  label: string
  value: string | number
  sub?: string
}) {
  return (
    <div className="border-b border-rule px-4 py-3.5 last:border-b-0">
      <div className="text-[22px] font-bold tracking-tighter text-ink leading-none">
        {value}
      </div>
      <div className="mt-1 tag text-ink-dim">{label}</div>
      {sub && <div className="mt-0.5 text-[10px] text-ink-dim font-sans">{sub}</div>}
    </div>
  )
}

function JobRow({ job, projects }: { job: Job; projects: Project[] }) {
  const project = projects.find(p => p.id === job.project_id)
  const duration =
    job.started_at && job.completed_at
      ? Math.round((new Date(job.completed_at).getTime() - new Date(job.started_at).getTime()) / 1000)
      : null

  return (
    <Link
      to={`/app/projects/${job.project_id}/jobs/${job.id}`}
      className="group flex items-center gap-3 border-b border-rule px-3 py-2.5 last:border-b-0 transition-colors hover:bg-hot-wash"
    >
      <StatusBadge status={job.status} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[12px] font-semibold text-ink truncate">
            {project?.name ?? `Project ${job.project_id}`}
          </span>
          <span className="tag text-ink-dim shrink-0">{job.job_type}</span>
        </div>
        <div className="tag text-ink-dim mt-0.5">
          {relativeTime(job.created_at)}
          {duration != null && ` · ${duration < 60 ? `${duration}s` : `${Math.round(duration / 60)}m`}`}
        </div>
      </div>
      <span className="tag text-ink-dim group-hover:text-hot-ink transition-colors plate-arrow shrink-0">→</span>
    </Link>
  )
}

function DocRow({ doc }: { doc: Doc }) {
  return (
    <Link
      to={`/app/documents/${doc.id}`}
      className="group flex items-center gap-3 border-b border-rule px-3 py-2.5 last:border-b-0 transition-colors hover:bg-hot-wash"
    >
      <span className="block size-[7px] rotate-45 bg-hot shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="text-[12px] font-semibold text-ink truncate">{doc.title}</div>
        <div className="tag text-ink-dim mt-0.5">{doc.doc_type.replace(/_/g, ' ')} · {relativeTime(doc.created_at)}</div>
      </div>
      <StatusBadge status={doc.status} />
    </Link>
  )
}

/** Animated activity sparkline — recent job activity by day (7 days). */
function ActivitySpark({ jobs }: { jobs: Job[] }) {
  const bars = useMemo(() => {
    const buckets: { ok: number; fail: number; run: number }[] = Array.from({ length: 14 }, () => ({
      ok: 0,
      fail: 0,
      run: 0,
    }))
    const now = Date.now()
    for (const j of jobs) {
      const age = (now - new Date(j.created_at).getTime()) / (1000 * 60 * 60 * 24)
      const idx = Math.floor(age)
      if (idx >= 0 && idx < 14) {
        if (j.status === 'completed') buckets[idx].ok++
        else if (j.status === 'failed') buckets[idx].fail++
        else buckets[idx].run++
      }
    }
    return buckets.reverse()
  }, [jobs])

  const max = Math.max(...bars.map(b => b.ok + b.fail + b.run), 1)

  return (
    <div className="flex items-end gap-[3px] h-[36px] px-3 pb-2.5 pt-2">
      {bars.map((b, i) => {
        const total = b.ok + b.fail + b.run
        const pct = total / max
        return (
          <div
            key={i}
            title={`${total} job${total !== 1 ? 's' : ''}`}
            className="flex-1 flex flex-col-reverse overflow-hidden"
            style={{ height: `${Math.max(pct * 100, total > 0 ? 8 : 2)}%` }}
          >
            {b.run > 0 && (
              <span
                className="block w-full bg-hot"
                style={{ height: `${(b.run / Math.max(total, 1)) * 100}%` }}
              />
            )}
            {b.fail > 0 && (
              <span
                className="block w-full bg-bad"
                style={{ height: `${(b.fail / Math.max(total, 1)) * 100}%` }}
              />
            )}
            {b.ok > 0 && (
              <span
                className="block w-full bg-ok"
                style={{ height: `${(b.ok / Math.max(total, 1)) * 100}%` }}
              />
            )}
            {total === 0 && <span className="block w-full bg-rule" style={{ height: '2px' }} />}
          </div>
        )
      })}
    </div>
  )
}

export default function DashboardPage() {
  const projects = useAsync(sig => api.projects(50, 0), [])
  const docs = useAsync(sig => api.documents(undefined, 10, 0), [])

  /* Collect all recent jobs from the first few projects in parallel.
     We load up to 5 projects' jobs so the dashboard has real data. */
  const recentJobs = useAsync(
    async sig => {
      if (!projects.data?.length) return []
      const slice = projects.data.slice(0, 5)
      const nested = await Promise.all(
        slice.map(p =>
          api.projectJobs(p.id, 10, 0).catch(() => [] as Job[]),
        ),
      )
      return nested
        .flat()
        .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
        .slice(0, 20)
    },
    [projects.data],
  )

  const totalDocs = docs.data?.length ?? 0
  const totalProjects = projects.data?.length ?? 0
  const activeJobs = (projects.data ?? []).filter(
    p => p.latest_job && !['completed', 'failed', 'cancelled'].includes(p.latest_job.status),
  ).length
  const totalJobs = (projects.data ?? []).reduce((s, p) => s + (p.stats?.job_count ?? 0), 0)

  return (
    <div className="mx-auto max-w-[1200px] p-5">
      {/* Header */}
      <header className="mb-5 border-b border-rule pb-3">
        <div className="flex items-end gap-4">
          <span className="text-[34px] font-bold tracking-tighter text-rule leading-[0.8] select-none">
            00
          </span>
          <div>
            <h1 className="text-[19px] font-bold tracking-tight text-ink leading-tight">Dashboard</h1>
            <p className="mt-0.5 text-[11.5px] text-ink-dim">
              Cross-project activity · {new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}
            </p>
          </div>
        </div>
      </header>

      {/* Stats row */}
      <div className="mb-5 grid grid-cols-2 sm:grid-cols-4 border border-rule">
        <StatBar label="Projects" value={projects.loading ? '…' : totalProjects} />
        <StatBar label="Documents" value={docs.loading ? '…' : totalDocs} />
        <StatBar
          label="Jobs run"
          value={projects.loading ? '…' : totalJobs.toLocaleString()}
        />
        <StatBar
          label="Active jobs"
          value={projects.loading ? '…' : activeJobs}
          sub={activeJobs > 0 ? 'in progress now' : 'all clear'}
        />
      </div>

      {/* Main grid */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_340px]">
        {/* Left column */}
        <div className="flex flex-col gap-4">

          {/* Recent jobs */}
          <section className="plate">
            <header className="flex items-center gap-2.5 border-b border-rule bg-sunk/60 px-3 py-2">
              <h2 className="text-[11.5px] font-semibold tracking-tight text-ink">Recent Jobs</h2>
              <div className="ml-auto tag text-ink-dim">14-day activity</div>
            </header>

            {/* Spark */}
            {recentJobs.data && recentJobs.data.length > 0 && (
              <ActivitySpark jobs={recentJobs.data} />
            )}

            {recentJobs.loading || projects.loading ? (
              <div className="p-3">
                <SkeletonPanel rows={5} />
              </div>
            ) : recentJobs.error ? (
              <div className="p-3">
                <ErrorState message={recentJobs.error} onRetry={recentJobs.reload} compact />
              </div>
            ) : !recentJobs.data?.length ? (
              <EmptyState
                title="No jobs yet"
                body="Analyse a project to see jobs appear here."
                compact
              />
            ) : (
              <div>
                {recentJobs.data.map(job => (
                  <JobRow key={job.id} job={job} projects={projects.data ?? []} />
                ))}
              </div>
            )}
          </section>

          {/* Projects overview */}
          <section className="plate">
            <header className="flex items-center gap-2.5 border-b border-rule bg-sunk/60 px-3 py-2">
              <h2 className="text-[11.5px] font-semibold tracking-tight text-ink">Projects</h2>
              <div className="ml-auto">
                <Link to="/app/projects" className="tag text-hot-ink hover:underline">
                  View all →
                </Link>
              </div>
            </header>
            {projects.loading ? (
              <div className="p-3">
                <SkeletonPanel rows={4} />
              </div>
            ) : projects.error ? (
              <div className="p-3">
                <ErrorState message={projects.error} onRetry={projects.reload} compact />
              </div>
            ) : !projects.data?.length ? (
              <EmptyState title="No projects" compact />
            ) : (
              <div>
                {projects.data.slice(0, 8).map(p => (
                  <Link
                    key={p.id}
                    to={`/app/projects/${p.id}`}
                    className="group flex items-center gap-3 border-b border-rule px-3 py-2.5 last:border-b-0 hover:bg-hot-wash transition-colors"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-[12px] font-semibold text-ink truncate">{p.name}</span>
                        {p.latest_job && <StatusBadge status={p.latest_job.status} />}
                      </div>
                      <div className="tag text-ink-dim mt-0.5">
                        {countLabel(p.stats?.job_count ?? 0, 'job')} ·{' '}
                        {countLabel(p.stats?.doc_count ?? 0, 'doc')} ·{' '}
                        updated {relativeTime(p.updated_at)}
                      </div>
                    </div>
                    <span className="tag text-ink-dim group-hover:text-hot-ink transition-colors plate-arrow shrink-0">→</span>
                  </Link>
                ))}
              </div>
            )}
          </section>
        </div>

        {/* Right column */}
        <div className="flex flex-col gap-4">

          {/* Recent documents */}
          <section className="plate">
            <header className="flex items-center gap-2.5 border-b border-rule bg-sunk/60 px-3 py-2">
              <h2 className="text-[11.5px] font-semibold tracking-tight text-ink">Recent Documents</h2>
              <div className="ml-auto">
                <Link to="/app/documents" className="tag text-hot-ink hover:underline">
                  View all →
                </Link>
              </div>
            </header>
            {docs.loading ? (
              <div className="p-3">
                <SkeletonPanel rows={4} />
              </div>
            ) : docs.error ? (
              <div className="p-3">
                <ErrorState message={docs.error} onRetry={docs.reload} compact />
              </div>
            ) : !docs.data?.length ? (
              <EmptyState title="No documents yet" compact />
            ) : (
              <div>
                {docs.data.map(doc => (
                  <DocRow key={doc.id} doc={doc} />
                ))}
              </div>
            )}
          </section>

          {/* Quick links */}
          <section className="plate">
            <header className="flex items-center gap-2.5 border-b border-rule bg-sunk/60 px-3 py-2">
              <h2 className="text-[11.5px] font-semibold tracking-tight text-ink">Quick Access</h2>
            </header>
            <div className="divide-y divide-rule">
              {[
                { to: '/app/projects', label: 'Projects', sub: 'Create or browse projects' },
                { to: '/app/documents', label: 'Documents', sub: 'All generated documentation' },
                { to: '/app/settings', label: 'Settings', sub: 'LLM configuration' },
              ].map(link => (
                <Link
                  key={link.to}
                  to={link.to}
                  className="group flex items-center gap-3 px-3 py-2.5 hover:bg-hot-wash transition-colors"
                >
                  <span className="block size-[6px] rotate-45 border border-rule group-hover:bg-hot group-hover:border-hot transition-colors shrink-0" />
                  <div className="min-w-0 flex-1">
                    <div className="text-[12px] font-semibold text-ink">{link.label}</div>
                    <div className="tag text-ink-dim">{link.sub}</div>
                  </div>
                  <span className="tag text-ink-dim group-hover:text-hot-ink transition-colors plate-arrow">→</span>
                </Link>
              ))}
            </div>
          </section>

          {/* Pipeline legend */}
          <section className="plate">
            <header className="flex items-center gap-2.5 border-b border-rule bg-sunk/60 px-3 py-2">
              <h2 className="text-[11.5px] font-semibold tracking-tight text-ink">Pipeline</h2>
            </header>
            <div className="p-3 space-y-2.5">
              {[
                { n: '01', label: 'Analyse', desc: 'Probe + clone source, build knowledge base' },
                { n: '02', label: 'Knowledge Base', desc: 'Modules, entities, and narrative topics' },
                { n: '03', label: 'Choose', desc: 'Select doc types by confidence score' },
                { n: '04', label: 'Compose', desc: 'LLM writes Markdown, DOCX, or site output' },
              ].map(step => (
                <div key={step.n} className="flex gap-3">
                  <span className="text-[18px] font-bold tracking-tighter text-rule leading-none select-none shrink-0 mt-0.5">
                    {step.n}
                  </span>
                  <div>
                    <div className="text-[11.5px] font-semibold text-ink">{step.label}</div>
                    <div className="tag text-ink-dim mt-0.5 normal-case tracking-[0.02em] font-sans text-[10.5px]">
                      {step.desc}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
