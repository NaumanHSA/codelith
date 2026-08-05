import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../../lib/api'
import { useAsync } from '../../lib/hooks'
import { useAuth } from '../../auth'
import { useRunningJobs } from '../../running-jobs'
import { countLabel, humanize, languageShares, relativeTime, shortSha } from '../../lib/format'
import { confidenceLabel, docTypeMeta, DOC_TYPES, OUTPUT_FORMATS } from '../../lib/docTypes'
import type { DocType, Job, KnowledgeBase, OutputFormat, Project } from '../../lib/types'
import { Button, Chip, Eyebrow, Meter, PageHead, Panel, Stat, StatusBadge } from '../../components/ui'
import { EmptyState, ErrorState, SkeletonPanel } from '../../components/States'
import KnowledgeMap from '../../components/projects/KnowledgeMap'

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

function ComposePanel({
  project,
  kb,
  onStarted,
}: {
  project: Project
  kb: KnowledgeBase
  onStarted: (job: Job) => void
}) {
  const suggested = kb.suggested_doc_types ?? []
  const suggestedTypes = suggested.map(s => s.doc_type)
  const others = Object.keys(DOC_TYPES).filter(t => !suggestedTypes.includes(t)) as DocType[]

  // Pre-select what the analysis is confident about — the picker should
  // open on a sensible plan, not an empty form.
  const [picked, setPicked] = useState<DocType[]>(
    suggested.filter(s => s.confidence >= 0.6).map(s => s.doc_type),
  )
  const [formats, setFormats] = useState<OutputFormat[]>(['markdown'])
  const [review, setReview] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const toggle = (t: DocType) =>
    setPicked(p => (p.includes(t) ? p.filter(x => x !== t) : [...p, t]))

  const minutes = picked.reduce((s, t) => s + docTypeMeta(t).estMinutes, 0)

  const start = async () => {
    if (!picked.length || !formats.length) return
    setBusy(true)
    setError(null)
    try {
      const job = await api.compose(project.id, {
        doc_types: picked,
        output_formats: formats,
        human_review: review,
        kb_id: kb.knowledge_base.id,
      })
      onStarted(job)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not start composition.')
      setBusy(false)
    }
  }

  const card = (t: DocType, confidence?: number, reason?: string) => {
    const meta = docTypeMeta(t)
    const on = picked.includes(t)
    return (
      <button
        key={t}
        onClick={() => toggle(t)}
        aria-pressed={on}
        className={`plate plate-lift flex flex-col text-left ${on ? 'plate-hot' : ''}`}
      >
        <span className="flex items-center gap-2 border-b border-rule px-2.5 py-1.5">
          <span
            className={`block size-[9px] shrink-0 rotate-45 border ${
              on ? 'border-hot bg-hot' : 'border-ink-dim bg-transparent'
            }`}
          />
          <span className="min-w-0 flex-1 truncate text-[12px] font-bold text-ink">
            {meta.title}
          </span>
          {confidence != null && (
            <span className="tag shrink-0 text-ink-dim">{confidenceLabel(confidence)}</span>
          )}
        </span>
        <span className="flex-1 px-2.5 py-2">
          <span className="block font-sans text-[11.5px] leading-relaxed text-ink-mid">
            {reason || meta.blurb}
          </span>
          <span className="mt-1.5 flex flex-wrap gap-1">
            {meta.contains.map(c => (
              <span key={c} className="tag border border-rule px-1 py-px text-ink-dim">
                {c}
              </span>
            ))}
          </span>
        </span>
        {confidence != null && (
          <span className="border-t border-rule px-2.5 py-1.5">
            <Meter pct={confidence * 100} segments={16} />
          </span>
        )}
      </button>
    )
  }

  return (
    <Panel
      title="Compose documentation"
      action={<span className="tag text-ink-dim">{countLabel(picked.length, 'doc')} selected</span>}
    >
      <div className="p-3">
        {error && <ErrorState message={error} compact />}

        {suggested.length > 0 && (
          <>
            <Eyebrow>Suggested by the analysis</Eyebrow>
            <div className="mt-2 mb-4 grid grid-cols-1 gap-2 md:grid-cols-2">
              {suggested.map(s => card(s.doc_type, s.confidence, s.reason))}
            </div>
          </>
        )}

        {others.length > 0 && (
          <>
            <Eyebrow>Also available</Eyebrow>
            <div className="mt-2 grid grid-cols-1 gap-2 md:grid-cols-2">
              {others.map(t => card(t))}
            </div>
          </>
        )}

        <div className="mt-4 grid grid-cols-1 gap-3 border-t border-rule pt-3 sm:grid-cols-2">
          <div>
            <Eyebrow>Output formats</Eyebrow>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {OUTPUT_FORMATS.map(f => (
                <Chip
                  key={f.value}
                  active={formats.includes(f.value)}
                  title={f.note}
                  onClick={() =>
                    setFormats(p =>
                      p.includes(f.value) ? p.filter(x => x !== f.value) : [...p, f.value],
                    )
                  }
                >
                  {f.label}
                </Chip>
              ))}
            </div>
          </div>
          <div>
            <Eyebrow>Before publishing</Eyebrow>
            <label className="mt-1.5 flex cursor-pointer items-start gap-2">
              <input
                type="checkbox"
                checked={review}
                onChange={e => setReview(e.target.checked)}
                className="mt-[3px] size-3 accent-[var(--hot)]"
              />
              <span className="font-sans text-[11.5px] leading-relaxed text-ink-mid">
                Pause for human review.{' '}
                <span className="text-warn">
                  A paused job cannot be resumed from here yet — it will sit at
                  awaiting review.
                </span>
              </span>
            </label>
          </div>
        </div>
      </div>

      <footer className="flex flex-wrap items-center gap-2 border-t border-rule bg-sunk/60 px-3 py-2.5">
        <span className="tag text-ink-dim">
          {picked.length ? `about ${minutes} min on a local model` : 'pick at least one document'}
        </span>
        <Button
          variant="hot"
          className="ml-auto"
          disabled={!picked.length || !formats.length || busy}
          onClick={start}
        >
          {busy ? 'starting…' : 'Compose →'}
        </Button>
      </footer>
    </Panel>
  )
}

