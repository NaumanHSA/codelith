import { useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../../lib/api'
import { useAsync } from '../../lib/hooks'
import { useAuth } from '../../auth'
import { formatDuration, elapsedSeconds, humanize, relativeTime } from '../../lib/format'
import { describeJobScope } from '../../lib/site'
import { isTerminal, type Job } from '../../lib/types'
import { Button, Chip, PageHead, StatusBadge } from '../../components/ui'
import { IconTile } from '../../components/primitives'
import { Icon } from '../../lib/icons'
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
  const [params, setParams] = useSearchParams()
  // Arrived from a project's "all →". Kept in the URL so the view is linkable and
  // survives a reload, rather than being lost the moment you refresh.
  const projectId = Number(params.get('project')) || null
  const { data, error, loading, reload } = useAsync(s => api.jobs(200, 0, null, s), [])
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('all')
  const [doomed, setDoomed] = useState<Job | null>(null)

  const scoped = useMemo(
    () => (data ?? []).filter(j => !projectId || j.project_id === projectId),
    [data, projectId],
  )
  const jobs = useMemo(
    () => scoped.filter(j => filter === 'all' || j.status === filter),
    [scoped, filter],
  )
  const counts = useMemo(() => {
    const out: Record<string, number> = {}
    for (const j of scoped) out[j.status] = (out[j.status] ?? 0) + 1
    return out
  }, [scoped])
  const projectName = scoped[0]?.project_name ?? null

  return (
    <div className="w-full px-6 py-5">
      <PageHead
        index="04"
        title="Runs"
        sub={
          projectId
            ? `Every run for ${projectName ?? `project ${projectId}`}, newest first.`
            : "Every run, newest first: analysis, composition and revision."
        }
        right={
          <Button variant="ghost" onClick={reload}>
            <Icon name="refresh-cw" size={14} /> Refresh
          </Button>
        }
      />

      <div className="mb-3 flex flex-wrap items-center gap-1.5">
        {projectId && (
          <button
            onClick={() => {
              const next = new URLSearchParams(params)
              next.delete('project')
              setParams(next, { replace: true })
            }}
            className="inline-flex items-center gap-1.5 rounded-md border border-hot-edge bg-hot-wash px-2 py-[3px] text-[12px] font-medium text-hot-ink transition-colors hover:bg-hot hover:text-on-hot"
          >
            {projectName ?? `project ${projectId}`} <Icon name="x" size={12} />
          </button>
        )}
        {FILTERS.map(f => (
          <Chip key={f} active={filter === f} onClick={() => setFilter(f)}>
            {f.charAt(0).toUpperCase() + f.slice(1)}
            {f !== 'all' && counts[f] ? <span className="font-mono text-ink-dim">{counts[f]}</span> : null}
          </Chip>
        ))}
        <span className="ml-auto text-[12.5px] text-ink-dim">
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
        <div className="overflow-x-auto">
          <table className="tbl">
            <thead>
              <tr>
                <th>Run</th>
                <th>Codebase</th>
                <th>What it did</th>
                <th className="num">Took</th>
                <th>When</th>
                <th>State</th>
                {can('manager') && <th />}
              </tr>
            </thead>
            <tbody>
              {jobs.map(j => {
                const live = !isTerminal(j.status)
                const seconds = elapsedSeconds(j.started_at ?? j.created_at, j.completed_at)
                const open = () => navigate(`/app/projects/${j.project_id}/jobs/${j.id}`)
                return (
                  <tr key={j.id} data-link onClick={open}>
                    <td>
                      <Link
                        to={`/app/projects/${j.project_id}/jobs/${j.id}`}
                        onClick={e => e.stopPropagation()}
                        className="flex items-center gap-2.5"
                      >
                        <IconTile icon={j.job_type === 'analysis' ? 'radar' : 'pencil'} size={30} />
                        <span>
                          <span className="block text-[13.5px] font-medium text-ink">{humanize(j.job_type)}</span>
                          <span className="font-mono text-[11.5px] text-ink-dim">#{j.id}</span>
                        </span>
                      </Link>
                    </td>
                    <td className="text-[13px] text-ink-mid">{j.project_name ?? `project ${j.project_id}`}</td>
                    <td className="max-w-[380px] text-[13px] text-ink-mid">
                      {j.error_message ? (
                        <span title={j.error_message} className="line-clamp-2 text-bad">
                          {j.error_message}
                        </span>
                      ) : (
                        describeJobScope(j) ?? (j.job_type === 'analysis' ? 'Read the whole repository' : '-')
                      )}
                    </td>
                    <td className="num font-mono text-[12.5px] text-ink-mid">{seconds ? formatDuration(seconds) : '-'}</td>
                    <td className="text-[12.5px] whitespace-nowrap text-ink-dim">{relativeTime(j.created_at)}</td>
                    <td>
                      <StatusBadge status={j.status} />
                    </td>
                    {can('manager') && (
                      <td className="w-10">
                        <button
                          onClick={e => {
                            e.stopPropagation()
                            setDoomed(j)
                          }}
                          title={live ? 'Cancel and remove this run' : 'Remove this run'}
                          aria-label={live ? 'Cancel and remove this run' : 'Remove this run'}
                          className="grid size-8 place-items-center rounded-md text-ink-dim transition-colors hover:bg-bad-wash hover:text-bad"
                        >
                          <Icon name="trash" size={14} />
                        </button>
                      </td>
                    )}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
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
                first: the worker stops, then the record goes.
              </p>
            ) : (
              <p>This removes the run and its logs.</p>
            )}
            <p className="mt-2">
              Anything it wrote (documents and site pages) is kept. They record what
              produced them, so the history survives without the job row.
            </p>
          </>
        }
      />
    </div>
  )
}
