import { useMemo, useState } from 'react'
import { agentLabel, formatDuration } from '../../lib/format'
import {
  describeStep, expectedStages, PARALLEL_STAGES, SYNTHETIC_STAGES,
} from '../../lib/narrate'
import type { Job, JobStep, StepStatus } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * The pipeline as a directed graph, not a list of rows.
 *
 * A fixed-width SVG rail is drawn beside fixed-height HTML rows, so node
 * geometry stays locked to row content at any zoom. diagram_agent and
 * qa_agent fork off the writer into their own lanes and rejoin at gate.
 *
 * Steps arrive incrementally — a job three stages into seven returns
 * three steps — so rows come from the expected stage list and are then
 * filled in from whatever the job has reported.
 * ------------------------------------------------------------------ */

const ROW = 46
const RAIL = 62
const LANE_X: Record<number, number> = { [-1]: 16, 0: 31, 1: 46 }

/** Rendered status, which adds "skipped" — a state the API does not send. */
type RowStatus = StepStatus | 'skipped'

interface Row {
  key: string
  label: string
  detail: string | null
  status: RowStatus
  duration: number | null
  lane: -1 | 0 | 1
  parents: number[]
}

function buildRows(job: Job): Row[] {
  const stages = expectedStages(job.job_type)
  const steps = job.steps ?? []

  // Any stage the backend reported that we did not expect still gets a row.
  const byName = new Map<string, JobStep>()
  for (const s of steps) byName.set(s.name, s)
  const extra = steps.filter(s => !stages.includes(s.name)).map(s => s.name)
  const order = [...stages, ...extra]

  // A cancelled or failed job never runs its remaining stages. Showing
  // them as "pending" implies they are still queued, which is a lie.
  const abandoned = job.status === 'cancelled' || job.status === 'failed'

  const laneOf = (name: string): -1 | 0 | 1 =>
    PARALLEL_STAGES[0] === name ? -1 : PARALLEL_STAGES[1] === name ? 1 : 0

  const rows = order.map((name, i) => {
    const step = byName.get(name)
    const status: RowStatus = step
      ? (step.status as RowStatus)
      : abandoned
        ? 'skipped'
        : 'pending'

    // Parents: the parallel pair both hang off the stage before them, and
    // the join takes both of them. Everything else is a simple chain.
    let parents = i === 0 ? [] : [i - 1]
    if (PARALLEL_STAGES.includes(name)) {
      parents = [order.indexOf(PARALLEL_STAGES[0]) - 1]
    } else if (name === 'gate') {
      parents = PARALLEL_STAGES.map(p => order.indexOf(p)).filter(x => x >= 0)
      if (!parents.length) parents = [i - 1]
    }

    return {
      key: name,
      label: name === 'gate' ? 'Join' : agentLabel(name),
      detail: step ? describeStep(step) : null,
      status,
      duration: step?.duration_seconds ?? null,
      lane: laneOf(name),
      parents,
    }
  })

  // Synthetic nodes report no step of their own, so their state has to come
  // from the lanes feeding them — otherwise the join sits on "pending"
  // forever, including on a job that finished ten minutes ago.
  for (const row of rows) {
    if (!SYNTHETIC_STAGES.includes(row.key)) continue
    const feeders = row.parents.map(p => rows[p]).filter(Boolean)
    row.status = abandoned
      ? 'skipped'
      : feeders.some(f => f.status === 'failed')
        ? 'failed'
        : feeders.length && feeders.every(f => f.status === 'completed')
          ? 'completed'
          : 'pending'
  }

  return rows
}

const NODE_FILL: Record<RowStatus, string> = {
  completed: 'var(--ok)',
  running: 'var(--hot)',
  failed: 'var(--bad)',
  pending: 'var(--panel)',
  skipped: 'var(--panel)',
}

const NODE_STROKE: Record<RowStatus, string> = {
  completed: 'var(--ok)',
  running: 'var(--hot)',
  failed: 'var(--bad)',
  pending: 'var(--rule)',
  skipped: 'var(--rule)',
}

