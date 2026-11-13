import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError } from '../../lib/api'
import { useAsync, useJob, useJobLogs } from '../../lib/hooks'
import { useAuth } from '../../auth'
import { useRunningJobs } from '../../running-jobs'
import { agentLabel, elapsedSeconds, formatDateTime, formatDuration, humanize, shortSha } from '../../lib/format'
import { confidenceLabel, docTypeTitle } from '../../lib/docTypes'
import { progressStages, stageIcon, stagePurpose } from '../../lib/narrate'
import { describeJobScope } from '../../lib/site'
import { Icon } from '../../lib/icons'
import { useFill } from '../../lib/motion'
import { isTerminal, type Doc, type JobLog, type KnowledgeBase, type Site } from '../../lib/types'
import { Button, StatusBadge } from '../../components/ui'
import { IconTile, StatBlock } from '../../components/primitives'
import { ErrorState, SkeletonPanel } from '../../components/States'
import Stepper from '../../components/jobs/Stepper'
import JobTargets from '../../components/jobs/JobTargets'
import ReviewGate from '../../components/jobs/ReviewGate'
import { NEW_TAB } from '../../components/layout/tabState'

/* ------------------------------------------------------------------ *
 * A run, live. Every stage as a step with its state and what it did, a
 * progress bar over the stages that report, and the output log beside
 * it filling the height. A tool page: it fills the window and its two
 * panes scroll on their own.
 * ------------------------------------------------------------------ */

