import { Button } from '../ui'
import { DepthPicker, ReviewToggle } from './WriteOptions'
import type { Depth } from '../../lib/types'

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
 *
 * The controls themselves live in `WriteOptions`, because the button on a
 * single unwritten page starts the same kind of run and has to offer the
 * same choices.
 * ------------------------------------------------------------------ */

export default function WriteBar({
  count,
  rewrites,
  review,
  onReview,
  depth,
  onDepth,
  onWrite,
  onClear,
  busy,
}: {
  count: number
  /** How many of the selected pages already have text. Counted separately because
   *  the run replaces them, and a bar that says "Write 4" when one of the four is
   *  finished work is a bar that destroys something quietly. */
  rewrites: number
  review: boolean
  onReview: (v: boolean) => void
  depth: Depth
  onDepth: (v: Depth) => void
  onWrite: () => void
  onClear: () => void
  busy: boolean
}) {
  if (count === 0) return null

  const fresh = count - rewrites
  const action = busy
    ? 'starting…'
    : rewrites === count
      ? `Replace ${rewrites} →`
      : rewrites > 0
        ? `Write ${fresh}, replace ${rewrites} →`
        : review
          ? `Write ${count} for review →`
          : `Write ${count} →`

  return (
    // Separated from the list above it rather than merely stuck to the bottom. It
    // used to be one hairline against the same panel colour as everything else, at
    // the end of a long scroll of rows that also carry hairlines — so the one control
    // that acts on your selection read as another row. The gap, the heavier edge and
    // the wash are all doing the same job: this is not part of the list.
    <div className="sticky bottom-0 z-20 -mx-1 mt-10 border-2 border-hot bg-hot-wash shadow-[0_-6px_24px_-8px_rgba(0,0,0,0.25)]">
      <div className="flex flex-wrap items-center gap-3 border-b border-hot-edge px-3 py-2.5">
        <span className="text-[12.5px] font-semibold text-hot-ink">
          {count} page{count === 1 ? '' : 's'} selected
        </span>
        <button
          onClick={onClear}
          className="tag text-ink-mid transition-colors hover:text-hot-ink"
        >
          clear
        </button>

        <ReviewToggle value={review} onChange={onReview} disabled={busy} />

        <span className="tag text-ink-dim">
          roughly {Math.max(2, count * 3)} min on a local model
        </span>

        <Button variant="hot" className="ml-auto" disabled={busy} onClick={onWrite}>
          {action}
        </Button>
      </div>

      {rewrites > 0 && (
        // Named, not counted. "1 will be replaced" is a number; saying which pages is
        // what lets somebody notice they ticked the wrong row.
        <p className="border-b border-hot-edge bg-warn-wash px-3 py-1.5 font-sans text-[11.5px] text-warn">
          {rewrites} selected page{rewrites === 1 ? ' is' : 's are'} already written.
          Writing {rewrites === 1 ? 'it' : 'them'} again discards the current text.
        </p>
      )}

      <div className="px-3 py-2">
        <DepthPicker value={depth} onChange={onDepth} disabled={busy} />
      </div>
    </div>
  )
}
