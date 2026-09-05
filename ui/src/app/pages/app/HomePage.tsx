import { Link } from 'react-router-dom'
import { useAsync } from '../../lib/hooks'
import { api } from '../../lib/api'
import { relativeTime } from '../../lib/format'
import { StatusBadge } from '../../components/ui'
import { EmptyState, ErrorState, SkeletonPanel } from '../../components/States'
import Pipeline from '../../components/home/Pipeline'
import HomeBanner from '../../components/home/HomeBanner'
import AgentTicker from '../../components/home/AgentTicker'
import JobsTimeline from '../../components/home/JobsTimeline'
import RecentProjects from '../../components/home/RecentProjects'
import type { Doc, Job } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * Home.
 *
 * It opens by saying what the product is, because the only other place
 * that explains it is the landing page, which you stop seeing the moment
 * you have an account. Then what you can do, then what has been
 * happening. Independent fetches, so one failure does not blank it.
 * ------------------------------------------------------------------ */

/** Rows in the recent panels. They are shortcuts back to recent work; the
 *  index each one links to is the place to see everything. */
const RECENT = 3

function JobRow({ job }: { job: Job }) {
  const duration =
    job.started_at && job.completed_at
      ? Math.round(
          (new Date(job.completed_at).getTime() - new Date(job.started_at).getTime()) / 1000,
        )
      : null

  return (
    <Link
      to={`/app/projects/${job.project_id}/jobs/${job.id}`}
      className="group flex items-center gap-3 border-b border-rule px-3 py-2.5 transition-colors last:border-b-0 hover:bg-hot-wash"
    >
      <StatusBadge status={job.status} />
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate text-[12px] font-semibold text-ink">
            {job.project_name ?? `Project ${job.project_id}`}
          </span>
          <span className="tag shrink-0 text-ink-dim">{job.job_type}</span>
        </div>
        <div className="tag mt-0.5 text-ink-dim">
          {relativeTime(job.created_at)}
          {duration != null &&
            ` · ${duration < 60 ? `${duration}s` : `${Math.round(duration / 60)}m`}`}
        </div>
      </div>
      <span className="tag plate-arrow shrink-0 text-ink-dim transition-colors group-hover:text-hot-ink">
        →
      </span>
    </Link>
  )
}

function DocRow({ doc }: { doc: Doc }) {
  return (
    <Link
      to={`/app/documents/${doc.id}`}
      className="group flex items-center gap-3 border-b border-rule px-3 py-2.5 transition-colors last:border-b-0 hover:bg-hot-wash"
    >
      <span className="block size-[7px] shrink-0 rotate-45 bg-hot" />
      <div className="min-w-0 flex-1">
        <div className="truncate text-[12px] font-semibold text-ink">{doc.title}</div>
        <div className="tag mt-0.5 text-ink-dim">
          {doc.doc_type.replace(/_/g, ' ')} · {relativeTime(doc.created_at)}
        </div>
      </div>
      <StatusBadge status={doc.status} />
    </Link>
  )
}

export default function HomePage() {
  const projects = useAsync(() => api.projects(50, 0), [])
  const docs = useAsync(() => api.documents(undefined, 10, 0), [])
  const features = useAsync(sig => api.appCatalog(sig), [])

  // One cross-project call. Home used to fan out to the first five projects'
  // job lists and merge them, which cost five requests and quietly excluded
  // every project after the fifth from the chart.
  const jobs = useAsync(sig => api.jobs(200, 0, null, sig), [])

  return (
    <div className="mx-auto max-w-[1200px]">
      {/* The banner, the strip and the schematic stack flush, with no page padding
          and nothing between them. A banner inset from the page edge is a panel, and
          the strip only reads as the separator it is when it touches what it
          separates. Everything below returns to the page's normal gutter. */}
      <HomeBanner projects={projects.data ?? null} />
      <AgentTicker />
      <Pipeline features={features.data ?? null} />

      {/* Vertical gutter only. A horizontal one here made every panel below
          40px narrower than the three bands above, which reads as a mistake
          rather than as a margin. */}
      <div className="py-5">
        <JobsTimeline jobs={jobs.data ?? null} loading={jobs.loading} />

      {/* Two columns: the work on the left, what came out of it on the right.
          Documents span both rows rather than sitting under one of them —
          it is a list of its own length, not a footnote to either. */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_340px]">
        <div className="flex flex-col gap-4">
          <RecentProjects
            projects={projects.data ?? null}
            loading={projects.loading}
            error={projects.error}
            onRetry={projects.reload}
          />

          <section className="plate overflow-hidden">
            <header className="flex items-center gap-2.5 border-b border-rule bg-sunk/60 px-3 py-2">
              <h2 className="text-[11.5px] font-semibold tracking-tight text-ink">
                Recent jobs
              </h2>
              <Link
                to="/app/jobs"
                className="tag plate-arrow ml-auto text-hot-ink hover:underline"
              >
                View all →
              </Link>
            </header>

            {jobs.loading ? (
              <div className="p-3">
                <SkeletonPanel rows={3} />
              </div>
            ) : jobs.error ? (
              <div className="p-3">
                <ErrorState message={jobs.error} onRetry={jobs.reload} compact />
              </div>
            ) : !jobs.data?.length ? (
              <EmptyState
                title="No jobs yet"
                body="Analyse a codebase to see jobs appear here."
                compact
              />
            ) : (
              <div>
                {jobs.data.slice(0, RECENT).map(job => (
                  <JobRow key={job.id} job={job} />
                ))}
              </div>
            )}
          </section>
        </div>

        <section className="plate flex flex-col">
          <header className="flex items-center gap-2.5 border-b border-rule bg-sunk/60 px-3 py-2">
            <h2 className="text-[11.5px] font-semibold tracking-tight text-ink">
              Recent documents
            </h2>
            <Link
              to="/app/documents"
              className="tag plate-arrow ml-auto text-hot-ink hover:underline"
            >
              View all →
            </Link>
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
            // This panel spans both rows on the left, so it has room for more
            // than three — and scrolls rather than stretching the grid.
            <div className="min-h-0 flex-1 overflow-y-auto">
              {docs.data.map(doc => (
                <DocRow key={doc.id} doc={doc} />
              ))}
            </div>
          )}
        </section>
        </div>
      </div>
    </div>
  )
}
