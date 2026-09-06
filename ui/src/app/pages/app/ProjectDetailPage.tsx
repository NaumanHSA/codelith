import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../../lib/api'
import { useAsync } from '../../lib/hooks'
import { useAuth } from '../../auth'
import { useRunningJobs } from '../../running-jobs'
import { countLabel, humanize, languageShares, relativeTime, shortSha } from '../../lib/format'
import type { Project } from '../../lib/types'
import { Button, Meter, PageHead, Panel, Stat, StatusBadge } from '../../components/ui'
import { EmptyState, ErrorState, SkeletonPanel } from '../../components/States'
import Preflight from '../../components/projects/Preflight'
import ReanalyseDialog from '../../components/projects/ReanalyseDialog'
import KnowledgeMap from '../../components/projects/KnowledgeMap'
import ArchitectureMap from '../../components/projects/ArchitectureMap'
import NarrativeReader from '../../components/projects/NarrativeReader'
import ConfirmDelete from '../../components/ConfirmDelete'
import AppGrid from '../../components/projects/AppGrid'
import { coverage, describeJobScope } from '../../lib/site'

/* ------------------------------------------------------------------ *
 * A project has two lives: before analysis and after.
 *
 * GET /knowledge-base resolves to null when a project has never been
 * analysed — that null is the signal, not an error, and it decides
 * which of the two screens below is shown.
 * ------------------------------------------------------------------ */

function SourcePanel({ project }: { project: Project }) {
  const source = project.sources?.[0]
  const probe = source?.config_json?.probe
  const shares = languageShares(probe?.languages)

  return (
    <Panel title="Source" action={<span className="tag text-ink-dim">{source?.source_type}</span>}>
      <div className="px-3 py-2.5">
        <a
          href={source?.source_type === 'local' ? undefined : source?.url_or_path}
          target="_blank"
          rel="noreferrer"
          className="block truncate text-[12px] text-hot-ink hover:underline"
        >
          {source?.url_or_path ?? 'No source attached.'}
        </a>
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
          <span className="tag text-ink-dim">branch {source?.branch ?? 'default'}</span>
          <span className="tag text-ink-dim">sha {shortSha(probe?.commit_sha)}</span>
          <span className="tag text-ink-dim">
            {probe?.file_count != null ? countLabel(probe.file_count, 'file') : 'unmeasured'}
          </span>
        </div>
      </div>
      {shares.length > 0 && (
        <div className="border-t border-rule px-3 py-2.5">
          <div className="flex h-[6px] w-full overflow-hidden border border-rule">
            {shares.slice(0, 6).map((l, i) => (
              <span
                key={l.name}
                title={`${l.name} · ${countLabel(l.count, 'file')}`}
                style={{ width: `${l.pct}%`, opacity: 1 - i * 0.13 }}
                className="block bg-hot"
              />
            ))}
          </div>
          <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1">
            {shares.slice(0, 5).map(l => (
              <span key={l.name} className="tag text-ink-dim">
                {l.name} {Math.round(l.pct)}%
              </span>
            ))}
          </div>
        </div>
      )}
    </Panel>
  )
}

/**
 * The bridge to the compose page.
 *
 * Deliberately not a picker. What to write next is a decision about the state of
 * the documentation — which pages are missing, which have gone out of date — and
 * that needs a screen of its own, not a form stapled to the bottom of a status page.
 */
/**
 * How much of the documentation exists, shown inside its feature card.
 *
 * This used to be a panel of its own titled "Documentation", sitting where the
 * project's one outcome went. It is a detail of one feature among several now, so it
 * lives in that feature's card — and the "Read" link only appears once there is
 * something written to read.
 */
function DocumentationProgress({ projectId }: { projectId: number }) {
  const navigate = useNavigate()
  const { data: site } = useAsync(s => api.site(projectId, null, s), [projectId])
  const c = coverage(site ?? null)
  const outstanding = c.planned + c.stale + c.failed
  const planned = c.total - c.orphaned
  const written = !!site && site.sections.length > 0

  return (
    <span className="block">
      <span className="block font-sans text-[11.5px] text-ink-mid">
        {!written
          ? 'No pages planned yet.'
          : outstanding
            ? `${countLabel(outstanding, 'page')} still to write of ${planned} planned.`
            : 'Every planned page is written and current.'}
      </span>
      {written && (
        <span className="mt-1.5 flex items-center gap-2">
          <Meter pct={c.pct} segments={18} />
          <span className="tag text-ink-dim">{c.pct}% written</span>
          {/* A button, not a Link: this sits inside the app card, which is itself
              a Link, and an anchor inside an anchor is invalid HTML — React warns
              and the browser is free to reparent it, which breaks both. */}
          <button
            type="button"
            onClick={e => {
              e.preventDefault()
              e.stopPropagation()
              navigate(`/app/projects/${projectId}/docs`)
            }}
            className="tag ml-auto text-ink-dim underline-offset-2 hover:text-hot-ink hover:underline"
          >
            read
          </button>
        </span>
      )}
    </span>
  )
}

