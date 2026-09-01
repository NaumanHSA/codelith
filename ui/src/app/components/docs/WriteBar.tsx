import { Button } from '../ui'

/* ------------------------------------------------------------------ *
 * What happens to the pages you ticked.
 *
 * Pinned to the viewport rather than sitting at the end of the page.
 * The control it replaces lived at the bottom of a two-screen scroll,
 * which meant the option nobody could find was the option nobody used.
 *
 * It carries no format picker. Format is a property of leaving — it is
 * chosen on export, from the same stored markdown, so nothing about
 * writing has to know where the text is eventually going.
 * ------------------------------------------------------------------ */

export default function WriteBar({
  count,
  review,
  onReview,
  onWrite,
  onClear,
  busy,
}: {
  count: number
  review: boolean
  onReview: (v: boolean) => void
  onWrite: () => void
  onClear: () => void
  busy: boolean
}) {
  if (count === 0) return null

  return (
    <div className="sticky bottom-0 z-20 -mx-1 mt-5 border-t border-hot-edge bg-panel/95 backdrop-blur">
      <div className="flex flex-wrap items-center gap-3 px-3 py-2.5">
        <span className="text-[12px] font-semibold text-ink">
          {count} page{count === 1 ? '' : 's'} selected
        </span>
        <button
          onClick={onClear}
          className="tag text-ink-dim transition-colors hover:text-hot-ink"
        >
          clear
        </button>

        <label
          className="flex cursor-pointer items-center gap-1.5 select-none"
          title="Pages that fail the fact check are held for you to read before anything is published."
        >
          <input
            type="checkbox"
            checked={review}
            onChange={e => onReview(e.target.checked)}
            className="accent-[var(--hot)]"
          />
          <span className="tag text-ink-dim">hold flagged pages for review</span>
        </label>

        <span className="tag text-ink-dim">
          roughly {Math.max(2, count * 3)} min on a local model
        </span>

        <Button variant="hot" className="ml-auto" disabled={busy} onClick={onWrite}>
          {busy ? 'starting…' : review ? `Write ${count} for review →` : `Write ${count} →`}
        </Button>
      </div>
    </div>
  )
}
