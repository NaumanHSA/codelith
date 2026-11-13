import { Icon } from '../../lib/icons'
import type { TraceStep } from './trace'

/* ------------------------------------------------------------------ *
 * The four steps, in a row above the reply, each lighting as its event
 * arrives on the stream. A declined question stops at the gate: route
 * and retrieve show as skipped, which is what happened.
 * ------------------------------------------------------------------ */

const TONE = {
  done: 'text-ink border-line-2 bg-sunk',
  active: 'text-hot-ink border-hot-edge bg-hot-wash',
  pending: 'text-ink-dim border-rule bg-transparent',
  skipped: 'text-ink-dim border-dashed border-rule bg-transparent',
} as const

export default function AnswerTrace({
  steps,
  onOpen,
}: {
  steps: TraceStep[]
  /** Opens the Thinking tab for this answer. */
  onOpen?: () => void
}) {
  return (
    <ol
      className="flex flex-wrap items-center gap-1.5"
      aria-label="How this answer was reached"
      onClick={onOpen}
    >
      {steps.map((s, i) => (
        <li key={s.id} className="flex items-center gap-1.5">
          {i > 0 && (
            <span
              className={`h-px w-4 ${s.state === 'pending' || s.state === 'skipped' ? 'bg-rule' : 'bg-line-2'}`}
              aria-hidden
            />
          )}
          <button
            type="button"
            title={`${s.label}: ${s.detail}`}
            className={`inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-[12px] font-medium transition-colors ${TONE[s.state]} ${
              onOpen ? 'cursor-pointer hover:border-line-2' : 'cursor-default'
            }`}
          >
            {s.state === 'active' ? (
              <Icon name="loader" size={13} className="anim-spin" />
            ) : s.state === 'done' ? (
              <Icon name={s.icon} size={13} className={s.id === 'gate' ? 'text-ok' : 'text-ink-mid'} />
            ) : (
              <Icon name={s.icon} size={13} />
            )}
            <span>{s.label}</span>
            <span className="hidden max-w-[220px] truncate font-normal text-ink-dim sm:inline">
              {s.detail}
            </span>
          </button>
        </li>
      ))}
    </ol>
  )
}
