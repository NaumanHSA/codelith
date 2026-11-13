import { useMemo, useState } from 'react'
import { formatDuration } from '../../lib/format'
import { Icon } from '../../lib/icons'
import { stageIcon } from '../../lib/narrate'
import type { Job, JobLog } from '../../lib/types'
import { buildRows, type Row, type RowStatus } from './stages'
import WriterFanout, { buildSections } from './WriterFanout'

/* ------------------------------------------------------------------ *
 * A run as a stepper: one row per stage, its icon, its state, and what it
 * did, in the order the stages run. Replaces the drawn pipeline tree. The
 * two stages that run side by side say so; the writer opens out into the
 * sections it is writing while it works.
 * ------------------------------------------------------------------ */

const STATE: Record<RowStatus, { ring: string; text: string; label: string }> = {
  completed: { ring: 'border-ok/50 text-ok', text: 'text-ink', label: 'Done' },
  running: { ring: 'border-hot text-hot', text: 'text-ink', label: 'Running' },
  failed: { ring: 'border-bad/60 text-bad', text: 'text-ink', label: 'Failed' },
  pending: { ring: 'border-rule text-ink-dim', text: 'text-ink-mid', label: 'Queued' },
  skipped: { ring: 'border-dashed border-rule text-ink-dim', text: 'text-ink-dim', label: 'Never ran' },
  disabled: { ring: 'border-dashed border-rule text-ink-dim', text: 'text-ink-dim', label: 'Switched off' },
}

function subtitle(r: Row): string {
  if (r.status === 'disabled') return 'Switched off in configuration, so this run skips it'
  if (r.status === 'skipped') return 'Never ran'
  if (r.detail) return r.detail
  return r.purpose ?? ''
}

export default function Stepper({
  job,
  diagramsEnabled = null,
  logs = [],
}: {
  job: Job
  diagramsEnabled?: boolean | null
  /** The writer's per-section progress rides on these. */
  logs?: JobLog[]
}) {
  const rows = useMemo(() => buildRows(job, diagramsEnabled), [job, diagramsEnabled])
  const outline = useMemo(() => {
    const step = (job.steps ?? []).find(s => s.name === 'composition_planner_agent')
    const raw = step?.output_json?.outline
    return raw && typeof raw === 'object' ? (raw as Record<string, string[]>) : null
  }, [job.steps])
  const sections = useMemo(() => buildSections(outline, logs), [outline, logs])
  const writer = rows.find(r => r.key === 'composition_writer_agent')
  const [openWriter, setOpenWriter] = useState<boolean | null>(null)
  const showFanout = sections.length > 0 && (openWriter ?? writer?.status === 'running')

  return (
    <ol className="flex flex-col">
      {rows.map((r, i) => {
        const st = STATE[r.status]
        const isWriter = r.key === 'composition_writer_agent' && sections.length > 0
        const last = i === rows.length - 1
        return (
          <li key={r.key} className="relative flex gap-3.5">
            {!last && (
              <span
                aria-hidden
                className={`absolute top-10 bottom-0 left-[17px] w-px ${r.status === 'completed' ? 'bg-ok/40' : 'bg-rule'}`}
              />
            )}
            <span
              className={`relative z-[1] mt-1 grid size-9 shrink-0 place-items-center rounded-full border-2 bg-panel ${st.ring}`}
              title={st.label}
            >
              {r.status === 'running' ? (
                <Icon name="loader" size={16} className="anim-spin" />
              ) : r.status === 'completed' ? (
                <Icon name="check" size={16} />
              ) : r.status === 'failed' ? (
                <Icon name="x" size={16} />
              ) : (
                <Icon name={stageIcon(r.key)} size={15} />
              )}
            </span>
            <div className={`min-w-0 flex-1 ${last ? 'pb-1' : 'pb-5'}`}>
              <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 pt-1.5">
                <Icon name={stageIcon(r.key)} size={15} className="text-ink-dim" />
                <span className={`text-[14px] font-medium ${st.text}`}>{r.label}</span>
                {r.lane !== 0 && (
                  <span className="rounded-md border border-rule px-1.5 py-px text-[12px] text-ink-dim">in parallel</span>
                )}
                <span className={`text-[13px] ${r.status === 'running' ? 'text-hot-ink' : r.status === 'failed' ? 'text-bad' : 'text-ink-dim'}`}>
                  {st.label}
                </span>
                {r.duration != null && (
                  <span className="ml-auto font-mono text-[13px] text-ink-dim tabular-nums">{formatDuration(r.duration)}</span>
                )}
              </div>
              <p className={`mt-0.5 text-[13px] leading-snug ${r.status === 'completed' ? 'text-ink-mid' : 'text-ink-dim'}`}>
                {subtitle(r)}
              </p>
              {isWriter && (
                <div className="mt-2">
                  <button
                    type="button"
                    onClick={() => setOpenWriter(!showFanout)}
                    className="flex items-center gap-1.5 rounded-md px-1.5 py-1 text-[12.5px] text-ink-mid transition-colors hover:bg-hover hover:text-ink"
                  >
                    <Icon name={showFanout ? 'chevron-down' : 'chevron-right'} size={14} />
                    {sections.filter(x => x.state === 'done').length}/{sections.length} sections written
                  </button>
                  {showFanout && (
                    <div className="mt-1.5">
                      <WriterFanout sections={sections} multiPage={Object.keys(outline ?? {}).length > 1} />
                    </div>
                  )}
                </div>
              )}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
