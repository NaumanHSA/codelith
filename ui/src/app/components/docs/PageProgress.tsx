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
 * **The job id does not come from the page alone.** `doc_pages.job_id` is
 * set when the *worker* claims the page, which is a second or two after
 * the API returns the job — so a page read in that window is still
 * `planned` with no job on it, and deriving everything from the row left
 * the reader staring at "not written yet" with nothing moving. The caller
 * therefore passes the job it just started, and that wins until the row
 * catches up.
 *
 * Three states worth separating:
 *
 *   starting  — a job exists, the page has not been claimed yet.
 *   in flight — the job is live and owns the page.
 *   stranded  — the page says `generating` but its job has reached a
 *               terminal status, or there is no job at all. The worker
 *               died mid-write. Without this the page spins for ever and
 *               looks like slow progress rather than a failure.
 * ------------------------------------------------------------------ */

export default function PageProgress({
  projectId, page, jobId, onFinished, onRetry, canGenerate,
}: {
  projectId: number
  page: SitePage
  /** The page's own job, or the one just started for it — whichever exists. */
  jobId: number | null
  /** The job reached a terminal status — reload the map and the open page. */
  onFinished: () => void
  onRetry: () => void
  canGenerate: boolean
}) {
  const navigate = useNavigate()
  const { job, error } = useJob(jobId)

  // Fire once, on the *transition* into a terminal status. Three things guard it,
  // because getting this wrong is a reload loop rather than a cosmetic bug:
  //
  //  - `onFinished` is held in a ref, not listed as a dependency, or the effect
  //    re-runs on every poll.
  //  - `announced` stops it firing twice for the same job.
  //  - `wasLive` stops it firing at all for a job that had already finished when
  //    this mounted. Without it, anything that renders this against a completed run
  //    reloads the page, remounts, and announces again — which is exactly what a
  //    written page's provenance `job_id` used to do, forever.
  const finished = useRef(onFinished)
  finished.current = onFinished
  const announced = useRef<number | null>(null)
  const wasLive = useRef(false)
  useEffect(() => {
    if (!job) return
    if (!isTerminal(job.status)) {
      wasLive.current = true
      return
    }
    if (!wasLive.current || announced.current === job.id) return
    announced.current = job.id
    finished.current()
  }, [job])

  // Nothing is coming: either no job was ever recorded against a page that claims to
  // be generating, or the job that owned it has stopped without finishing it.
  const stranded =
    page.status === 'generating' && (jobId == null || (job != null && isTerminal(job.status)))

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

  // The stage being worked on now, else the last one that finished — a job between
  // stages should not blank the line it was just showing.
  const active = [...steps].reverse().find(s => s.status === 'running') ?? steps[steps.length - 1]

  // Claimed by the worker, or still in the gap between starting and being claimed.
  const claimed = page.status === 'generating'

  return (
    <section className="mb-4 border border-hot/40 bg-hot-wash/50 px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="tag flex items-center gap-1.5 text-hot-ink">
          <span className="anim-blink block size-[6px] rounded-full bg-hot" />
          {claimed ? 'being written now' : 'starting…'}
        </span>
        <Meter pct={pct} segments={14} />
        <span className="tag text-ink-dim">{denominator ? `${done}/${denominator}` : '…'}</span>
        {job && (
          <button
            onClick={() => navigate(`/app/projects/${projectId}/jobs/${job.id}`)}
            className="tag ml-auto border border-hot/40 px-1.5 py-[2px] text-hot-ink transition-colors hover:bg-hot hover:text-paper"
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
            : 'Waiting for the worker to pick this up…'}
      </p>
    </section>
  )
}