/** A labelled row of short facts. Used for layers, patterns and the stack. */
function Facts({ label, items, hot }: { label: string; items: string[]; hot?: boolean }) {
  return (
    <div className="mb-1.5 flex flex-wrap items-baseline gap-x-2 gap-y-1 last:mb-0">
      <span className="tag w-[74px] shrink-0 text-ink-dim">{label}</span>
      {items.map(item => (
        <span
          key={item}
          className={`border px-1.5 py-[2px] text-[10.5px] ${
            hot ? 'border-hot-edge bg-hot-wash text-hot-ink' : 'border-rule text-ink-mid'
          }`}
        >
          {item}
        </span>
      ))}
    </div>
  )
}

export default function ProjectDetailPage() {
  const { projectId } = useParams()
  const id = Number(projectId)
  const navigate = useNavigate()
  const { can } = useAuth()
  const { track } = useRunningJobs()

  const project = useAsync(() => api.project(id), [id])
  const arch = useAsync(sig => api.architecture(id, sig), [id])
  const narratives = useAsync(sig => api.narratives(id, sig), [id])
  const kb = useAsync(s => api.knowledgeBase(id, s), [id])
  const jobs = useAsync(() => api.projectJobs(id, 10, 0), [id])
  const features = useAsync(sig => api.projectApps(id, sig), [id])

  const [analysing, setAnalysing] = useState(false)
  const [analyseError, setAnalyseError] = useState<string | null>(null)
  const [doomed, setDoomed] = useState(false)

  const canRun = can('manager')
  const [confirmingReanalyse, setConfirmingReanalyse] = useState(false)

  const startAnalysis = async (force: boolean) => {
    setAnalysing(true)
    setAnalyseError(null)
    try {
      const job = await api.analyze(id, force)
      track(job, project.data?.name)
      navigate(`/app/projects/${id}/jobs/${job.id}`)
    } catch (e) {
      setAnalyseError(e instanceof ApiError ? e.message : 'Could not start analysis.')
      setAnalysing(false)
      setConfirmingReanalyse(false)
    }
  }

  if (project.loading) {
    return (
      <div className="mx-auto max-w-[1180px] p-5">
        <SkeletonPanel rows={6} />
      </div>
    )
  }

  if (project.error || !project.data) {
    return (
      <div className="mx-auto max-w-[1180px] p-5">
        <ErrorState message={project.error ?? 'Project not found.'} onRetry={project.reload} />
      </div>
    )
  }

  const p = project.data
  const base = kb.data?.knowledge_base
  const neverAnalysed = !kb.loading && !kb.error && !kb.data
  const stale = base?.status === 'stale'

  return (
    <div className="mx-auto max-w-[1180px] p-5">
      <PageHead
        index={String(p.id).padStart(2, '0')}
        title={p.name}
        sub={p.description || 'No description.'}
        right={
          canRun ? (
            <div className="flex gap-2">
              {/* Asks what it would achieve first. A re-analysis of a repository
                  that has not moved costs the same as a real one and stores the same
                  reading, so it is worth one dialog to find out. */}
              {!neverAnalysed && (
                <Button
                  variant="ghost"
                  onClick={() => setConfirmingReanalyse(true)}
                  disabled={analysing}
                >
                  ↻ Re-analyse
                </Button>
              )}
              {neverAnalysed && (
                <Button variant="hot" onClick={() => startAnalysis(false)} disabled={analysing}>
                  {analysing ? 'starting…' : 'Analyse repository →'}
                </Button>
              )}
              <Button variant="danger" onClick={() => setDoomed(true)} title="Delete this project">
                Delete
              </Button>
            </div>
          ) : null
        }
      />

      <ReanalyseDialog
        open={confirmingReanalyse}
        projectId={id}
        starting={analysing}
        onClose={() => setConfirmingReanalyse(false)}
        onConfirm={() => void startAnalysis(true)}
      />

      <ConfirmDelete
        open={doomed}
        onClose={() => setDoomed(false)}
        onConfirm={async () => {
          await api.deleteProject(id)
          navigate('/app/projects')
        }}
        title={`Delete ${p.name}`}
        actionLabel="Delete everything"
        confirmText={p.name}
        body={
          <>
            <p>
              This removes the project and everything derived from it: its knowledge
              base, every job, every document, and the whole documentation site with
              its pages and versions.
            </p>
            <p className="mt-2">The repository is untouched. Nothing here can be recovered.</p>
          </>
        }
      />

      {analyseError && <ErrorState message={analyseError} compact />}

      {!!features.data?.length && (
        <div className="mb-3">
          <AppGrid
            features={features.data}
            extras={{ documentation: <DocumentationProgress projectId={id} /> }}
          />
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-[1fr_320px]">
        <div className="flex min-w-0 flex-col gap-3">
          {kb.loading && <SkeletonPanel rows={5} />}

          {kb.error && <ErrorState message={kb.error} onRetry={kb.reload} />}

          {neverAnalysed && (
            <EmptyState
              title="This repository has not been read yet"
              body="Analysis clones the source, walks every file, extracts modules, routes, dependencies and environment variables, then builds the knowledge base that every document is written from. Nothing is generated until you choose what to write."
              action={
                canRun ? (
                  <Button variant="hot" onClick={() => startAnalysis(false)} disabled={analysing}>
                    {analysing ? 'starting…' : 'Analyse repository →'}
                  </Button>
                ) : (
                  <span className="tag text-ink-dim">the manager role can start an analysis</span>
                )
              }
            />
          )}

          {kb.data && base && (
            <>
              {stale && (
                <div className="flex flex-wrap items-center gap-2 border border-warn/40 bg-warn-wash px-3 py-2">
                  <span className="tag text-warn">knowledge base is stale</span>
                  <span className="font-sans text-[11.5px] text-ink-mid">
                    The repository moved on since {shortSha(base.commit_sha)}.
                  </span>
                  {canRun && (
                    <Button variant="ghost" className="ml-auto" onClick={() => startAnalysis(true)}>
                      ↻ Re-analyse
                    </Button>
                  )}
                </div>
              )}

              {base.error_message && (
                <div className="border border-bad/35 bg-bad-wash px-3 py-2.5">
                  <span className="tag text-bad">analysis reported a problem</span>
                  <p className="mt-1 font-sans text-[12px] text-ink">{base.error_message}</p>
                </div>
              )}

              <Panel
                title="Knowledge base"
                action={<StatusBadge status={base.status} />}
              >
                <div className="grid grid-cols-2 gap-px bg-rule sm:grid-cols-4">
                  <Stat k="modules" v={kb.data.module_count} hot />
                  <Stat k="entities" v={kb.data.entity_count} />
                  <Stat k="indexed" v={base.stats?.indexed_chunks?.toLocaleString() ?? '-'} />
                  <Stat k="commit" v={shortSha(base.commit_sha)} />
                </div>
                <div className="border-t border-rule">
                  <KnowledgeMap kb={kb.data} />
                </div>
              </Panel>

              {/* Above the counters and the role plot, because it is the only thing
                  here that answers "what is this project" rather than "how big is
                  it". Analysis has written this on every run and nothing has ever
                  read it. */}
              {arch.data?.available && (
                <Panel
                  title="Architecture"
                  action={
                    <span className="tag text-ink-dim">
                      as analysed at {shortSha(arch.data.commit_sha)}
                    </span>
                  }
                >
                  <ArchitectureMap arch={arch.data} />

                  {(arch.data.tech_stack.frameworks.length > 0 ||
                    arch.data.patterns.length > 0 ||
                    arch.data.layers.length > 0) && (
                    <div className="border-t border-rule px-3 py-2.5">
                      {/* Single-word facts that each cost a quality-tier call to
                          derive and reached nobody until now. */}
                      {arch.data.layers.length > 0 && (
                        <Facts label="layers" items={arch.data.layers.map(l => l.name)} />
                      )}
                      {arch.data.patterns.length > 0 && (
                        <Facts label="patterns" items={arch.data.patterns} hot />
                      )}
                      {arch.data.tech_stack.frameworks.length > 0 && (
                        <Facts label="frameworks" items={arch.data.tech_stack.frameworks} />
                      )}
                      {arch.data.tech_stack.infra.length > 0 && (
                        <Facts label="infra" items={arch.data.tech_stack.infra} />
                      )}
                      {arch.data.tech_stack.databases.length > 0 && (
                        <Facts label="data stores" items={arch.data.tech_stack.databases} />
                      )}
                    </div>
                  )}
                </Panel>
              )}

              {/* The chips that used to sit at the bottom of this page named
                  twelve topics and showed none of the three thousand words
                  behind them. Composition read this prose from day one; a
                  person could not. */}
              {narratives.data?.available && (
                <Panel
                  title="What analysis wrote"
                  action={
                    <span className="tag text-ink-dim">
                      {narratives.data.narratives.length} topics ·{' '}
                      {narratives.data.narratives
                        .reduce((n, x) => n + x.words, 0)
                        .toLocaleString()}{' '}
                      words
                    </span>
                  }
                >
                  <NarrativeReader data={narratives.data} />
                </Panel>
              )}

              {/* Directly under the knowledge base, because it is the one thing
                  on this page you ask *before* doing something rather than
                  after. */}
              <Preflight projectId={id} />

              {(kb.data.sample_routes?.length ||
                kb.data.key_dependencies?.length ||
                kb.data.entrypoints?.length) && (
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  {kb.data.entrypoints?.length ? (
                    <Panel title="Entrypoints">
                      <ul className="p-2.5">
                        {kb.data.entrypoints.slice(0, 8).map(e => (
                          <li key={e} className="truncate py-[3px] text-[11.5px] text-ink-mid">
                            <span className="text-hot-ink">→</span> {e}
                          </li>
                        ))}
                      </ul>
                    </Panel>
                  ) : null}

                  {kb.data.key_dependencies?.length ? (
                    <Panel title="Key dependencies">
                      <div className="flex flex-wrap gap-1 p-2.5">
                        {kb.data.key_dependencies.slice(0, 24).map(d => (
                          <span
                            key={d}
                            className="tag border border-rule bg-sunk/60 px-1.5 py-0.5 text-ink-mid"
                          >
                            {d}
                          </span>
                        ))}
                      </div>
                    </Panel>
                  ) : null}

                  {kb.data.sample_routes?.length ? (
                    <Panel title="Surface" action={<span className="tag text-ink-dim">sample</span>}>
                      <ul className="divide-y divide-rule">
                        {kb.data.sample_routes.slice(0, 10).map((r, i) => (
                          <li key={`${r.name}-${i}`} className="flex gap-2 px-2.5 py-1.5">
                            <span className="tag w-[74px] shrink-0 text-ink-dim">
                              {humanize(r.kind)}
                            </span>
                            <span className="min-w-0 flex-1 truncate text-[11.5px] text-ink">
                              {r.name}
                            </span>
                            {r.detail && (
                              <span className="hidden truncate text-[11px] text-ink-dim sm:block">
                                {r.detail}
                              </span>
                            )}
                          </li>
                        ))}
                      </ul>
                    </Panel>
                  ) : null}
                </div>
              )}

            </>
          )}
        </div>

        {/* rail */}
        <div className="flex flex-col gap-3">
          <SourcePanel project={p} />

          <Panel
            title="Recent jobs"
            action={
              <span className="flex items-center gap-2">
                <span className="tag text-ink-dim">{p.stats?.job_count ?? 0} total</span>
                {/* Ten rows is a summary, not the record. Everything that ever ran —
                    including the failures worth looking at — lives on the jobs page. */}
                <Link
                  to={`/app/jobs?project=${p.id}`}
                  className="tag text-hot-ink transition-colors hover:underline"
                >
                  all →
                </Link>
              </span>
            }
          >
            {jobs.loading && <SkeletonPanel rows={3} />}
            {!jobs.loading && !jobs.data?.length && (
              <p className="px-3 py-3 text-[11.5px] text-ink-dim">Nothing has run yet.</p>
            )}
            <ul className="divide-y divide-rule">
              {(jobs.data ?? []).map(j => (
                <li key={j.id}>
                  <Link
                    to={`/app/projects/${p.id}/jobs/${j.id}`}
                    className="flex items-center gap-2 px-3 py-2 transition-colors hover:bg-hot-wash/60"
                  >
                    <span className="tag w-8 shrink-0 text-ink-dim">#{j.id}</span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[11.5px] font-semibold text-ink">
                        {humanize(j.job_type)}
                      </span>
                      <span className="tag block truncate text-ink-dim">
                        {describeJobScope(j) ?? relativeTime(j.created_at)}
                      </span>
                    </span>
                    <StatusBadge status={j.status} />
                  </Link>
                </li>
              ))}
            </ul>
          </Panel>

          <Panel
            title="Documents"
            action={
              <Link to="/app/documents" className="tag text-hot-ink hover:underline">
                all →
              </Link>
            }
          >
            <div className="px-3 py-3">
              <span className="block text-[22px] leading-none font-bold text-ink">
                {p.stats?.doc_count ?? 0}
              </span>
              <span className="tag mt-1 block text-ink-dim">
                single documents, written before the site
              </span>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  )
}