const LEVEL_COLOR: Record<string, string> = {
  error: 'text-bad',
  warning: 'text-warn',
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
    <div className="flex h-full min-h-[320px] flex-col overflow-hidden rounded-xl border border-term-rule bg-term">
      <header className="flex items-center gap-2.5 border-b border-term-rule px-4 py-2.5">
        <Icon name="square-terminal" size={15} className="text-term-dim" />
        <span className="text-[13px] font-medium text-term-text">Output</span>
        <span className="ml-auto flex items-center gap-3">
          {streaming && (
            <span className="flex items-center gap-1.5 text-[12px] text-term-ok">
              <span className="anim-pulse block size-[7px] rounded-full bg-term-ok" /> Live
            </span>
          )}
          <button
            type="button"
            onClick={() => setStick(s => !s)}
            className={`rounded-md px-2 py-0.5 text-[12px] transition-colors ${stick ? 'text-term-ok' : 'text-term-dim hover:text-term-text'}`}
          >
            {stick ? 'Following' : 'Paused'}
          </button>
        </span>
      </header>
      <div
        ref={box}
        onScroll={e => {
          const el = e.currentTarget
          // Turning "follow" off the moment the reader scrolls up is the only
          // behaviour that does not fight them.
          const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24
          if (atBottom !== stick) setStick(atBottom)
        }}
        className="min-h-0 flex-1 overflow-y-auto px-4 py-3 font-mono text-[12px] leading-[1.6]"
      >
        {logs.length === 0 && <p className="text-term-dim">Waiting for the first line…</p>}
        {logs.map(l => (
          <div key={l.id} className="flex gap-3">
            <span className="shrink-0 text-term-dim tabular-nums">
              {new Date(l.timestamp).toLocaleTimeString([], { hour12: false })}
            </span>
            {l.agent && (
              <span className="hidden w-[150px] shrink-0 truncate text-hot-ink sm:block">{agentLabel(l.agent)}</span>
            )}
            <span className={`min-w-0 flex-1 break-words ${LEVEL_COLOR[l.level] ?? 'text-term-text'}`}>{l.message}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function Progress({ pct, live }: { pct: number; live: boolean }) {
  const shown = useFill(pct)
  return (
    <span className="relative block h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-sunk">
      <span className="block h-full rounded-full bg-hot transition-[width] duration-500" style={{ width: `${shown}%` }} />
      {live && <span className="anim-sweep absolute inset-0" />}
    </span>
  )
}

export default function JobProgressPage() {
  const { projectId, jobId } = useParams()
  const pid = Number(projectId)
  const id = Number(jobId)
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
  // Null until known. A stage must never be drawn as enabled on a guess.
  const [diagramsEnabled, setDiagramsEnabled] = useState<boolean | null>(null)
  const [kb, setKb] = useState<KnowledgeBase | null>(null)
  const apps = useAsync(sig => api.appCatalog(sig), []).data

  useEffect(() => {
    if (job?.status !== 'completed' || job.job_type !== 'composition') return
    api
      .documents(pid, 50, 0)
      .then(all => setDocs(all.filter(d => d.job_id === job.id)))
      .catch(() => setDocs([]))
  }, [job?.status, job?.id, job?.job_type, pid])

  useEffect(() => {
    if (job?.status !== 'completed' || job.job_type !== 'analysis') return
    api
      .knowledgeBase(pid)
      .then(setKb)
      .catch(() => setKb(null))
  }, [job?.status, job?.id, job?.job_type, pid])

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

  // `gate` never reports a step, so it is not in the denominator.
  const stages = job ? progressStages(job.job_type) : []
  const done = (job?.steps ?? []).filter(s => s.status === 'completed' && stages.includes(s.name)).length
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
      setActionError(e instanceof ApiError ? e.message : 'Could not cancel the run.')
    } finally {
      setCancelling(false)
    }
  }

  if (loading && !job)
    return (
      <div className="w-full px-6 py-5">
        <SkeletonPanel rows={7} />
      </div>
    )
  if (!job)
    return (
      <div className="w-full px-6 py-5">
        <ErrorState message={error ?? 'Run not found.'} />
      </div>
    )

  const scope = describeJobScope(job)

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 px-6 py-5">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3.5">
          <IconTile icon={job.job_type === 'analysis' ? 'radar' : 'pencil'} color="var(--hot)" tint size={44} />
          <div className="min-w-0">
            <h1 className="flex items-center gap-2 text-[22px] leading-tight font-semibold text-ink">
              {humanize(job.job_type)} run
              <span className="font-mono text-[15px] font-normal text-ink-dim">#{job.id}</span>
            </h1>
            <p className="mt-1 text-[13px] text-ink-mid">
              {job.project_name && (
                <Link to={`/app/projects/${pid}`} className="text-ink hover:underline">
                  {job.project_name}
                </Link>
              )}
              {scope ? ` · ${scope}` : ''} · started {formatDateTime(job.started_at ?? job.created_at)} ·{' '}
              {formatDuration(elapsed)} {live ? 'so far' : 'in all'}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={job.status} size="md" />
          {live &&
            can('manager') &&
            (confirming ? (
              <>
                <span className="text-[12.5px] text-ink-dim">Stop the model?</span>
                <Button variant="danger" onClick={cancel} disabled={cancelling}>
                  {cancelling ? 'Stopping…' : 'Yes, cancel'}
                </Button>
                <Button variant="ghost" onClick={() => setConfirming(false)}>
                  Keep going
                </Button>
              </>
            ) : (
              <Button variant="ghost" onClick={() => setConfirming(true)}>
                <Icon name="x" size={14} /> Cancel run
              </Button>
            ))}
        </div>
      </header>

      {actionError && <ErrorState message={actionError} compact />}

      <div className="flex flex-col gap-2 rounded-xl border border-rule bg-panel px-4 py-3">
        <div className="flex items-center gap-3">
          <span className="font-mono text-[12.5px] text-ink-mid tabular-nums">
            {done}/{stages.length} stages
          </span>
          <Progress pct={pct} live={live} />
          <span className="font-mono text-[12.5px] text-hot-ink tabular-nums">{Math.round(pct)}%</span>
        </div>
        <p className="flex items-center gap-2 text-[13px] text-ink-mid">
          {job.error_message ? (
            <span className="flex items-center gap-1.5 text-bad">
              <Icon name="circle-x" size={14} /> {job.error_message}
            </span>
          ) : running ? (
            <>
              <Icon name={stageIcon(running.name)} size={14} className="text-hot" />
              {stagePurpose(running.name) ?? `Running ${agentLabel(running.name)}…`}
            </>
          ) : job.status === 'awaiting_review' ? (
            'Paused for review. Nothing is published until you approve it.'
          ) : job.status === 'completed' ? (
            'Finished.'
          ) : job.status === 'cancelled' ? (
            'Cancelled. The remaining stages never ran.'
          ) : (
            'Queued.'
          )}
        </p>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(420px,44%)]">
        <div className="flex min-h-0 min-w-0 flex-col gap-4 overflow-y-auto pr-1">
          {job.status === 'awaiting_review' && (
            <ReviewGate projectId={job.project_id} jobId={job.id} onResolved={setJob} />
          )}

          {job.status === 'completed' && job.job_type === 'analysis' && (
            <section className="flex flex-col gap-3 rounded-xl border border-ok/30 bg-panel p-4">
              <div className="flex items-center gap-2.5">
                <Icon name="circle-check" size={18} className="text-ok" />
                <h2 className="text-[15px] font-semibold text-ink">Knowledge base ready</h2>
                <span className="ml-auto">{kb && <StatusBadge status={kb.knowledge_base.status} />}</span>
              </div>
              <div className="grid grid-cols-2 gap-x-6 border-y border-rule sm:grid-cols-4">
                <StatBlock value={kb?.module_count ?? 0} label="modules" icon="layers" />
                <StatBlock value={kb?.entity_count ?? 0} label="facts" icon="hash" />
                <StatBlock value={kb?.languages?.length ?? 0} label="languages" icon="code" />
                <StatBlock value={shortSha(kb?.knowledge_base.commit_sha)} label="commit" icon="git-commit-horizontal" />
              </div>
              <p className="text-[13px] leading-relaxed text-ink-mid">
                The repository has been read and stored. Every app reads this reading without opening
                the repository again.
              </p>
              <div className="flex flex-wrap gap-2">
                <Link
                  to={`/app/projects/${pid}`}
                  className="inline-flex items-center gap-2 rounded-lg bg-hot px-3.5 py-[7px] text-[13px] font-medium text-on-hot hover:bg-hot-ink"
                >
                  <Icon name="folder-git-2" size={15} /> Open this codebase
                </Link>
                <Link
                  to={`/app/projects/${pid}/graph`}
                  state={NEW_TAB}
                  className="inline-flex items-center gap-2 rounded-lg border border-line-2 bg-sunk px-3.5 py-[7px] text-[13px] font-medium text-ink hover:bg-hover"
                >
                  <Icon name="waypoints" size={15} /> Open the knowledge graph
                </Link>
                {(apps ?? [])
                  .filter(a => a.built)
                  .map(a => (
                    <Link
                      key={a.id}
                      to={a.route_template.replace('{id}', String(pid))}
                      className="inline-flex items-center gap-2 rounded-lg border border-line-2 bg-sunk px-3.5 py-[7px] text-[13px] font-medium text-ink hover:bg-hover"
                    >
                      {a.label}
                    </Link>
                  ))}
              </div>
              {!!kb?.suggested_doc_types?.length && (
                <div className="flex flex-wrap items-center gap-1.5 text-[12.5px] text-ink-dim">
                  <span className="tag mr-1">Documentation suggests</span>
                  {kb.suggested_doc_types.slice(0, 5).map(s => (
                    <span key={s.doc_type} title={s.reason} className="rounded-full border border-line-2 px-2.5 py-0.5 text-ink-mid">
                      {docTypeTitle(s.doc_type)} · {confidenceLabel(s.confidence)}
                    </span>
                  ))}
                </div>
              )}
            </section>
          )}

          {job.status === 'completed' && docs.length > 0 && (
            <section className="flex flex-col gap-2 rounded-xl border border-rule bg-panel p-4">
              <h2 className="text-[15px] font-semibold text-ink">What was written</h2>
              <ul className="flex flex-col">
                {docs.map(d => (
                  <li key={d.id}>
                    <Link
                      to={`/app/documents/${d.id}`}
                      state={{ from: `/app/projects/${pid}/jobs/${job.id}`, label: 'back to the run' }}
                      className="flex items-center gap-2.5 rounded-md px-2 py-2 transition-colors hover:bg-hover"
                    >
                      <Icon name="file-text" size={15} className="text-ink-dim" />
                      <span className="min-w-0 flex-1 truncate text-[13.5px] text-ink">{d.title}</span>
                      <span className="text-[12px] text-ink-dim">{humanize(d.doc_type)}</span>
                      <Icon name="chevron-right" size={14} className="text-ink-dim" />
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <JobTargets job={job} site={site} projectId={pid} projectName={job.project_name} />

          <section className="rounded-xl border border-rule bg-panel p-5">
            <Stepper job={job} diagramsEnabled={diagramsEnabled} logs={logs} />
          </section>
        </div>

        <div className="flex min-h-[320px] min-w-0 flex-col">
          <LogStream logs={logs} streaming={streaming} />
          {error && <p className="mt-2 text-[12.5px] text-warn">{error} · retrying</p>}
        </div>
      </div>
    </div>
  )
}
