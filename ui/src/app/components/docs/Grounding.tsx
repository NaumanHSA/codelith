/**
 * What this page could not ground.
 *
 * For AI-written documentation this is the part that makes the rest trustable.
 * Without it every sentence carries the same weight, and a reader has no way to tell
 * the paragraph derived from a function signature from the one a model filled in
 * because the section looked thin.
 *
 * Deliberately not a badge on its own. A score with nothing behind it is decoration —
 * the value is opening the specific paragraph that named something the codebase does
 * not contain, which is why the unknown identifiers are listed verbatim.
 */

import { useState } from 'react'
import type { SitePageDetail } from '../../lib/types'

export function Grounding({ page }: { page: SitePageDetail }) {
  const [open, setOpen] = useState(false)
  const g = page.grounding

  // Absent on pages written before the check existed, and on anything from the
  // legacy pipeline, which has no knowledge base to check against. Saying nothing
  // is better than showing a zero that reads as a failure.
  if (!g || !g.paragraphs) return null

  const checked = g.grounded + g.unverified
  if (!checked) return null

  const pct = Math.round(g.score * 100)
  const tone =
    pct >= 90 ? 'text-ok' : pct >= 70 ? 'text-ink-dim' : 'text-warn'

  return (
    <div className="mt-6 border-t border-rule pt-4">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="flex w-full items-center justify-between gap-3 text-left"
        aria-expanded={open}
      >
        <span className="tag text-ink-dim">Grounding</span>
        <span className="flex items-center gap-3 text-xs">
          <span className={tone}>
            {pct}% of {checked} checked paragraph{checked === 1 ? '' : 's'}
          </span>
          {!!g.unverified && (
            <span className="text-warn">
              {g.unverified} unverified
            </span>
          )}
          <span className="text-ink-dim">{open ? '−' : '+'}</span>
        </span>
      </button>

      {open && (
        <div className="mt-3 space-y-3">
          <p className="text-xs text-ink-dim">
            Each paragraph is checked for identifiers — symbols, files, packages —
            against what analysis found in the codebase. This proves a paragraph
            <em> refers</em> to things that exist; it does not prove what it says
            about them is right.
            {!!g.unchecked && (
              <> {g.unchecked} paragraph{g.unchecked === 1 ? '' : 's'} named nothing
              checkable and {g.unchecked === 1 ? 'is' : 'are'} not counted either way.</>
            )}
          </p>

          {g.problems.length === 0 ? (
            <p className="text-xs text-ok">Every checkable paragraph resolved.</p>
          ) : (
            <ul className="space-y-2">
              {g.problems.map(p => (
                <li key={p.paragraph} className="border-l-2 border-warn pl-3">
                  <div className="flex flex-wrap gap-1">
                    {p.unknown.map(name => (
                      <code
                        key={name}
                        className="rounded bg-sunk px-1 text-[11px] text-warn"
                      >
                        {name}
                      </code>
                    ))}
                  </div>
                  <p className="mt-1 text-xs text-ink-dim">{p.excerpt}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
