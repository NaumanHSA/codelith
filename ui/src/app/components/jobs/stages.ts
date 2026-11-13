import { agentLabel } from '../../lib/format'
import {
  describeStep, expectedStages, PARALLEL_STAGES, stagePurpose, SYNTHETIC_STAGES,
} from '../../lib/narrate'
import type { Job, JobStep, StepStatus } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * One row per stage of a run, in the order they run, with what each is
 * doing or did. Moved out of the old pipeline tree unchanged: it already
 * handles the parallel pair, the join that reports no step of its own,
 * a stage switched off in configuration, and the stages a cancelled or
 * failed run never reached.
 * ------------------------------------------------------------------ */

export type RowStatus = StepStatus | 'skipped' | 'disabled'

export interface Row {
  key: string
  label: string
  purpose: string | null
  detail: string | null
  status: RowStatus
  duration: number | null
  lane: -1 | 0 | 1
  parents: number[]
}

export function buildRows(job: Job, diagramsEnabled: boolean | null): Row[] {
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
