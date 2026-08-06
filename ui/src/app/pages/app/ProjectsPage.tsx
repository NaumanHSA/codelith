import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../lib/api'
import { useAsync } from '../../lib/hooks'
import { useAuth } from '../../auth'
import { countLabel, languageShares, relativeTime, shortSha } from '../../lib/format'
import type { Project } from '../../lib/types'
import { Button, Chip, PageHead, StatusBadge } from '../../components/ui'
import ConfirmDelete from '../../components/ConfirmDelete'
import { EmptyState, ErrorState, SkeletonGrid } from '../../components/States'
import NewProjectDialog from '../../components/projects/NewProjectDialog'

function probeOf(p: Project) {
  return p.sources?.[0]?.config_json?.probe
}

function ProjectCard({
  p, i, onOpen, onDelete,
}: {
  p: Project
  i: number
  onOpen: () => void
  onDelete?: () => void
}) {
  const probe = probeOf(p)
  const shares = languageShares(probe?.languages)
  const source = p.sources?.[0]

  return (
    <div className="relative" style={{ animationDelay: `${Math.min(i, 12) * 40}ms` }}>
      {onDelete && (
        <button
          onClick={onDelete}
          title={`Delete ${p.name}`}
          aria-label={`Delete ${p.name}`}
          className="tag absolute top-2 right-2 z-10 border border-rule bg-panel px-1.5 py-[2px] text-ink-dim opacity-0 transition-all group-hover/card:opacity-100 hover:border-bad hover:text-bad focus:opacity-100"
        >
          ✕
        </button>
      )}
    <button
      onClick={onOpen}
      className="plate plate-lift anim-rise group/card flex w-full flex-col text-left"
    >
      <span className="flex items-center gap-2 border-b border-rule bg-sunk/60 px-3 py-2">
        <span className="tag text-ink-dim">{String(p.id).padStart(2, '0')}</span>
        <span className="min-w-0 flex-1 truncate text-[13px] font-bold tracking-tight text-ink">
          {p.name}
        </span>
        {p.latest_job && <StatusBadge status={p.latest_job.status} />}
      </span>

      <span className="flex-1 px-3 py-2.5">
        <span className="mb-2.5 line-clamp-2 block min-h-[2.4em] font-sans text-[11.5px] leading-relaxed text-ink-mid">
          {p.description || source?.url_or_path || 'No description.'}
        </span>

        {shares.length > 0 ? (
          <>
            <span className="flex h-[6px] w-full overflow-hidden border border-rule">
              {shares.slice(0, 6).map((l, li) => (
                <span
                  key={l.name}
                  title={`${l.name} · ${countLabel(l.count, 'file')}`}
                  style={{ width: `${l.pct}%`, opacity: 1 - li * 0.13 }}
                  className="block bg-hot"
                />
              ))}
            </span>
            <span className="mt-1.5 flex flex-wrap gap-x-2.5 gap-y-1">
              {shares.slice(0, 3).map(l => (
                <span key={l.name} className="tag text-ink-dim">
                  {l.name} {Math.round(l.pct)}%
                </span>
              ))}
            </span>
          </>
        ) : (
          <span className="tag block text-ink-dim">not analysed yet</span>
        )}
      </span>

      <span className="grid grid-cols-4 gap-px border-t border-rule bg-rule">
        {[
          ['files', probe?.file_count?.toLocaleString() ?? '—'],
          ['jobs', p.stats?.job_count ?? 0],
          ['docs', p.stats?.doc_count ?? 0],
          ['sha', shortSha(probe?.commit_sha)],
        ].map(([k, v]) => (
          <span key={k as string} className="block bg-panel px-2 py-1.5">
            <span className="tag mb-[3px] block text-ink-dim">{k as string}</span>
            <span className="block truncate text-[11.5px] font-semibold text-ink">{v}</span>
          </span>
        ))}
      </span>
    </button>
    </div>
  )
}

