import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../../lib/api'
import { useJob, useJobLogs } from '../../lib/hooks'
import { useAuth } from '../../auth'
import { useRunningJobs } from '../../running-jobs'
import {
  agentLabel, elapsedSeconds, formatDateTime, formatDuration, humanize, shortSha,
} from '../../lib/format'
import { confidenceLabel, docTypeTitle } from '../../lib/docTypes'
import { progressStages, stagePurpose } from '../../lib/narrate'
import { describeJobScope } from '../../lib/site'
import { isTerminal, type Doc, type JobLog, type KnowledgeBase, type Site } from '../../lib/types'
import { Button, PageHead, Panel, Stat, StatusBadge } from '../../components/ui'
import { ErrorState, SkeletonPanel } from '../../components/States'
import PipelineTree from '../../components/jobs/PipelineTree'
import JobTargets from '../../components/jobs/JobTargets'

const LEVEL_COLOR: Record<string, string> = {
  error: 'text-[var(--bad)]',
  warning: 'text-[var(--warn)]',
  debug: 'text-term-dim',
  info: 'text-term-text',
}

function LogStream({ logs, streaming }: { logs: JobLog[]; streaming: boolean }) {
  const box = useRef<HTMLDivElement>(null)
  const [stick, setStick] = useState(true)

  useEffect(() => {
    if (!stick || !box.current) return
    box.current.scrollTop = box.current.scrollHeight
  }, [logs, stick])

  return (
    <div className="border border-term-rule bg-term">
      <header className="flex items-center gap-2 border-b border-term-rule px-3 py-1.5">
        <span className="flex gap-1">
          {['var(--bad)', 'var(--warn)', 'var(--term-ok)'].map(c => (
            <span key={c} className="block size-[7px] rounded-full" style={{ background: c }} />
          ))}
        </span>
        <span className="tag text-term-dim">job log</span>
        <span className="ml-auto flex items-center gap-2">
          {streaming && (
            <span className="tag flex items-center gap-1.5 text-term-ok">
              <span className="anim-blink block size-[6px] rounded-full bg-term-ok" /> live
            </span>
          )}
          <button
            onClick={() => setStick(s => !s)}
            className={`tag transition-colors ${stick ? 'text-term-ok' : 'text-term-dim hover:text-term-text'}`}
          >
            {stick ? 'following' : 'paused'}
          </button>
        </span>
      </header>
      <div
        ref={box}
        onScroll={e => {
          const el = e.currentTarget
          // Turning "follow" off the moment the reader scrolls up is the
          // only behaviour that does not fight them.
          const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24
          if (atBottom !== stick) setStick(atBottom)
        }}
        className="max-h-[340px] min-h-[160px] overflow-y-auto px-3 py-2 text-[11px] leading-[1.55]"
      >
        {logs.length === 0 && <p className="text-term-dim">Waiting for the first line…</p>}
        {logs.map(l => (
          <div key={l.id} className="flex gap-2">
            <span className="shrink-0 text-term-dim tabular-nums">
              {new Date(l.timestamp).toLocaleTimeString([], { hour12: false })}
            </span>
            {l.agent && (
              <span className="hidden w-[110px] shrink-0 truncate text-[var(--hot)] sm:block">
                {agentLabel(l.agent)}
              </span>
            )}
            <span className={`min-w-0 flex-1 break-words ${LEVEL_COLOR[l.level] ?? 'text-term-text'}`}>
              {l.message}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function JobProgressPage() {
  const { projectId, jobId } = useParams()
  const pid = Number(projectId)
  const id = Number(jobId)
  const navigate = useNavigate()
  const { can } = useAuth()
  const { untrack } = useRunningJobs()

  const { job, error, loading, setJob } = useJob(Number.isFinite(id) ? id : null)
  const live = job ? !isTerminal(job.status) : false
  const { logs, streaming } = useJobLogs(Number.isFinite(id) ? id : null, live)

  const [cancelling, setCancelling] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [docs, setDocs] = useState<Doc[]>([])
  const [site, setSite] = useState<Site | null>(null)
  // Null until known. A stage must never be drawn as enabled on a guess — showing
  // optional work as merely queued is the failure this is here to prevent.
  const [diagramsEnabled, setDiagramsEnabled] = useState<boolean | null>(null)
  const [kb, setKb] = useState<KnowledgeBase | null>(null)

  // Documents only exist once the job finished writing them.
  useEffect(() => {
    if (job?.status !== 'completed' || job.job_type !== 'composition') return
    api
      .documents(pid, 50, 0)
      .then(all => setDocs(all.filter(d => d.job_id === job.id)))
      .catch(() => setDocs([]))
  }, [job?.status, job?.id, job?.job_type, pid])

  // An analysis run produces a knowledge base rather than documents. Without
  // this the run just stops, and the user is left on a finished page with no
  // idea that choosing what to write is the next step.
  useEffect(() => {
    if (job?.status !== 'completed' || job.job_type !== 'analysis') return
    api
      .knowledgeBase(pid)
      .then(setKb)
      .catch(() => setKb(null))
  }, [job?.status, job?.id, job?.job_type, pid])

  // The target list needs page titles and — while the run is live — each page's
  // current status, so this follows the job rather than being fetched once. It is one
  // request per poll against a map that is already cached client-side.
  const isComposition = job?.job_type === 'composition'
  useEffect(() => {
    if (!isComposition || !Number.isFinite(pid)) return
    let alive = true
    api
      .site(pid, null)
      .then(s => alive && setSite(s))
      .catch(() => alive && setSite(null))
    return () => {
      alive = false
    }
  }, [pid, isComposition, job?.status, (job?.steps ?? []).length])

  useEffect(() => {
    let alive = true
    api
      .features()
      .then(f => alive && setDiagramsEnabled(f.diagrams_enabled))
      .catch(() => alive && setDiagramsEnabled(null))
    return () => {
      alive = false
    }
  }, [])

  // `gate` never reports a step, so it must not sit in the denominator —
  // counting it left a finished composition showing 8/9 and 89%.
  const stages = job ? progressStages(job.job_type) : []
  const done = (job?.steps ?? []).filter(
    s => s.status === 'completed' && stages.includes(s.name),
  ).length
  const pct = stages.length ? Math.min(100, (done / stages.length) * 100) : 0
  const running = (job?.steps ?? []).find(s => s.status === 'running')

  const elapsed = useMemo(() => {
    if (!job) return 0
    return elapsedSeconds(job.started_at ?? job.created_at, job.completed_at) ?? 0
  }, [job])

  const cancel = async () => {
    setCancelling(true)
    setActionError(null)
    try {
      const next = await api.cancelJob(id)
      setJob(next)
      untrack(id)
      setConfirming(false)
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : 'Could not cancel the job.')
    } finally {
      setCancelling(false)
    }
  }

  if (loading && !job) {
    return (
      <div className="mx-auto max-w-[1100px] p-5">
        <SkeletonPanel rows={7} />
      </div>
    )
  }

  if (!job) {
    return (
      <div className="mx-auto max-w-[1100px] p-5">
        <ErrorState message={error ?? 'Job not found.'} />
      </div>
    )
  }

  const scope = describeJobScope(job)

  return (
    <div className="mx-auto max-w-[1100px] p-5">
      <PageHead
        index={`#${job.id}`}
        title={`${humanize(job.job_type)} run`}
        sub={
          <>
            {/* The scope first: "API Reference · 3 pages" says more about
                this run than when it started. */}
            {scope && <span className="text-ink-mid">{scope} · </span>}
            started {formatDateTime(job.started_at ?? job.created_at)} · {formatDuration(elapsed)}
            {live ? ' elapsed' : ' total'}
          </>
        }
        back={{ label: 'back to project', onClick: () => navigate(`/app/projects/${pid}`) }}
        right={
          <div className="flex items-center gap-2">
            <StatusBadge status={job.status} size="md" />
            {live && can('manager') && (
              confirming ? (
                <>
                  <span className="tag text-ink-dim">stop the model?</span>
                  <Button variant="danger" onClick={cancel} disabled={cancelling}>
                    {cancelling ? 'stopping…' : 'Yes, cancel'}
                  </Button>
                  <Button variant="ghost" onClick={() => setConfirming(false)}>
                    Keep going
                  </Button>
                </>
              ) : (
                <Button variant="ghost" onClick={() => setConfirming(true)}>
                  Cancel run
                </Button>
              )
            )}
          </div>
        }
      />

      {actionError && <ErrorState message={actionError} compact />}

      <JobTargets job={job} site={site} projectId={pid} projectName={job.project_name} />

      {/* progress strip */}
      <div className="mb-3 border border-rule bg-panel">
        <div className="flex items-center gap-3 px-3 py-2">
          <span className="tag text-ink-dim">
            {done}/{stages.length} stages
          </span>
          <span className="relative h-[6px] min-w-0 flex-1 overflow-hidden bg-sunk">
            <span
              className="block h-full bg-hot transition-[width] duration-500"
              style={{ width: `${pct}%` }}
            />
            {live && <span className="anim-sweep absolute inset-0" />}
          </span>
          <span className="tag tabular-nums text-hot-ink">{Math.round(pct)}%</span>
        </div>
        <div className="border-t border-rule bg-sunk/50 px-3 py-1.5">
          <span className="text-[11.5px] text-ink-mid">
            {job.error_message ? (
              <span className="text-[var(--bad)]">{job.error_message}</span>
            ) : running ? (
              (stagePurpose(running.name) ?? `Running ${agentLabel(running.name)}…`)
            ) : job.status === 'awaiting_review' ? (
              'Paused for human review. Resuming is not supported by the API yet.'
            ) : job.status === 'completed' ? (
              'Finished.'
            ) : job.status === 'cancelled' ? (
              'Cancelled. Remaining stages never ran.'
            ) : (
              'Queued.'
            )}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-[1fr_360px]">
        <div className="flex min-w-0 flex-col gap-3">
          <PipelineTree job={job} diagramsEnabled={diagramsEnabled} logs={logs} />

          {job.status === 'completed' && job.job_type === 'analysis' && (
            <Panel
              title="Knowledge base ready"
              action={kb ? <StatusBadge status={kb.knowledge_base.status} /> : null}
            >
              <div className="grid grid-cols-2 gap-px bg-rule sm:grid-cols-4">
                <Stat k="modules" v={kb?.module_count ?? '—'} hot />
                <Stat k="facts" v={kb?.entity_count ?? '—'} />
                <Stat k="languages" v={kb?.languages?.length ?? '—'} />
                <Stat k="commit" v={shortSha(kb?.knowledge_base.commit_sha)} />
              </div>
              <div className="px-3 py-2.5">
                <p className="font-sans text-[12.5px] leading-relaxed text-ink-mid">
                  The repository has been read and stored. Nothing is written until you
                  choose what to write — and the options come from what was actually
                  found in the code.
                </p>
                {kb?.suggested_doc_types?.length ? (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {kb.suggested_doc_types.slice(0, 5).map(s => (
                      <span
                        key={s.doc_type}
                        title={s.reason}
                        className="tag border border-hot-edge bg-hot-wash px-1.5 py-0.5 text-hot-ink"
                      >
                        {docTypeTitle(s.doc_type)} · {confidenceLabel(s.confidence)}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
              <footer className="flex flex-wrap items-center gap-2 border-t border-rule bg-sunk/60 px-3 py-2.5">
                <span className="tag text-ink-dim">
                  this does not need repeating for each document
                </span>
                <Button
                  variant="hot"
                  className="ml-auto"
                  onClick={() => navigate(`/app/projects/${pid}`)}
                >
                  Choose what to write →
                </Button>
              </footer>
            </Panel>
          )}

          {job.status === 'completed' && docs.length > 0 && (
            <Panel title="What was written">
              <ul className="divide-y divide-rule">
                {docs.map(d => (
                  <li key={d.id}>
                    <Link
                      to={`/app/documents/${d.id}`}
                      state={{ from: `/app/projects/${pid}/jobs/${job.id}`, label: 'back to the run' }}
                      className="flex items-center gap-2 px-3 py-2 transition-colors hover:bg-hot-wash/60"
                    >
                      <span className="block size-[7px] rotate-45 bg-hot" />
                      <span className="min-w-0 flex-1 truncate text-[12px] font-semibold text-ink">
                        {d.title}
                      </span>
                      <span className="tag text-ink-dim">{humanize(d.doc_type)}</span>
                      <span className="tag text-hot-ink">read →</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </Panel>
          )}
        </div>

        <div className="min-w-0">
          <LogStream logs={logs} streaming={streaming} />
          {error && <p className="tag mt-2 text-[var(--warn)]">{error} · retrying</p>}
        </div>
      </div>
    </div>
  )
}
