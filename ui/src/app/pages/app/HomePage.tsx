import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../../lib/api'
import { useAsync } from '../../lib/hooks'
import { useAuth } from '../../auth'
import { useChatThreads } from '../../chat-threads'
import { useProjectsList } from '../../projects-list'
import { BrandMark, languageBrand } from '../../lib/brands'
import { humanize, languageShares, relativeTime } from '../../lib/format'
import { Icon } from '../../lib/icons'
import { stagger } from '../../lib/motion'
import type { Project } from '../../lib/types'
import { CodebaseMark, IconTile, ListRow, Pill, StatBlock } from '../../components/primitives'
import { StatusBadge } from '../../components/ui'
import { SkeletonPanel } from '../../components/States'
import NewProjectDialog from '../../components/projects/NewProjectDialog'
import Pipeline from '../../components/home/Pipeline'

/* ------------------------------------------------------------------ *
 * Home: what Codelith is for, in one line and one picture, then what is
 * in it — the codebases, the conversations, the runs. A new installation
 * gets one thing to do: add a codebase.
 * ------------------------------------------------------------------ */

function Readiness({ p }: { p: Project }) {
  if (p.latest_job?.status === 'running')
    return (
      <Pill tone="hot" icon="loader">
        Analysing
      </Pill>
    )
  if (p.kb_status === 'stale')
    return (
      <Pill tone="warn" icon="clock">
        Stale
      </Pill>
    )
  return p.apps_ready ? (
    <Pill tone="good" icon="check">
      Read
    </Pill>
  ) : (
    <Pill icon="circle-dashed">Not read yet</Pill>
  )
}

