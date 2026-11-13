import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../../lib/api'
import { useAsync } from '../../lib/hooks'
import { useAuth } from '../../auth'
import { countLabel, languageShares, relativeTime } from '../../lib/format'
import { BrandMark, languageBrand, sourceBrand } from '../../lib/brands'
import { Icon } from '../../lib/icons'
import { CodebaseMark, Pill } from '../../components/primitives'
import type { Project } from '../../lib/types'
import { Button, Chip, PageHead } from '../../components/ui'
import ConfirmDelete from '../../components/ConfirmDelete'
import { EmptyState, ErrorState, SkeletonPanel } from '../../components/States'
import NewProjectDialog from '../../components/projects/NewProjectDialog'

function probeOf(p: Project) {
  return p.sources?.[0]?.config_json?.probe
}

export default function ProjectsPage() {
  const navigate = useNavigate()
  const { can } = useAuth()
  const { data, error, loading, reload, setData } = useAsync(() => api.projects(50, 0), [])
  const [q, setQ] = useState('')
  const [searchParams, setSearchParams] = useSearchParams()
  // `?new=1` opens the form directly, so "Add a codebase" on Home lands on
  // the action rather than on a list the reader then has to find the button in.
  const [creating, setCreating] = useState(searchParams.get('new') === '1')

  useEffect(() => {
    if (searchParams.get('new') !== '1') return
    setCreating(true)
    // Consumed, so a reload or a back-navigation does not reopen it.
    searchParams.delete('new')
    setSearchParams(searchParams, { replace: true })
  }, [searchParams, setSearchParams])
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
    <div className="w-full px-6 py-5">
      <PageHead
        index="02"
        title="Codebases"
        sub="Every repository Codelith has been pointed at, and what has been done with each."
        right={
          canCreate ? (
            <Button variant="hot" onClick={() => setCreating(true)}>
              <Icon name="folder-plus" size={15} /> Add a codebase
            </Button>
          ) : (
            <Chip title="Requires the manager role">Read-only role</Chip>
          )
        }
      />

      <div className="mb-5 flex flex-wrap items-center gap-3">
        <label className="flex h-9 w-[min(420px,100%)] items-center gap-2 rounded-lg border border-line-2 bg-sunk px-3 focus-within:border-hot">
          <Icon name="search" size={15} className="text-ink-dim" />
          <input
            value={q}
            onChange={e => setQ(e.target.value)}
            placeholder="Find a codebase by name, description or URL"
            aria-label="Find a codebase"
            className="min-w-0 flex-1 bg-transparent text-[13px] text-ink placeholder:text-ink-dim focus:outline-none"
          />
        </label>
        <span className="text-[12.5px] text-ink-dim">{countLabel(filtered.length, 'codebase')}</span>
      </div>

      {loading && <SkeletonPanel rows={6} />}

      {!loading && error && <ErrorState message={error} onRetry={reload} />}

      {!loading && !error && filtered.length === 0 && (
        <EmptyState
          title={q ? 'Nothing matches that' : 'No codebases yet'}
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
                <Icon name="folder-plus" size={15} /> Add a codebase
              </Button>
            ) : null
          }
        />
      )}

      {!loading && !error && filtered.length > 0 && (
        <div className="overflow-x-auto">
          <table className="tbl">
            <thead>
              <tr>
                <th>Codebase</th>
                <th>Languages</th>
                <th className="num">Files</th>
                <th className="num">Runs</th>
                <th className="num">Pages</th>
                <th>Reading</th>
                <th>Updated</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {filtered.map(p => {
                const probe = probeOf(p)
                const shares = languageShares(probe?.languages)
                const host = sourceBrand(p.sources?.[0]?.source_type)
                return (
                  <tr key={p.id} data-link onClick={() => navigate(`/app/projects/${p.id}`)}>
                    <td>
                      <span className="flex items-center gap-3">
                        <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-sunk shadow-[inset_0_0_0_1px_var(--line-2)]">
                          <CodebaseMark project={p} size={18} />
                        </span>
                        <span className="min-w-0">
                          <span className="block text-[14px] font-medium text-ink">{p.name}</span>
                          <span className="flex max-w-[420px] items-center gap-1.5 truncate font-mono text-[11.5px] text-ink-dim">
                            {host ? <BrandMark name={host} size={11} decorative /> : <Icon name="folder" size={11} />}
                            {p.sources?.[0]?.url_or_path ?? '-'}
                          </span>
                        </span>
                      </span>
                    </td>
                    <td>
                      <span className="flex items-center gap-2.5">
                        {shares.slice(0, 4).map(l => {
                          const b = languageBrand(l.name)
                          return (
                            <span key={l.name} title={`${l.name} ${Math.round(l.pct)}%`} className="flex items-center gap-1 text-[12px] text-ink-dim">
                              {b ? <BrandMark name={b} size={15} decorative /> : <span>{l.name}</span>}
                              {Math.round(l.pct)}%
                            </span>
                          )
                        })}
                      </span>
                    </td>
                    <td className="num font-mono text-[12.5px] text-ink-mid">
                      {(probe?.analysable_files ?? probe?.file_count)?.toLocaleString() ?? '-'}
                    </td>
                    <td className="num font-mono text-[12.5px] text-ink-mid">{p.stats?.job_count ?? 0}</td>
                    <td className="num font-mono text-[12.5px] text-ink-mid">{p.stats?.page_count ?? 0}</td>
                    <td>
                      {p.latest_job?.status === 'running' ? (
                        <Pill tone="hot" icon="loader">Analysing</Pill>
                      ) : p.kb_status === 'stale' ? (
                        <Pill tone="warn" icon="clock">Stale</Pill>
                      ) : p.apps_ready ? (
                        <Pill tone="good" icon="check">Read</Pill>
                      ) : (
                        <Pill icon="circle-dashed">Not read yet</Pill>
                      )}
                    </td>
                    <td className="text-[12.5px] whitespace-nowrap text-ink-dim">{relativeTime(p.updated_at)}</td>
                    <td>
                      <span className="flex justify-end gap-1" onClick={e => e.stopPropagation()}>
                        {p.apps_ready && (
                          <>
                            <Link
                              to={`/app/projects/${p.id}/graph`}
                              title="Open the knowledge graph"
                              aria-label={`Open the knowledge graph of ${p.name}`}
                              className="grid size-8 place-items-center rounded-md text-ink-dim transition-colors hover:bg-hover hover:text-ink"
                            >
                              <Icon name="waypoints" size={15} />
                            </Link>
                            <Link
                              to={`/app/chat?project=${p.id}&thread=new`}
                              title="Ask about it"
                              aria-label={`Ask about ${p.name}`}
                              className="grid size-8 place-items-center rounded-md text-ink-dim transition-colors hover:bg-hover hover:text-ink"
                            >
                              <Icon name="message-square" size={15} />
                            </Link>
                          </>
                        )}
                        {canCreate && (
                          <button
                            type="button"
                            onClick={() => setDoomed(p)}
                            title="Delete this codebase"
                            aria-label={`Delete ${p.name}`}
                            className="grid size-8 place-items-center rounded-md text-ink-dim transition-colors hover:bg-bad-wash hover:text-bad"
                          >
                            <Icon name="trash" size={15} />
                          </button>
                        )}
                      </span>
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
        title={`Delete ${doomed?.name ?? 'this codebase'}`}
        actionLabel="Delete everything"
        confirmText={doomed?.name}
        body={
          <>
            <p>
              This removes the codebase and everything derived from it: its knowledge
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
