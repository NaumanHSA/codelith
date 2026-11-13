import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useRunningJobs, type TrackedJob } from '../../running-jobs'
import { agentLabel, humanize } from '../../lib/format'
import { Icon } from '../../lib/icons'
import { stageIcon } from '../../lib/narrate'
import { useFill } from '../../lib/motion'

/* ------------------------------------------------------------------ *
 * The live run, following you. A run takes minutes and people leave the
 * page; this sits in the corner of every page while work runs, says which
 * stage it is on and how far it has got, and opens the run in one click.
 * It used to be a coloured banner across the top of the page that pushed
 * everything down when a job started and up again when it finished.
 *
 * Hidden on the run's own page, which already says all of this.
 * ------------------------------------------------------------------ */

function Bar({ done, total, tone }: { done: number; total: number; tone: string }) {
  const pct = useFill(total ? (done / total) * 100 : 0)
  return (
    <span className="block h-1 w-full overflow-hidden rounded-full bg-sunk">
      <span className={`block h-full rounded-full transition-[width] duration-500 ${tone}`} style={{ width: `${pct}%` }} />
    </span>
  )
}

function Row({ j }: { j: TrackedJob }) {
  const done = j.status === 'completed'
  const bad = j.status === 'failed' || j.status === 'cancelled'
  const review = j.status === 'awaiting_review'
  const runningish = !done && !bad && !review
  return (
    <Link
      to={`/app/projects/${j.projectId}/jobs/${j.id}`}
      className="flex flex-col gap-1.5 rounded-lg px-3 py-2.5 transition-colors hover:bg-hover"
    >
      <span className="flex items-center gap-2">
        {runningish ? (
          <Icon name="loader" size={14} className="anim-spin text-hot" />
        ) : (
          <Icon
            name={done ? 'circle-check' : bad ? 'circle-x' : 'clock'}
            size={14}
            className={done ? 'text-ok' : bad ? 'text-bad' : 'text-warn'}
          />
        )}
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-ink">
          {humanize(j.jobType)} <span className="font-mono text-[11.5px] font-normal text-ink-dim">#{j.id}</span>
          {j.projectName && <span className="font-normal text-ink-mid"> · {j.projectName}</span>}
        </span>
        {j.total ? (
          <span className="font-mono text-[11.5px] text-ink-dim tabular-nums">
            {j.done}/{j.total}
          </span>
        ) : null}
      </span>
      <span className="flex items-center gap-1.5 text-[12px] text-ink-mid">
        {j.stage && runningish && <Icon name={stageIcon(j.stage)} size={13} className="text-ink-dim" />}
        <span className="truncate">
          {done
            ? 'Finished'
            : bad
              ? humanize(j.status)
              : review
                ? 'Waiting for your review'
                : j.stage
                  ? agentLabel(j.stage)
                  : 'Starting'}
        </span>
      </span>
      {j.total ? (
        <Bar done={done ? j.total : (j.done ?? 0)} total={j.total} tone={done ? 'bg-ok' : bad ? 'bg-bad' : review ? 'bg-warn' : 'bg-hot'} />
      ) : null}
    </Link>
  )
}

export default function RunDock() {
  const { jobs } = useRunningJobs()
  const { pathname } = useLocation()
  const [open, setOpen] = useState(true)
  const shown = jobs.filter(j => !pathname.endsWith(`/jobs/${j.id}`))
  if (!shown.length) return null
  const live = shown.filter(j => !['completed', 'failed', 'cancelled'].includes(j.status)).length

  return (
    <div className="anim-rise fixed right-5 bottom-5 z-50 w-[340px] max-w-[calc(100vw-40px)] overflow-hidden rounded-xl border border-line-2 bg-panel shadow-[0_24px_60px_-20px_var(--shadow)]">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="flex w-full items-center gap-2 border-b border-rule px-3.5 py-2.5 text-left"
        aria-expanded={open}
      >
        <Icon name="activity" size={15} className={live ? 'text-hot' : 'text-ink-dim'} />
        <span className="flex-1 text-[13px] font-medium text-ink">
          {live ? `${live} run${live === 1 ? '' : 's'} in progress` : 'Runs finished'}
        </span>
        <Icon name={open ? 'chevron-down' : 'chevron-right'} size={14} className="text-ink-dim" />
      </button>
      {open && (
        <div className="flex max-h-[300px] flex-col overflow-y-auto p-1">
          {shown.map(j => (
            <Row key={j.id} j={j} />
          ))}
        </div>
      )}
    </div>
  )
}
