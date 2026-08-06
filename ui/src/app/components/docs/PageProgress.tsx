import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useJob } from '../../lib/hooks'
import { agentLabel } from '../../lib/format'
import { describeStep, progressStages } from '../../lib/narrate'
import { isTerminal, type SitePage } from '../../lib/types'
import { Button, Meter } from '../ui'

/* ------------------------------------------------------------------ *
 * What is happening to the page you are looking at.
 *
 * The reader and the operator need the same facts, so this shows the
 * stage narration the jobs page shows rather than the word "writing…".
 *
 * Everything here derives from the server: a page carries `status` and
 * `job_id`, both set when a job claims it. That matters because the
 * alternative — remembering locally which button you pressed — is wrong
 * the moment you arrive from anywhere else. Open the page in a second
 * tab, or come back to it from the jobs list, and local state says
 * nothing is happening while the page is being rewritten underneath you.
 *
 * Two states worth separating:
 *
 *   in flight — the job is live. Poll it, narrate it, offer the run.
 *   stranded  — the page still says `generating` but its job has already
 *               reached a terminal status, or it has no job at all. The
 *               worker died mid-write. Without this the page spins for
 *               ever and looks like slow progress rather than a failure.
 * ------------------------------------------------------------------ */

export default function PageProgress({
  projectId, page, onFinished, onRetry, canGenerate,
}: {
  projectId: number
  page: SitePage
  /** The job reached a terminal status — reload the map and the open page. */
  onFinished: () => void
  onRetry: () => void
  canGenerate: boolean
}) {
  const navigate = useNavigate()
  const { job, error } = useJob(page.job_id)

  // Fire once per job, on the transition into a terminal status. `onFinished`
  // is a fresh closure every render, so it is held in a ref rather than
  // listed as a dependency — otherwise the effect re-runs on every poll and
  // reloads the site in a loop.
  const finished = useRef(onFinished)
  finished.current = onFinished
  const announced = useRef<number | null>(null)
  useEffect(() => {
    if (!job || !isTerminal(job.status)) return
    if (announced.current === job.id) return
    announced.current = job.id
    finished.current()
  }, [job])

  // No job recorded at all, or a job that has stopped while the page still
  // claims to be generating. Either way nothing is coming.
  const stranded = page.job_id == null || (job != null && isTerminal(job.status))

  if (stranded) {
    return (
      <section className="mb-4 border border-warn/40 bg-warn-wash px-3 py-2.5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="tag text-warn">stalled</span>
          <span className="font-sans text-[11.5px] text-ink-mid">
            {job
              ? `The run that was writing this page ${job.status} without finishing it.`
              : 'This page is marked as being written, but no run is recorded for it.'}
          </span>
          {canGenerate && (
            <Button variant="ghost" className="ml-auto" onClick={onRetry}>
              ↻ Try again
            </Button>
          )}
        </div>
        {job && (
          <button
            onClick={() => navigate(`/app/projects/${projectId}/jobs/${job.id}`)}
            className="tag mt-1.5 text-hot-ink hover:underline"
          >
            View run #{job.id} →
          </button>
        )}
      </section>
    )
  }

  const steps = job?.steps ?? []
  const denominator = job ? progressStages(job.job_type).length : 0
  const done = steps.filter(s => s.status === 'completed').length
  const pct = denominator ? Math.min(100, Math.round((done / denominator) * 100)) : 0

  // The stage being worked on now, else the last one that finished — a job
  // between stages should not blank the line it was just showing.
  const active = [...steps].reverse().find(s => s.status === 'running') ?? steps[steps.length - 1]

  return (
    <section className="mb-4 border border-rule bg-sunk px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="tag text-hot-ink">being written now</span>
        <Meter pct={pct} segments={14} />
        <span className="tag text-ink-dim">
          {denominator ? `${done}/${denominator}` : '…'}
        </span>
        {job && (
          <button
            onClick={() => navigate(`/app/projects/${projectId}/jobs/${job.id}`)}
            className="tag ml-auto text-hot-ink hover:underline"
          >
            View run #{job.id} →
          </button>
        )}
      </div>

      <p className="mt-1.5 text-[11.5px] text-ink-mid">
        {error
          ? error
          : active
            ? `${agentLabel(active.name)} — ${describeStep(active) ?? 'working'}`
            : 'Starting…'}
      </p>
    </section>
  )
}
