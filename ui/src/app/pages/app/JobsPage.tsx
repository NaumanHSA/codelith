import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../../lib/api'
import { useAsync } from '../../lib/hooks'
import { useAuth } from '../../auth'
import { formatDuration, elapsedSeconds, humanize, relativeTime } from '../../lib/format'
import { describeJobScope } from '../../lib/site'
import { isTerminal, type Job } from '../../lib/types'
import { Button, Chip, PageHead, StatusBadge } from '../../components/ui'
import { EmptyState, ErrorState, SkeletonPanel } from '../../components/States'
import ConfirmDelete from '../../components/ConfirmDelete'

/* ------------------------------------------------------------------ *
 * Every run, across every project.
 *
 * The project page shows a project's own jobs; this is the view for
 * "what has this machine been doing", which is where you go when
 * something is stuck or you want to clear out a failed attempt.
 * ------------------------------------------------------------------ */

const FILTERS = ['all', 'running', 'completed', 'failed', 'cancelled'] as const

export default function JobsPage() {
  const navigate = useNavigate()
  const { can } = useAuth()
  const { data, error, loading, reload } = useAsync(s => api.jobs(100, 0, null, s), [])
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('all')
  const [doomed, setDoomed] = useState<Job | null>(null)

  const jobs = useMemo(
    () => (data ?? []).filter(j => filter === 'all' || j.status === filter),
    [data, filter],
  )
  const counts = useMemo(() => {
    const out: Record<string, number> = {}
    for (const j of data ?? []) out[j.status] = (out[j.status] ?? 0) + 1
    return out
  }, [data])

  return (
    <div className="mx-auto max-w-[1100px] p-5">
      <PageHead
        index="04"
        title="Jobs"
        sub="Every analysis and composition run, newest first."
        right={
          <Button variant="ghost" onClick={reload}>
            ↻ Refresh
          </Button>
        }
      />

      <div className="mb-3 flex flex-wrap items-center gap-1.5">
        {FILTERS.map(f => (
          <Chip key={f} active={filter === f} onClick={() => setFilter(f)}>
            {f}
            {f !== 'all' && counts[f] ? ` ${counts[f]}` : ''}
          </Chip>
        ))}
        <span className="tag ml-auto text-ink-dim">
          {jobs.length} of {data?.length ?? 0}
        </span>
      </div>

      {loading && <SkeletonPanel rows={8} />}
      {error && <ErrorState message={error} onRetry={reload} />}

      {data && jobs.length === 0 && (
        <EmptyState
          title={filter === 'all' ? 'Nothing has run yet' : `No ${filter} jobs`}
          body={
            filter === 'all'
              ? 'Analyse a project and its runs appear here.'
              : 'Try another filter.'
          }
          action={
            <Button variant="ghost" onClick={() => navigate('/app/projects')}>
              Go to projects
            </Button>
          }
        />
      )}

      {jobs.length > 0 && (
        <ul className="plate divide-y divide-rule">
          {jobs.map(j => {
            const live = !isTerminal(j.status)
            const seconds = elapsedSeconds(j.started_at ?? j.created_at, j.completed_at)
            return (
              <li key={j.id} className="flex items-center gap-3 px-3 py-2.5">
                <span className="tag w-9 shrink-0 text-ink-dim">#{j.id}</span>

                <Link
                  to={`/app/projects/${j.project_id}/jobs/${j.id}`}
                  className="min-w-0 flex-1"
                >
                  <span className="flex flex-wrap items-baseline gap-x-2">
                    <span className="text-[12.5px] font-semibold text-ink hover:text-hot-ink">
                      {humanize(j.job_type)}
                    </span>
                    <span className="tag text-ink-dim">{j.project_name ?? `project ${j.project_id}`}</span>
                  </span>
                  {/* What the run was for, not just that it ran. An analysis job
                      has no scope — it reads the whole repository — so it simply
                      shows its timing rather than an apology for the empty field. */}
                  <span className="mt-0.5 block truncate text-[11px] text-ink-dim">
                    {[
                      describeJobScope(j),
                      relativeTime(j.created_at),
                      seconds ? formatDuration(seconds) : null,
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </span>
                </Link>

                {j.error_message && (
                  <span
                    title={j.error_message}
                    className="hidden max-w-[220px] truncate text-[11px] text-bad md:block"
                  >
                    {j.error_message}
                  </span>
                )}

                <StatusBadge status={j.status} />

                {can('manager') && (
                  <button
                    onClick={() => setDoomed(j)}
                    title={live ? 'Cancel and remove this run' : 'Remove this run'}
                    className="tag shrink-0 border border-rule bg-panel px-1.5 py-[3px] text-ink-dim transition-colors hover:border-bad hover:text-bad"
                  >
                    ✕
                  </button>
                )}
              </li>
            )
          })}
        </ul>
      )}

      <ConfirmDelete
        open={doomed !== null}
        onClose={() => setDoomed(null)}
        onConfirm={async () => {
          if (doomed) await api.deleteJob(doomed.id)
          reload()
        }}
        title={`Delete job #${doomed?.id}`}
        actionLabel="Delete the run"
        body={
          <>
            {doomed && !isTerminal(doomed.status) ? (
              <p>
                This run is still <strong>{doomed.status}</strong>. It will be cancelled
                first — the worker stops, then the record goes.
              </p>
            ) : (
              <p>This removes the run and its logs.</p>
            )}
            <p className="mt-2">
              Anything it wrote — documents and site pages — is kept. They record what
              produced them, so the history survives without the job row.
            </p>
          </>
        }
      />
    </div>
  )
}