export default function ProjectDetailPage() {
  const { projectId } = useParams()
  const id = Number(projectId)
  const navigate = useNavigate()
  const { can } = useAuth()
  const { track } = useRunningJobs()

  const project = useAsync(() => api.project(id), [id])
  const kb = useAsync(s => api.knowledgeBase(id, s), [id])
  const jobs = useAsync(() => api.projectJobs(id, 10, 0), [id])

  const [analysing, setAnalysing] = useState(false)
  const [analyseError, setAnalyseError] = useState<string | null>(null)

  const canRun = can('manager')

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
              {!neverAnalysed && (
                <Button variant="ghost" onClick={() => startAnalysis(true)} disabled={analysing}>
                  ↻ Re-analyse
                </Button>
              )}
              {neverAnalysed && (
                <Button variant="hot" onClick={() => startAnalysis(false)} disabled={analysing}>
                  {analysing ? 'starting…' : 'Analyse repository →'}
                </Button>
              )}
            </div>
          ) : null
        }
      />

      {analyseError && <ErrorState message={analyseError} compact />}

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
                  <Stat k="indexed" v={base.stats?.indexed_chunks?.toLocaleString() ?? '—'} />
                  <Stat k="commit" v={shortSha(base.commit_sha)} />
                </div>
                <div className="border-t border-rule">
                  <KnowledgeMap kb={kb.data} />
                </div>
              </Panel>

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

                  {kb.data.narrative_topics?.length ? (
                    <Panel title="What this codebase talks about">
                      <div className="flex flex-wrap gap-1 p-2.5">
                        {kb.data.narrative_topics.slice(0, 20).map(t => (
                          <span key={t} className="tag border border-hot-edge bg-hot-wash px-1.5 py-0.5 text-hot-ink">
                            {t}
                          </span>
                        ))}
                      </div>
                    </Panel>
                  ) : null}
                </div>
              )}

              {canRun && base.status !== 'failed' && (
                <ComposePanel
                  project={p}
                  kb={kb.data}
                  onStarted={job => {
                    track(job, p.name)
                    navigate(`/app/projects/${p.id}/jobs/${job.id}`)
                  }}
                />
              )}
            </>
          )}
        </div>

        {/* rail */}
        <div className="flex flex-col gap-3">
          <SourcePanel project={p} />

          <Panel
            title="Recent jobs"
            action={<span className="tag text-ink-dim">{p.stats?.job_count ?? 0} total</span>}
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
                      <span className="tag block text-ink-dim">{relativeTime(j.created_at)}</span>
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
              <span className="tag mt-1 block text-ink-dim">written for this project</span>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  )
}