export default function HomePage() {
  const navigate = useNavigate()
  const { can } = useAuth()
  const { projects, loading, refresh } = useProjectsList()
  const { threads } = useChatThreads()
  const jobs = useAsync(sig => api.jobs(8, 0, null, sig), [])
  const [creating, setCreating] = useState(false)

  const totals = useMemo(() => {
    let files = 0
    let pages = 0
    for (const p of projects) {
      files += p.sources?.[0]?.config_json?.probe?.analysable_files ?? 0
      pages += p.stats?.page_count ?? 0
    }
    return { files, pages }
  }, [projects])

  const first = !loading && projects.length === 0

  return (
    <div className="flex w-full flex-col gap-10 px-6 py-8">
      <section className="grid grid-cols-1 items-end gap-8 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <div className="flex flex-col gap-4">
          <h1 className="max-w-[18ch] text-[34px] leading-[1.1] font-semibold text-ink">
            Read a codebase once. <span className="text-hot-ink">Use it many times.</span>
          </h1>
          <p className="max-w-[62ch] text-[14.5px] leading-relaxed text-ink-mid">
            Codelith reads a repository file by file and keeps what it learned: what imports what, who
            calls whom, the routes, settings and services it declares, and prose about how it fits
            together. Everything else reads that, on your machine: a map of what breaks if a file
            changes, answers with checked citations, the difference between two readings, and
            documentation.
          </p>
          <div className="flex flex-wrap gap-2">
            {can('manager') && (
              <button
                type="button"
                onClick={() => setCreating(true)}
                className="inline-flex items-center gap-2 rounded-lg bg-hot px-4 py-2 text-[13.5px] font-medium text-on-hot transition-colors hover:bg-hot-ink"
              >
                <Icon name="folder-plus" size={16} /> Add a codebase
              </button>
            )}
            {projects.length > 0 && (
              <Link
                to="/app/projects"
                className="inline-flex items-center gap-2 rounded-lg border border-line-2 bg-sunk px-4 py-2 text-[13.5px] font-medium text-ink transition-colors hover:bg-hover"
              >
                <Icon name="folder-git-2" size={16} /> Open a codebase
              </Link>
            )}
            <a
              href="https://github.com/NaumanHSA/codelith"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-2 rounded-lg px-3 py-2 text-[13.5px] font-medium text-ink-mid transition-colors hover:text-ink"
            >
              <BrandMark name="github" size={15} decorative /> Source
            </a>
          </div>
        </div>
        {!first && (
          <div className="grid grid-cols-2 gap-x-6 border-y border-rule sm:grid-cols-4">
            <StatBlock value={projects.length} label={projects.length === 1 ? 'codebase' : 'codebases'} icon="folder-git-2" />
            <StatBlock value={totals.files} label="files read" icon="file-code" />
            <StatBlock value={threads.length} label="conversations" icon="message-square" />
            <StatBlock value={totals.pages} label="pages written" icon="book-open" />
          </div>
        )}
      </section>

      <Pipeline />

      {first ? (
        <section className="flex max-w-[720px] flex-col gap-4 rounded-xl border border-hot-edge bg-hot-wash/40 p-6">
          <div className="flex items-center gap-3">
            <IconTile icon="folder-plus" color="var(--hot)" tint size={40} />
            <div>
              <h2 className="text-[17px] font-semibold text-ink">Start with one codebase</h2>
              <p className="text-[13px] text-ink-mid">A GitHub, GitLab or Bitbucket URL, or a folder on this machine.</p>
            </div>
          </div>
          <ol className="flex flex-col gap-1.5 text-[13.5px] text-ink-mid">
            <li className="flex items-center gap-2"><Icon name="folder-plus" size={15} className="text-ink-dim" /> Add it. Nothing is read until you say so.</li>
            <li className="flex items-center gap-2"><Icon name="radar" size={15} className="text-ink-dim" /> Analyse it. One pass, a few minutes, pinned to the commit.</li>
            <li className="flex items-center gap-2"><Icon name="waypoints" size={15} className="text-ink-dim" /> Open the knowledge graph, ask a question, or write the docs.</li>
          </ol>
          {can('manager') ? (
            <button
              type="button"
              onClick={() => setCreating(true)}
              className="inline-flex items-center gap-2 self-start rounded-lg bg-hot px-4 py-2 text-[13.5px] font-medium text-on-hot transition-colors hover:bg-hot-ink"
            >
              <Icon name="folder-plus" size={16} /> Add a codebase
            </button>
          ) : (
            <p className="text-[12.5px] text-ink-dim">The manager role can add a codebase.</p>
          )}
        </section>
      ) : (
        <section className="flex flex-col gap-3">
          <header className="flex items-end justify-between gap-3">
            <h2 className="text-[17px] font-semibold text-ink">Codebases</h2>
            <Link to="/app/projects" className="flex items-center gap-1 text-[12.5px] text-ink-mid hover:text-ink">
              All of them <Icon name="chevron-right" size={14} />
            </Link>
          </header>
          {loading ? (
            <SkeletonPanel rows={4} />
          ) : (
            <div className="overflow-x-auto">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Codebase</th>
                    <th>Built with</th>
                    <th className="num">Files</th>
                    <th className="num">Pages</th>
                    <th>Reading</th>
                    <th>Last run</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {projects.slice(0, 8).map(p => {
                    const shares = languageShares(p.sources?.[0]?.config_json?.probe?.languages)
                    return (
                      <tr key={p.id} data-link onClick={() => navigate(`/app/projects/${p.id}`)}>
                        <td>
                          <Link
                            to={`/app/projects/${p.id}`}
                            onClick={e => e.stopPropagation()}
                            className="flex items-center gap-2.5"
                          >
                            <CodebaseMark project={p} size={18} />
                            <span>
                              <span className="block text-[14px] font-medium text-ink">{p.name}</span>
                              <span className="block max-w-[360px] truncate font-mono text-[11.5px] text-ink-dim">
                                {p.sources?.[0]?.url_or_path}
                              </span>
                            </span>
                          </Link>
                        </td>
                        <td>
                          <span className="flex items-center gap-2">
                            {shares.slice(0, 4).map(l => {
                              const b = languageBrand(l.name)
                              return b ? (
                                <span key={l.name} title={`${humanize(l.name)} ${Math.round(l.pct)}%`}>
                                  <BrandMark name={b} size={16} decorative />
                                </span>
                              ) : (
                                <span key={l.name} className="text-[12px] text-ink-dim">
                                  {l.name}
                                </span>
                              )
                            })}
                          </span>
                        </td>
                        <td className="num font-mono text-[12.5px] text-ink-mid">
                          {p.sources?.[0]?.config_json?.probe?.analysable_files?.toLocaleString() ?? '-'}
                        </td>
                        <td className="num font-mono text-[12.5px] text-ink-mid">{p.stats?.page_count ?? 0}</td>
                        <td>
                          <Readiness p={p} />
                        </td>
                        <td>
                          {p.latest_job ? <StatusBadge status={p.latest_job.status} /> : <span className="text-[12.5px] text-ink-dim">-</span>}
                        </td>
                        <td>
                          {p.apps_ready && (
                            <span className="flex justify-end gap-1">
                              <Link
                                to={`/app/projects/${p.id}/graph`}
                                onClick={e => e.stopPropagation()}
                                title="Open the knowledge graph"
                                aria-label={`Open the knowledge graph of ${p.name}`}
                                className="grid size-8 place-items-center rounded-md text-ink-dim transition-colors hover:bg-hover hover:text-ink"
                              >
                                <Icon name="waypoints" size={15} />
                              </Link>
                              <Link
                                to={`/app/chat?project=${p.id}&thread=new`}
                                onClick={e => e.stopPropagation()}
                                title="Ask about it"
                                aria-label={`Ask about ${p.name}`}
                                className="grid size-8 place-items-center rounded-md text-ink-dim transition-colors hover:bg-hover hover:text-ink"
                              >
                                <Icon name="message-square" size={15} />
                              </Link>
                            </span>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {!first && (
        <div className="grid grid-cols-1 gap-10 xl:grid-cols-2">
          <section className="flex flex-col gap-2">
            <header className="flex items-end justify-between gap-3">
              <h2 className="text-[17px] font-semibold text-ink">Recent conversations</h2>
              <Link to="/app/chat?thread=new" className="flex items-center gap-1 text-[12.5px] text-ink-mid hover:text-ink">
                <Icon name="plus" size={14} /> New
              </Link>
            </header>
            {threads.length === 0 ? (
              <p className="text-[13px] text-ink-dim">No conversations yet.</p>
            ) : (
              <div className="flex flex-col">
                {threads.slice(0, 6).map((t, i) => (
                  <ListRow
                    key={t.id}
                    to={`/app/chat?project=${t.project_id}&thread=${t.id}`}
                    lead={<IconTile icon="message-square" size={30} />}
                    title={t.title}
                    sub={`${t.project_name} · ${t.message_count} messages${t.last_message_at ? ` · ${relativeTime(t.last_message_at)}` : ''}`}
                    className="anim-rise"
                    style={stagger(i)}
                  />
                ))}
              </div>
            )}
          </section>

          <section className="flex flex-col gap-2">
            <header className="flex items-end justify-between gap-3">
              <h2 className="text-[17px] font-semibold text-ink">Recent runs</h2>
              <Link to="/app/jobs" className="flex items-center gap-1 text-[12.5px] text-ink-mid hover:text-ink">
                All runs <Icon name="chevron-right" size={14} />
              </Link>
            </header>
            {jobs.loading ? (
              <SkeletonPanel rows={4} />
            ) : !jobs.data?.length ? (
              <p className="text-[13px] text-ink-dim">Nothing has run yet.</p>
            ) : (
              <div className="flex flex-col">
                {jobs.data.slice(0, 6).map((j, i) => (
                  <ListRow
                    key={j.id}
                    to={`/app/projects/${j.project_id}/jobs/${j.id}`}
                    lead={<IconTile icon={j.job_type === 'analysis' ? 'radar' : 'pencil'} size={30} />}
                    title={`${humanize(j.job_type)} #${j.id}`}
                    sub={`${j.project_name ?? `codebase ${j.project_id}`} · ${relativeTime(j.created_at)}`}
                    trail={<StatusBadge status={j.status} />}
                    className="anim-rise"
                    style={stagger(i)}
                  />
                ))}
              </div>
            )}
          </section>
        </div>
      )}

      <NewProjectDialog
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={p => {
          setCreating(false)
          void refresh()
          navigate(`/app/projects/${p.id}`)
        }}
      />
    </div>
  )
}
