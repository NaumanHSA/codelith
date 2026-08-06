import { useMemo } from 'react'
import { collapseDiff, diffLines, diffStat } from '../../lib/site'

/* ------------------------------------------------------------------ *
 * What the last rewrite changed.
 *
 * A regenerated page arriving as a fresh blob asks the reader to spot
 * the difference by reading it all again, which nobody does. This is
 * the difference between a generator and a review workflow.
 * ------------------------------------------------------------------ */

export default function PageDiff({
  before,
  after,
  onClose,
}: {
  before: string
  after: string
  onClose: () => void
}) {
  const lines = useMemo(() => diffLines(before, after), [before, after])
  const rows = useMemo(() => collapseDiff(lines), [lines])
  const { added, removed } = useMemo(() => diffStat(lines), [lines])

  return (
    <section className="plate">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-rule bg-sunk/60 px-3 py-2">
        <span className="tag text-hot-ink">DIFF</span>
        <h2 className="text-[11.5px] font-semibold tracking-tight text-ink">
          What the last rewrite changed
        </h2>
        <span className="tag text-ok">+{added}</span>
        <span className="tag text-bad">−{removed}</span>
        <button onClick={onClose} className="tag ml-auto text-ink-dim hover:text-ink">
          show the page
        </button>
      </header>

      {added + removed === 0 ? (
        <p className="px-3 py-3 text-[11.5px] text-ink-mid">
          The rewrite produced the same text.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <pre className="min-w-full font-mono text-[11px] leading-[1.6]">
            {rows.map((row, i) =>
              row === null ? (
                <div key={`gap-${i}`} className="bg-sunk/60 px-3 py-[3px] text-ink-dim">
                  ⋯
                </div>
              ) : (
                <div
                  key={i}
                  className={`px-3 whitespace-pre-wrap ${
                    row.op === 'add'
                      ? 'bg-ok-wash text-ink'
                      : row.op === 'remove'
                        ? 'bg-bad-wash text-ink-mid line-through decoration-bad/40'
                        : 'text-ink-dim'
                  }`}
                >
                  <span className="mr-2 inline-block w-2 select-none text-ink-dim">
                    {row.op === 'add' ? '+' : row.op === 'remove' ? '−' : ' '}
                  </span>
                  {row.text || ' '}
                </div>
              ),
            )}
          </pre>
        </div>
      )}
    </section>
  )
}
