/* ------------------------------------------------------------------ *
 * How much of the model's context this conversation has spent.
 *
 * A ring rather than a bar because it belongs beside the send button,
 * where there is height but no width. The number underneath it is the
 * whole point — a ring alone says "some", and the question a reader is
 * actually asking is "can I keep going".
 *
 * It never blocks sending. Token counts are an approximation on both
 * sides, and a control that refuses a message because of an estimate
 * is worse than one that lets a long conversation get trimmed.
 * ------------------------------------------------------------------ */

const SIZE = 20
const STROKE = 2.5
const RADIUS = (SIZE - STROKE) / 2
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

export function ContextWheel({
  used,
  total,
}: {
  used: number
  total: number
}) {
  if (!total) return null

  const fraction = Math.min(used / total, 1)
  const pct = Math.round(fraction * 100)

  // Amber and red are earned, not decorative: below three quarters there is
  // nothing for the reader to do, so the ring stays quiet.
  const tone =
    fraction >= 0.9 ? 'text-bad' : fraction >= 0.75 ? 'text-warn' : 'text-ink-dim'

  return (
    <span
      className={`flex items-center gap-1.5 ${tone}`}
      title={`${used.toLocaleString()} of ${total.toLocaleString()} tokens used in this conversation`}
    >
      <svg width={SIZE} height={SIZE} className="-rotate-90" aria-hidden>
        <circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={RADIUS}
          fill="none"
          strokeWidth={STROKE}
          className="stroke-rule"
        />
        <circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={RADIUS}
          fill="none"
          strokeWidth={STROKE}
          strokeDasharray={CIRCUMFERENCE}
          strokeDashoffset={CIRCUMFERENCE * (1 - fraction)}
          strokeLinecap="round"
          className="stroke-current transition-[stroke-dashoffset] duration-300"
        />
      </svg>
      <span className="text-[10px] tabular-nums">{pct}%</span>
    </span>
  )
}
