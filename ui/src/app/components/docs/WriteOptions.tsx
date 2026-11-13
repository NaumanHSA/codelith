import type { Depth } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * The two choices you make before anything is written.
 *
 * One component because there are two places you can start a run — the
 * selection bar over the whole site, and the button on a single unwritten
 * page — and they used to offer different things. The bar had the review
 * toggle; the page had nothing, so writing one page silently inherited
 * whatever the bar had been left on. An option you cannot see is not an
 * option, it is a hidden default.
 *
 * Depth is three named levels rather than a word count. Nobody knows
 * whether they want 240 words or 300; they know whether they want to be
 * reminded how something works or to implement against it.
 * ------------------------------------------------------------------ */

export const DEPTHS: { id: Depth; label: string; blurb: string }[] = [
  {
    id: 'concise',
    label: 'Concise',
    blurb: 'What it is, how to use it, and the one thing people get wrong.',
  },
  {
    id: 'standard',
    label: 'Standard',
    blurb: 'The working middle. Enough to use the code without reading it.',
  },
  {
    id: 'detailed',
    label: 'Detailed',
    blurb: 'A reference to implement against: parameters, failures, examples.',
  },
]

export function DepthPicker({
  value,
  onChange,
  disabled,
}: {
  value: Depth
  onChange: (v: Depth) => void
  disabled?: boolean
}) {
  const current = DEPTHS.find(d => d.id === value) ?? DEPTHS[1]
  return (
    <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
      <span className="text-[12.5px] font-medium text-ink-mid">Depth</span>
      <div className="flex gap-0.5 rounded-lg border border-rule bg-paper p-[3px]">
        {DEPTHS.map(d => (
          <button
            key={d.id}
            type="button"
            disabled={disabled}
            title={d.blurb}
            onClick={() => onChange(d.id)}
            aria-pressed={d.id === value}
            className={`rounded-md px-2.5 py-1 text-[12.5px] font-medium transition-colors disabled:cursor-not-allowed ${
              d.id === value
                ? 'bg-sunk text-ink shadow-[inset_0_0_0_1px_var(--line-2)]'
                : 'text-ink-mid hover:text-ink'
            }`}
          >
            {d.label}
          </button>
        ))}
      </div>
      {/* The blurb rather than a tooltip alone: the difference between these is the
          whole decision, and a tooltip is not readable on a touch device. */}
      <span className="text-[12.5px] text-ink-dim">{current.blurb}</span>
    </div>
  )
}

export function ReviewToggle({
  value,
  onChange,
  disabled,
}: {
  value: boolean
  onChange: (v: boolean) => void
  disabled?: boolean
}) {
  return (
    <label
      className="flex cursor-pointer items-center gap-1.5 select-none"
      title="Pages that fail the fact check are held for you to read before anything is published."
    >
      <input
        type="checkbox"
        checked={value}
        disabled={disabled}
        onChange={e => onChange(e.target.checked)}
        className="accent-[var(--hot)]"
      />
      <span className="text-[12.5px] text-ink-mid">Hold pages QA flags for my review before they are published</span>
    </label>
  )
}

/** Both, stacked. Used wherever a run can be started. */
export default function WriteOptions({
  depth,
  onDepth,
  review,
  onReview,
  disabled,
}: {
  depth: Depth
  onDepth: (v: Depth) => void
  review: boolean
  onReview: (v: boolean) => void
  disabled?: boolean
}) {
  return (
    <div className="flex flex-col gap-2">
      <DepthPicker value={depth} onChange={onDepth} disabled={disabled} />
      <ReviewToggle value={review} onChange={onReview} disabled={disabled} />
    </div>
  )
}
