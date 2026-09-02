import { useEffect, useState } from 'react'
import type { Heading } from '../../lib/site'

/* ------------------------------------------------------------------ *
 * The right-hand table of contents: headings within the open page,
 * with the one currently on screen highlighted.
 * ------------------------------------------------------------------ */

export default function Toc({
  headings,
  className = 'hidden xl:block',
  top = 'top-4',
}: {
  headings: Heading[]
  /** Which breakpoint the rail appears at — the two readers have different widths. */
  className?: string
  /** Sticky offset, which depends on how tall the header above it is. */
  top?: string
}) {
  const [active, setActive] = useState<string | null>(null)

  useEffect(() => {
    if (!headings.length) return
    const obs = new IntersectionObserver(
      entries => {
        const visible = entries
          .filter(e => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
        if (visible[0]) setActive(visible[0].target.id)
      },
      { rootMargin: '-64px 0px -70% 0px' },
    )
    for (const h of headings) {
      const el = document.getElementById(h.id)
      if (el) obs.observe(el)
    }
    return () => obs.disconnect()
  }, [headings])

  if (headings.length < 2) return null

  return (
    <nav className={className}>
      <div className={`sticky ${top}`}>
        <span className="tag mb-2 block text-ink-dim">On this page</span>
        <ul className="border-l border-rule">
          {/* Keyed by position, not by id. Two headings with the same text produce the
              same anchor id — `## Entry Points` twice in one page is ordinary prose,
              not a mistake — and `id + text` collides for exactly that case, which
              React reports as duplicate keys. Position is unique by construction.
              (The anchors themselves still collide: both link to the first. That is a
              real bug, and fixing it means agreeing a de-duplication rule between
              `anchorId` here and `anchor_id` in `codelith/knowledge/sites.py`, which
              the linker also validates against.) */}
          {headings.map((h, i) => (
            <li key={`${i}-${h.id}`}>
              <a
                href={`#${h.id}`}
                onClick={e => {
                  e.preventDefault()
                  document.getElementById(h.id)?.scrollIntoView({ behavior: 'smooth' })
                }}
                style={{ paddingLeft: `${(h.depth - 1) * 9 + 9}px` }}
                className={`block border-l-2 py-[3px] pr-1 text-[11px] leading-snug transition-colors ${
                  active === h.id
                    ? 'border-hot text-hot-ink'
                    : 'border-transparent text-ink-dim hover:text-ink'
                }`}
              >
                {h.text}
              </a>
            </li>
          ))}
        </ul>
      </div>
    </nav>
  )
}
