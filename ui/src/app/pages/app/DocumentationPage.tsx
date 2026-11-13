import { useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../../lib/api'
import { useAsync } from '../../lib/hooks'
import { countLabel, humanize, relativeTime, shortSha } from '../../lib/format'
import { Icon, type IconName } from '../../lib/icons'
import { APP_LOOKS } from '../../lib/kinds'
import { useFill } from '../../lib/motion'
import type { CodebaseDocs, Doc, Project, Publication } from '../../lib/types'
import { useProjectsList } from '../../projects-list'
import { CodebaseMark, IconTile, Pill, StatBlock } from '../../components/primitives'
import { EmptyState, ErrorState, SkeletonPanel } from '../../components/States'

/* ------------------------------------------------------------------ *
 * Documentation, across every codebase: a dashboard, not a shelf.
 *
 * The numbers first (how much is written, how much has fallen behind the
 * code, what is published), then one row per codebase. A row opens that
 * codebase's documentation site, where pages are read, written and
 * revised. Counted on the server (`/documentation/overview`), so the page
 * stays one request however many codebases there are.
 * ------------------------------------------------------------------ */

type Tab = 'codebases' | 'published' | 'documents'

const TABS: { id: Tab; label: string; icon: IconName }[] = [
  { id: 'codebases', label: 'Codebases', icon: 'folder-git-2' },
  { id: 'published', label: 'Published sites', icon: 'globe' },
  { id: 'documents', label: 'Single documents', icon: 'file-text' },
]

/** The four states a page can be in that a reader cares about, as bar segments. */
const SEGMENTS: { key: string; label: string; className: string; statuses: string[] }[] = [
  { key: 'written', label: 'Written', className: 'bg-ok', statuses: ['ready'] },
  { key: 'stale', label: 'Out of date', className: 'bg-warn', statuses: ['stale'] },
  { key: 'planned', label: 'Planned', className: 'bg-line-2', statuses: ['planned', 'generating'] },
  { key: 'failed', label: 'Failed', className: 'bg-bad', statuses: ['failed'] },
]

function count(pages: Record<string, number>, statuses: string[]) {
  return statuses.reduce((n, s) => n + (pages[s] ?? 0), 0)
}

function StateBar({ pages, total, thin = false }: { pages: Record<string, number>; total: number; thin?: boolean }) {
  const grow = useFill(100)
  return (
    <span className={`flex w-full overflow-hidden rounded-full bg-sunk ${thin ? 'h-1.5' : 'h-2.5'}`}>
      {total > 0 &&
        SEGMENTS.map(s => {
          const n = count(pages, s.statuses)
          return n ? (
            <span
              key={s.key}
              title={`${n} ${s.label.toLowerCase()}`}
              className={`block h-full transition-[width] duration-500 ${s.className}`}
              style={{ width: `${(n / total) * (grow / 100) * 100}%` }}
            />
          ) : null
        })}
    </span>
  )
}

function Published({ publications, projects }: { publications: Publication[]; projects: Project[] }) {
  if (!publications.length)
    return (
      <EmptyState
        title="Nothing published yet"
        body="Publishing gives a documentation site a URL other people can open. Do it from a codebase's site."
      />
    )
  return (
    <div className="flex flex-col gap-3">
      <div className="overflow-x-auto">
        <table className="tbl">
          <thead>
            <tr>
              <th>Site</th>
              <th>Codebase</th>
              <th>State</th>
              <th>Built from</th>
              <th>Published</th>
            </tr>
          </thead>
          <tbody>
            {publications.map(p => {
              const project = projects.find(x => x.id === p.project_id)
              return (
                <tr key={p.id}>
                  <td>
                    <a
                      href={`${window.location.origin}${p.url}`}
                      target="_blank"
                      rel="noreferrer"
                      className="flex items-center gap-2 font-mono text-[12.5px] text-ink hover:underline"
                    >
                      <Icon name="globe" size={14} className="text-ink-dim" />
                      {p.url}
                    </a>
                  </td>
                  <td>
                    <span className="flex items-center gap-2 text-[13px] text-ink-mid">
                      {project && <CodebaseMark project={project} size={14} />}
                      {p.project_name} {p.target !== 'live' && <span className="text-ink-dim">· {p.target}</span>}
                    </span>
                  </td>
                  <td>
                    <Pill
                      tone={p.status === 'live' ? (p.is_current === false ? 'warn' : 'good') : p.status === 'failed' ? 'bad' : 'plain'}
                      icon={p.status === 'live' ? 'globe' : p.status === 'building' ? 'loader' : p.status === 'failed' ? 'circle-x' : 'circle-dashed'}
                    >
                      {p.status === 'live' && p.is_current === false ? 'Live, behind the code' : humanize(p.status)}
                    </Pill>
                  </td>
                  <td className="font-mono text-[12.5px] text-ink-dim">
                    {p.current_build?.commit_sha ? shortSha(p.current_build.commit_sha) : '-'}
                  </td>
                  <td className="text-[12.5px] text-ink-dim">{p.published_at ? relativeTime(p.published_at) : '-'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <Link to="/app/published" className="flex items-center gap-1.5 self-start text-[13px] text-ink-mid hover:text-ink">
        <Icon name="settings" size={14} /> Manage publishing: republish, rotate the link, roll back, take down
      </Link>
    </div>
  )
}

function Documents({ docs, projects }: { docs: Doc[]; projects: Project[] }) {
  if (!docs.length)
    return (
      <EmptyState
        title="No single documents"
        body="Documents written in one go, before the documentation site existed, are kept here. New writing happens in a codebase's site."
      />
    )
  return (
    <div className="overflow-x-auto">
      <table className="tbl">
        <thead>
          <tr>
            <th>Document</th>
            <th>Codebase</th>
            <th>Type</th>
            <th>State</th>
            <th>Written</th>
          </tr>
        </thead>
        <tbody>
          {docs.map(d => {
            const project = projects.find(x => x.id === d.project_id)
            return (
              <tr key={d.id}>
                <td>
                  <Link to={`/app/documents/${d.id}`} className="flex items-center gap-2 text-[13.5px] font-medium text-ink hover:underline">
                    <Icon name="file-text" size={15} className="text-ink-dim" />
                    {d.title}
                  </Link>
                </td>
                <td>
                  <span className="flex items-center gap-2 text-[13px] text-ink-mid">
                    {project && <CodebaseMark project={project} size={14} />}
                    {project?.name ?? `codebase ${d.project_id}`}
                  </span>
                </td>
                <td className="text-[13px] text-ink-mid">{humanize(d.doc_type)}</td>
                <td>
                  <Pill tone={d.status === 'published' ? 'good' : 'plain'}>{humanize(d.status)}</Pill>
                </td>
                <td className="text-[12.5px] text-ink-dim">{relativeTime(d.created_at)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function Codebases({ projects, docs }: { projects: Project[]; docs: Map<number, CodebaseDocs> }) {
  const navigate = useNavigate()
  const [q, setQ] = useState('')
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return projects.filter(p => !needle || p.name.toLowerCase().includes(needle) || (p.sources?.[0]?.url_or_path ?? '').toLowerCase().includes(needle))
  }, [projects, q])

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex h-9 w-[min(420px,100%)] items-center gap-2 rounded-lg border border-line-2 bg-sunk px-3 focus-within:border-hot">
          <Icon name="search" size={15} className="text-ink-dim" />
          <input
            value={q}
            onChange={e => setQ(e.target.value)}
            placeholder="Find a codebase"
            aria-label="Find a codebase"
            className="min-w-0 flex-1 bg-transparent text-[13px] text-ink placeholder:text-ink-dim focus:outline-none"
          />
        </label>
        <span className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12.5px] text-ink-dim">
          {SEGMENTS.map(s => (
            <span key={s.key} className="flex items-center gap-1.5">
              <span className={`block size-2 rounded-full ${s.className}`} />
              {s.label}
            </span>
          ))}
        </span>
      </div>
      {shown.length === 0 ? (
        <p className="text-[13px] text-ink-dim">No codebase matches that.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="tbl">
            <thead>
              <tr>
                <th>Codebase</th>
                <th className="w-[26%]">Pages</th>
                <th className="num">Written</th>
                <th className="num">Out of date</th>
                <th className="num">Words</th>
                <th>Published</th>
                <th>Last written</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {shown.map(p => {
                const d = docs.get(p.id)
                const total = d?.total ?? 0
                const pct = total ? Math.round(((d?.written ?? 0) / total) * 100) : 0
                const stale = d?.pages.stale ?? 0
                const ready = p.apps_ready
                const open = () => navigate(ready ? `/app/projects/${p.id}/docs` : `/app/projects/${p.id}`)
                return (
                  <tr key={p.id} data-link onClick={open}>
                    <td>
                      <span className="flex items-center gap-3">
                        <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-sunk shadow-[inset_0_0_0_1px_var(--line-2)]">
                          <CodebaseMark project={p} size={18} />
                        </span>
                        <span className="min-w-0">
                          <span className="block text-[14px] font-medium text-ink">{p.name}</span>
                          <span className="block text-[12px] text-ink-dim">
                            {!ready
                              ? 'Not read yet, so nothing is planned'
                              : total
                                ? `${countLabel(total, 'page')} planned${d?.versions ? ` · ${countLabel(d.versions, 'version')}` : ''}`
                                : 'No pages planned yet'}
                          </span>
                        </span>
                      </span>
                    </td>
                    <td>
                      {total ? (
                        <span className="flex items-center gap-3">
                          <StateBar pages={d!.pages} total={total} thin />
                          <span className="w-10 shrink-0 text-right font-mono text-[12.5px] text-ink-mid tabular-nums">{pct}%</span>
                        </span>
                      ) : (
                        <span className="text-[12.5px] text-ink-dim">-</span>
                      )}
                    </td>
                    <td className="num font-mono text-[12.5px] text-ink-mid">{d?.written ?? 0}</td>
                    <td className={`num font-mono text-[12.5px] ${stale ? 'text-warn' : 'text-ink-dim'}`}>{stale}</td>
                    <td className="num font-mono text-[12.5px] text-ink-mid">{d?.words ? d.words.toLocaleString() : '-'}</td>
                    <td>
                      {d?.published === 'live' ? (
                        <Pill tone="good" icon="globe">Live</Pill>
                      ) : d?.published ? (
                        <Pill icon="circle-dashed">{humanize(d.published)}</Pill>
                      ) : (
                        <span className="text-[12.5px] text-ink-dim">No</span>
                      )}
                    </td>
                    <td className="text-[12.5px] whitespace-nowrap text-ink-dim">
                      {d?.last_written_at ? relativeTime(d.last_written_at) : '-'}
                    </td>
                    <td>
                      <span className="flex justify-end">
                        <span className="flex items-center gap-1 rounded-md px-2 py-1 text-[12.5px] font-medium text-ink-mid">
                          {ready ? 'Open' : 'Analyse'} <Icon name="chevron-right" size={14} />
                        </span>
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default function DocumentationPage() {
  const [params, setParams] = useSearchParams()
  const tab = (TABS.find(t => t.id === params.get('tab'))?.id ?? 'codebases') as Tab
  const { projects, loading } = useProjectsList()
  const overview = useAsync(sig => api.documentationOverview(sig), [])
  const publications = useAsync(sig => api.allPublications(sig), [])
  const singles = useAsync(() => api.documents(undefined, 200, 0), [])

  const docs = useMemo(() => new Map((overview.data ?? []).map(d => [d.project_id, d])), [overview.data])
  const totals = useMemo(() => {
    const pages: Record<string, number> = {}
    let total = 0
    let written = 0
    let words = 0
    for (const d of overview.data ?? []) {
      total += d.total
      written += d.written
      words += d.words
      for (const [k, v] of Object.entries(d.pages)) pages[k] = (pages[k] ?? 0) + v
    }
    const live = (overview.data ?? []).filter(d => d.published === 'live').length
    const withSite = (overview.data ?? []).filter(d => d.total > 0).length
    return { pages, total, written, words, live, withSite }
  }, [overview.data])

  const look = APP_LOOKS.documentation
  const counts: Record<Tab, number> = {
    codebases: projects.length,
    published: (publications.data ?? []).length,
    documents: (singles.data ?? []).length,
  }

  return (
    <div className="flex w-full flex-col gap-7 px-6 py-6">
      <header className="flex flex-wrap items-center gap-3.5">
        <IconTile icon={look.icon} color={look.color} tint size={44} />
        <div>
          <h1 className="text-[22px] leading-tight font-semibold text-ink">Documentation</h1>
          <p className="mt-1 text-[13px] text-ink-mid">
            What has been written about each codebase, what has fallen behind the code, and what is
            published. Open a codebase to read and write its documentation.
          </p>
        </div>
      </header>

      {overview.error && <ErrorState message={overview.error} onRetry={overview.reload} compact />}

      <section className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-x-6 border-y border-rule sm:grid-cols-3 lg:grid-cols-5">
          <StatBlock value={totals.withSite} label={`of ${countLabel(projects.length, 'codebase')} with a site`} icon="folder-git-2" />
          <StatBlock value={totals.written} label={`of ${countLabel(totals.total, 'planned page')} written`} icon="circle-check" />
          <StatBlock
            value={totals.pages.stale ?? 0}
            label="pages out of date"
            icon="triangle-alert"
            color={totals.pages.stale ? 'var(--warn)' : undefined}
          />
          <StatBlock value={totals.words} label="words written" icon="pencil" />
          <StatBlock value={totals.live} label={totals.live === 1 ? 'site published' : 'sites published'} icon="globe" />
        </div>
        {totals.total > 0 && (
          <div className="flex flex-col gap-2">
            <StateBar pages={totals.pages} total={totals.total} />
            <div className="flex flex-wrap gap-x-5 gap-y-1 text-[12.5px] text-ink-mid">
              {SEGMENTS.map(s => {
                const n = count(totals.pages, s.statuses)
                return (
                  <span key={s.key} className="flex items-center gap-1.5">
                    <span className={`block size-2 rounded-full ${s.className}`} />
                    {s.label}
                    <span className="font-mono text-ink tabular-nums">{n}</span>
                  </span>
                )
              })}
            </div>
          </div>
        )}
      </section>

      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap gap-1 self-start rounded-lg border border-rule bg-panel p-[3px]" role="tablist">
          {TABS.map(t => (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={tab === t.id}
              onClick={() => setParams(t.id === 'codebases' ? {} : { tab: t.id }, { replace: true })}
              className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[12.5px] font-medium transition-colors ${
                tab === t.id ? 'bg-sunk text-ink shadow-[inset_0_0_0_1px_var(--line-2)]' : 'text-ink-mid hover:text-ink'
              }`}
            >
              <Icon name={t.icon} size={14} />
              {t.label}
              <span className="font-mono text-[11.5px] text-ink-dim">{counts[t.id]}</span>
            </button>
          ))}
        </div>

        {tab === 'codebases' ? (
          loading || overview.loading ? (
            <SkeletonPanel rows={6} />
          ) : projects.length === 0 ? (
            <EmptyState
              title="No codebases yet"
              body="Add and analyse a codebase, and its documentation site is planned from the reading."
              action={
                <Link to="/app/projects" className="text-hot-ink hover:underline">
                  Go to codebases
                </Link>
              }
            />
          ) : (
            <Codebases projects={projects} docs={docs} />
          )
        ) : tab === 'published' ? (
          publications.loading ? <SkeletonPanel rows={3} /> : <Published publications={publications.data ?? []} projects={projects} />
        ) : singles.loading ? (
          <SkeletonPanel rows={3} />
        ) : (
          <Documents docs={singles.data ?? []} projects={projects} />
        )}
      </div>
    </div>
  )
}
