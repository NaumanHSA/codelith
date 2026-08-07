import { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { agentLabel, formatDuration } from '../../lib/format'
import {
  describeStep, expectedStages, PARALLEL_STAGES, stagePurpose, SYNTHETIC_STAGES,
} from '../../lib/narrate'
import type { Job, JobLog, JobStep, StepStatus } from '../../lib/types'
import WriterFanout, { buildSections } from './WriterFanout'

/* ------------------------------------------------------------------ *
 * The pipeline as a directed graph.
 *
 * A fixed-width SVG rail is drawn beside the rows, and node positions are
 * *measured* from the rows themselves rather than assumed. They used to be
 * `index * ROW`, which was true only while every row was the same height —
 * the writer row expands to show its sections, and computed geometry drifted
 * away from the content the moment it did. `diagram` and `qa` fork off the
 * writer into their own lanes and rejoin at the gate — the only place the
 * graph is not a straight line, and the reason it is drawn at all rather
 * than listed.
 *
 * Steps arrive incrementally — a job three stages into nine returns three
 * steps — so rows come from the expected stage list and are then filled
 * in from whatever the job has reported.
 *
 * **A stage that is switched off must not read as pending.** `diagram`
 * is opt-in, and showing it queued tells the reader work is still coming
 * that never will. `features.diagrams_enabled` covers it before the run
 * reaches that node; the step's own `disabled` output covers it after.
 * ------------------------------------------------------------------ */

const ROW = 52
const RAIL = 62
const LANE_X: Record<number, number> = { [-1]: 16, 0: 31, 1: 46 }

/** Rendered status. Adds two states the API does not send. */
type RowStatus = StepStatus | 'skipped' | 'disabled'

interface Row {
  key: string
  label: string
  purpose: string | null
  detail: string | null
  status: RowStatus
  duration: number | null
  lane: -1 | 0 | 1
  parents: number[]
}

function buildRows(job: Job, diagramsEnabled: boolean | null): Row[] {
  const stages = expectedStages(job.job_type)
  const steps = job.steps ?? []

  // Any stage the backend reported that we did not expect still gets a row.
  const byName = new Map<string, JobStep>()
  for (const s of steps) byName.set(s.name, s)
  const extra = steps.filter(s => !stages.includes(s.name)).map(s => s.name)
  const order = [...stages, ...extra]

  // A cancelled or failed job never runs its remaining stages. Showing them as
  // "pending" implies they are still queued, which is a lie.
  const abandoned = job.status === 'cancelled' || job.status === 'failed'

  const laneOf = (name: string): -1 | 0 | 1 =>
    PARALLEL_STAGES[0] === name ? -1 : PARALLEL_STAGES[1] === name ? 1 : 0

  const rows = order.map((name, i) => {
    const step = byName.get(name)
    let status: RowStatus = step
      ? (step.status as RowStatus)
      : abandoned
        ? 'skipped'
        : 'pending'

    // Off in config, or it ran and reported itself off. Either way it is not work
    // that is still to come.
    const reportedDisabled = Boolean(step?.output_json?.disabled)
    if (name === 'diagram_agent' && (reportedDisabled || diagramsEnabled === false)) {
      status = 'disabled'
    }

    // Parents: the parallel pair both hang off the stage before them, and the join
    // takes both of them. Everything else is a simple chain.
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
      purpose: name === 'gate' ? 'Waits for both branches to finish' : stagePurpose(name),
      detail: step ? describeStep(step) : null,
      status,
      duration: step?.duration_seconds ?? null,
      lane: laneOf(name),
      parents,
    }
  })

  // Synthetic nodes report no step of their own, so their state has to come from the
  // lanes feeding them — otherwise the join sits on "pending" for ever, including on
  // a job that finished ten minutes ago. A disabled feeder counts as satisfied: the
  // join is not waiting for it.
  for (const row of rows) {
    if (!SYNTHETIC_STAGES.includes(row.key)) continue
    const feeders = row.parents.map(p => rows[p]).filter(Boolean)
    const settled = (s: RowStatus) => s === 'completed' || s === 'disabled' || s === 'skipped'
    row.status = abandoned
      ? 'skipped'
      : feeders.some(f => f.status === 'failed')
        ? 'failed'
        : feeders.length && feeders.every(f => settled(f.status))
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
  disabled: 'var(--panel)',
}

const NODE_STROKE: Record<RowStatus, string> = {
  completed: 'var(--ok)',
  running: 'var(--hot)',
  failed: 'var(--bad)',
  pending: 'var(--rule)',
  skipped: 'var(--rule)',
  disabled: 'var(--rule)',
}

/** The one line under the stage name, whatever state it is in. */
function subtitle(r: Row): string {
  if (r.status === 'disabled') return 'Switched off in configuration — this run skips it'
  if (r.status === 'skipped') return 'Never ran'
  if (r.detail) return r.detail
  if (r.status === 'pending') return r.purpose ? `Queued — ${lower(r.purpose)}` : 'Queued'
  return r.purpose ?? '—'
}

const lower = (s: string) => s.charAt(0).toLowerCase() + s.slice(1)

export default function PipelineTree({
  job,
  diagramsEnabled = null,
  logs = [],
}: {
  job: Job
  /** From `GET /settings/features`. Null while unknown — never assume enabled. */
  diagramsEnabled?: boolean | null
  /** The writer's per-section progress rides on these. */
  logs?: JobLog[]
}) {
  const rows = useMemo(() => buildRows(job, diagramsEnabled), [job, diagramsEnabled])
  const [hover, setHover] = useState<number | null>(null)

  // The headings the planner decided, and how far the writer has got through them.
  const outline = useMemo(() => {
    const step = (job.steps ?? []).find(s => s.name === 'composition_planner_agent')
    const raw = step?.output_json?.outline
    return raw && typeof raw === 'object' ? (raw as Record<string, string[]>) : null
  }, [job.steps])

  const sections = useMemo(() => buildSections(outline, logs), [outline, logs])
  const writerRow = rows.findIndex(r => r.key === 'composition_writer_agent')
  // Open while the writer is working, because that is when it says something; closed
  // once it is done, because by then the pages themselves are the better record.
  const writerRunning = writerRow >= 0 && rows[writerRow]?.status === 'running'
  const [openWriter, setOpenWriter] = useState<boolean | null>(null)
  const showFanout =
    sections.length > 0 && (openWriter ?? writerRunning)

  // Measured, not computed: the writer row changes height when its sections are
  // shown, and every node below it moves with it.
  const listRef = useRef<HTMLOListElement>(null)
  const [centres, setCentres] = useState<number[]>([])
  const [height, setHeight] = useState(rows.length * ROW)

  const measure = useCallback(() => {
    const el = listRef.current
    if (!el) return
    const top = el.getBoundingClientRect().top
    const next: number[] = []
    for (const li of Array.from(el.children) as HTMLElement[]) {
      // The node belongs to the stage row, not to whatever is expanded beneath it,
      // so the first child is measured rather than the whole <li>.
      const head = (li.firstElementChild as HTMLElement | null) ?? li
      const hb = head.getBoundingClientRect()
      next.push(hb.top - top + hb.height / 2)
    }
    setCentres(next)
    setHeight(el.getBoundingClientRect().height)
  }, [])

  useLayoutEffect(() => {
    measure()
    const el = listRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    for (const li of Array.from(el.children)) ro.observe(li)
    return () => ro.disconnect()
  }, [measure, rows.length, showFanout, sections.length])

  const cy = (i: number) => centres[i] ?? i * ROW + ROW / 2
  const cx = (lane: number) => LANE_X[lane]

  const slowest = Math.max(1, ...rows.map(r => r.duration ?? 0))

  return (
    <div className="flex border border-rule bg-panel">
      {/* the rail */}
      <svg
        width={RAIL}
        height={height}
        className="shrink-0 self-stretch border-r border-rule bg-sunk/40"
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
            // An edge into a stage that will never run is drawn dashed and dead.
            const dead = r.status === 'disabled' || r.status === 'skipped'
            const lit = hover === i || hover === p
            return (
              <g key={`${p}-${i}`}>
                <path
                  d={d}
                  fill="none"
                  stroke={lit ? 'var(--hot)' : 'var(--rule)'}
                  strokeWidth={lit ? 2 : 1.5}
                  strokeDasharray={dead ? '3 3' : undefined}
                  opacity={dead ? 0.5 : 1}
                  style={{ transition: 'stroke .15s, stroke-width .15s' }}
                />
                {done && !dead && (
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
                  <animate attributeName="r" values="5;11;5" dur="1.6s" repeatCount="indefinite" />
                  <animate
                    attributeName="opacity"
                    values="0.35;0;0.35"
                    dur="1.6s"
                    repeatCount="indefinite"
                  />
                </circle>
              )}
              {hover === i && (
                <circle cx={x} cy={y} r="9" fill="none" stroke="var(--hot)" strokeWidth="1" />
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
                strokeDasharray={
                  r.status === 'skipped' || r.status === 'disabled' ? '2 2' : undefined
                }
              />
            </g>
          )
        })}
      </svg>

      {/* the rows */}
      <ol ref={listRef} className="min-w-0 flex-1">
        {rows.map((r, i) => {
          const pct = r.duration ? (r.duration / slowest) * 100 : 0
          const muted =
            r.status === 'pending' || r.status === 'skipped' || r.status === 'disabled'
          const isWriter = r.key === 'composition_writer_agent' && sections.length > 0
          return (
            <li key={r.key} className="border-b border-rule last:border-b-0">
            <div
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
              onClick={isWriter ? () => setOpenWriter(o => !(o ?? writerRunning)) : undefined}
              // The purpose is on the row itself, so hovering anywhere explains the
              // stage rather than requiring a hit on the 9px node.
              title={r.purpose ? `${r.label} — ${r.purpose}` : r.label}
              style={{ height: ROW }}
              className={`flex items-center gap-3 px-3 transition-colors ${
                r.status === 'running' ? 'bg-hot-wash/60' : 'hover:bg-sunk/50'
              } ${isWriter ? 'cursor-pointer' : ''}`}
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span
                    className={`truncate text-[12px] font-semibold tracking-tight ${
                      muted ? 'text-ink-dim' : 'text-ink'
                    } ${r.status === 'disabled' ? 'line-through decoration-ink-dim/60' : ''}`}
                  >
                    {r.label}
                  </span>
                  {r.status === 'failed' && <span className="tag text-bad">failed</span>}
                  {r.status === 'skipped' && <span className="tag text-ink-dim">skipped</span>}
                  {r.status === 'disabled' && (
                    <span className="tag border border-rule px-1 text-ink-dim">off</span>
                  )}
                  {r.status === 'running' && (
                    <span className="anim-blink block size-[6px] shrink-0 rounded-full bg-hot" />
                  )}
                  {PARALLEL_STAGES.includes(r.key) && r.status !== 'disabled' && (
                    <span className="tag text-ink-dim">parallel</span>
                  )}
                </div>
                <div className="truncate text-[10.5px] leading-snug text-ink-dim">
                  {isWriter
                    ? `${sections.filter(x => x.state === 'done').length}/${sections.length} sections · ${showFanout ? 'hide' : 'show'} them`
                    : subtitle(r)}
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
            </div>
            {isWriter && showFanout && (
              <WriterFanout sections={sections} multiPage={Object.keys(outline ?? {}).length > 1} />
            )}
            </li>
          )
        })}
      </ol>
    </div>
  )
}