export default function PipelineTree({ job }: { job: Job }) {
  const rows = useMemo(() => buildRows(job), [job])
  const [hover, setHover] = useState<number | null>(null)

  const height = rows.length * ROW
  const cy = (i: number) => i * ROW + ROW / 2
  const cx = (lane: number) => LANE_X[lane]

  const slowest = Math.max(1, ...rows.map(r => r.duration ?? 0))

  return (
    <div className="flex border border-rule bg-panel">
      {/* the rail */}
      <svg
        width={RAIL}
        height={height}
        className="shrink-0 border-r border-rule bg-sunk/40"
        aria-hidden
      >
        {/* edges first, so nodes sit on top */}
        {rows.map((r, i) =>
          r.parents.map(p => {
            const parent = rows[p]
            if (!parent) return null
            const x1 = cx(parent.lane)
            const y1 = cy(p)
            const x2 = cx(r.lane)
            const y2 = cy(i)
            const mid = y1 + (y2 - y1) / 2
            // Orthogonal plotter trace with softened corners.
            const d =
              x1 === x2
                ? `M${x1} ${y1} V${y2}`
                : `M${x1} ${y1} V${mid - 6} Q${x1} ${mid} ${x1 + Math.sign(x2 - x1) * 6} ${mid} H${x2 - Math.sign(x2 - x1) * 6} Q${x2} ${mid} ${x2} ${mid + 6} V${y2}`
            const done = parent.status === 'completed'
            return (
              <g key={`${p}-${i}`}>
                <path d={d} fill="none" stroke="var(--rule)" strokeWidth="1.5" />
                {done && (
                  <path
                    d={d}
                    fill="none"
                    stroke="var(--hot)"
                    strokeWidth="1.5"
                    className="anim-flow"
                    opacity="0.85"
                  />
                )}
              </g>
            )
          }),
        )}

        {rows.map((r, i) => {
          const dim = hover !== null && hover !== i
          const x = cx(r.lane)
          const y = cy(i)
          return (
            <g key={r.key} opacity={dim ? 0.45 : 1} style={{ transition: 'opacity .15s' }}>
              {r.status === 'running' && (
                <circle cx={x} cy={y} r="5" fill="var(--hot)" opacity="0.35">
                  <animate attributeName="r" values="5;10;5" dur="1.6s" repeatCount="indefinite" />
                  <animate
                    attributeName="opacity"
                    values="0.35;0;0.35"
                    dur="1.6s"
                    repeatCount="indefinite"
                  />
                </circle>
              )}
              <rect
                x={x - 4.5}
                y={y - 4.5}
                width="9"
                height="9"
                transform={`rotate(45 ${x} ${y})`}
                fill={NODE_FILL[r.status]}
                stroke={NODE_STROKE[r.status]}
                strokeWidth="1.5"
                strokeDasharray={r.status === 'skipped' ? '2 2' : undefined}
              />
            </g>
          )
        })}
      </svg>

      {/* the rows */}
      <ol className="min-w-0 flex-1">
        {rows.map((r, i) => {
          const pct = r.duration ? (r.duration / slowest) * 100 : 0
          return (
            <li
              key={r.key}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
              style={{ height: ROW }}
              className={`flex items-center gap-3 border-b border-rule px-3 transition-colors last:border-b-0 ${
                r.status === 'running' ? 'bg-hot-wash/60' : 'hover:bg-sunk/50'
              }`}
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span
                    className={`truncate text-[12px] font-semibold tracking-tight ${
                      r.status === 'pending' || r.status === 'skipped'
                        ? 'text-ink-dim'
                        : 'text-ink'
                    }`}
                  >
                    {r.label}
                  </span>
                  {r.status === 'failed' && <span className="tag text-bad">failed</span>}
                  {r.status === 'skipped' && <span className="tag text-ink-dim">skipped</span>}
                  {PARALLEL_STAGES.includes(r.key) && (
                    <span className="tag text-ink-dim">parallel</span>
                  )}
                </div>
                <div className="truncate text-[10.5px] leading-snug text-ink-dim">
                  {r.status === 'skipped'
                    ? 'Never ran'
                    : (r.detail ?? (r.status === 'pending' ? 'Queued' : '—'))}
                </div>
              </div>

              {/* duration bar — makes a slow stage obvious at a glance */}
              <div className="hidden w-24 shrink-0 sm:block">
                {r.duration != null && (
                  <>
                    <span className="block h-[3px] w-full bg-sunk">
                      <span
                        className={`block h-full ${r.status === 'failed' ? 'bg-bad' : 'bg-hot'}`}
                        style={{ width: `${Math.max(3, pct)}%` }}
                      />
                    </span>
                    <span className="tag mt-1 block text-right text-ink-dim">
                      {formatDuration(r.duration)}
                    </span>
                  </>
                )}
              </div>
            </li>
          )
        })}
      </ol>
    </div>
  )
}