export default function ProjectsPage() {
  const navigate = useNavigate()
  const { can } = useAuth()
  const { data, error, loading, reload, setData } = useAsync(() => api.projects(50, 0), [])
  const [q, setQ] = useState('')
  const [view, setView] = useState<'grid' | 'table'>('grid')
  const [creating, setCreating] = useState(false)
  const [doomed, setDoomed] = useState<Project | null>(null)

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase()
    if (!needle) return data ?? []
    return (data ?? []).filter(
      p =>
        p.name.toLowerCase().includes(needle) ||
        (p.description ?? '').toLowerCase().includes(needle) ||
        (p.sources ?? []).some(s => s.url_or_path.toLowerCase().includes(needle)),
    )
  }, [data, q])

  const canCreate = can('manager')

  return (
    <div className="mx-auto max-w-[1180px] p-5">
      <PageHead
        index="02"
        title="Projects"
        sub="Every repository under analysis, and what has been written from each."
        right={
          canCreate ? (
            <Button variant="hot" onClick={() => setCreating(true)}>
              + New project
            </Button>
          ) : (
            <Chip title="Requires the manager role">read-only role</Chip>
          )
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2 border border-rule bg-panel px-2 py-1.5">
        <span className="tag pl-1 text-hot">/</span>
        <input
          value={q}
          onChange={e => setQ(e.target.value)}
          placeholder="filter projects…"
          className="min-w-[160px] flex-1 bg-transparent py-1 text-[12px] text-ink placeholder:text-ink-dim focus:outline-none"
        />
        <span className="tag text-ink-dim">{countLabel(filtered.length, 'project')}</span>
        <span className="h-4 w-px bg-rule" />
        {(['grid', 'table'] as const).map(v => (
          <Chip key={v} active={view === v} onClick={() => setView(v)}>
            {v}
          </Chip>
        ))}
      </div>

      {loading && <SkeletonGrid count={6} />}

      {!loading && error && <ErrorState message={error} onRetry={reload} />}

      {!loading && !error && filtered.length === 0 && (
        <EmptyState
          title={q ? 'Nothing matches that filter' : 'No projects yet'}
          body={
            q
              ? 'Try a different name, or clear the filter.'
              : 'Point the studio at a repository and it will clone, walk and index it before writing a word.'
          }
          action={
            q ? (
              <Button variant="ghost" onClick={() => setQ('')}>
                Clear filter
              </Button>
            ) : canCreate ? (
              <Button variant="hot" onClick={() => setCreating(true)}>
                + New project
              </Button>
            ) : null
          }
        />
      )}

      {!loading && !error && filtered.length > 0 && view === 'grid' && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {filtered.map((p, i) => (
            <ProjectCard
              key={p.id}
              p={p}
              i={i}
              onOpen={() => navigate(`/app/projects/${p.id}`)}
              onDelete={canCreate ? () => setDoomed(p) : undefined}
            />
          ))}
        </div>
      )}

      {!loading && !error && filtered.length > 0 && view === 'table' && (
        <div className="overflow-x-auto border border-rule bg-panel">
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="bg-sunk/60">
                {['', 'project', 'source', 'files', 'jobs', 'docs', 'updated', 'status'].map(h => (
                  <th key={h} className="tag border-b border-rule px-2.5 py-2 text-ink-dim">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map(p => {
                const probe = probeOf(p)
                return (
                  <tr
                    key={p.id}
                    onClick={() => navigate(`/app/projects/${p.id}`)}
                    className="cursor-pointer border-b border-rule transition-colors last:border-b-0 hover:bg-hot-wash/50"
                  >
                    <td className="tag px-2.5 py-2 text-ink-dim">{p.id}</td>
                    <td className="px-2.5 py-2 text-[12px] font-semibold text-ink">{p.name}</td>
                    <td className="max-w-[240px] truncate px-2.5 py-2 text-[11px] text-ink-dim">
                      {p.sources?.[0]?.url_or_path ?? '—'}
                    </td>
                    <td className="px-2.5 py-2 text-[11.5px] tabular-nums text-ink-mid">
                      {probe?.file_count?.toLocaleString() ?? '—'}
                    </td>
                    <td className="px-2.5 py-2 text-[11.5px] tabular-nums text-ink-mid">
                      {p.stats?.job_count ?? 0}
                    </td>
                    <td className="px-2.5 py-2 text-[11.5px] tabular-nums text-ink-mid">
                      {p.stats?.doc_count ?? 0}
                    </td>
                    <td className="px-2.5 py-2 text-[11px] text-ink-dim">
                      {relativeTime(p.updated_at)}
                    </td>
                    <td className="px-2.5 py-2">
                      {p.latest_job ? (
                        <StatusBadge status={p.latest_job.status} />
                      ) : (
                        <span className="tag text-ink-dim">never run</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <NewProjectDialog
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={p => {
          setCreating(false)
          setData([p, ...(data ?? [])])
          navigate(`/app/projects/${p.id}`)
        }}
      />

      <ConfirmDelete
        open={doomed !== null}
        onClose={() => setDoomed(null)}
        onConfirm={async () => {
          if (doomed) await api.deleteProject(doomed.id)
          reload()
        }}
        title={`Delete ${doomed?.name ?? 'project'}`}
        actionLabel="Delete everything"
        confirmText={doomed?.name}
        body={
          <>
            <p>
              This removes the project and everything derived from it — its knowledge
              base, every job, every document, and the whole documentation site with
              its pages and versions.
            </p>
            <p className="mt-2">
              The repository itself is untouched. Nothing here can be recovered.
            </p>
          </>
        }
      />
    </div>
  )
}
