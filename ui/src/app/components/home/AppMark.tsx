/* ------------------------------------------------------------------ *
 * The same three apps, at badge size.
 *
 * `AppArt` is a 120×64 plate drawing and it works where it was built
 * for: Home, where a card has a band of space above the words. Reusing
 * it on the codebase page — ghosted into a corner at 14% and clipped by
 * the card — produced fragments of rectangles that read as a rendering
 * fault rather than as artwork. A drawing scaled past what it was drawn
 * for stops being a drawing.
 *
 * So these are drawn for 24px instead: two or three shapes, one accent,
 * no detail that survives only at four times the size. They sit in the
 * card's title row where an icon belongs, rather than hiding behind the
 * text and hoping to be noticed.
 * ------------------------------------------------------------------ */

const BOX = '0 0 24 24'
const SVG = 'h-full w-full'

/** Documentation — sheets, and the written one in front. */
export function DocumentationMark() {
  return (
    <svg viewBox={BOX} className={SVG} fill="none" aria-hidden>
      <rect
        x="3.5"
        y="2.5"
        width="12"
        height="16"
        className="text-rule"
        stroke="currentColor"
        strokeWidth="1.3"
      />
      <rect
        x="7.5"
        y="5.5"
        width="12"
        height="16"
        fill="var(--panel)"
        className="text-ink"
        stroke="currentColor"
        strokeWidth="1.3"
      />
      <path
        d="M10.5 10h6"
        className="text-hot"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="square"
      />
      <path
        d="M10.5 13.5h6M10.5 17h4"
        className="text-rule"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="square"
      />
    </svg>
  )
}

/** Ask the code — a claim, and the source it resolves to. */
export function AskMark() {
  return (
    <svg viewBox={BOX} className={SVG} fill="none" aria-hidden>
      <rect
        x="2.5"
        y="3"
        width="12"
        height="7"
        fill="var(--panel)"
        className="text-ink"
        stroke="currentColor"
        strokeWidth="1.3"
      />
      {/* The join is the point: an answer that reaches its evidence. */}
      <path
        d="M6 10v6h4"
        className="text-hot"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeDasharray="2.5 2"
      />
      <rect
        x="10"
        y="13"
        width="11.5"
        height="8"
        fill="var(--panel)"
        className="text-ink"
        stroke="currentColor"
        strokeWidth="1.3"
      />
      <path
        d="M13 17h5.5"
        className="text-hot"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="square"
      />
    </svg>
  )
}

/** What changed — two readings, offset, and what arrived in the later one. */
export function DriftMark() {
  return (
    <svg viewBox={BOX} className={SVG} fill="none" aria-hidden>
      {/* The earlier reading, set back. */}
      <rect
        x="2.5"
        y="5.5"
        width="10"
        height="15"
        className="text-rule"
        stroke="currentColor"
        strokeWidth="1.3"
      />
      <path
        d="M5 10h5"
        className="text-rule"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="square"
      />
      {/* The later one, forward, with the line that appeared in it. */}
      <rect
        x="10.5"
        y="2.5"
        width="11"
        height="15"
        fill="var(--panel)"
        className="text-ink"
        stroke="currentColor"
        strokeWidth="1.3"
      />
      <path
        d="M13.5 7h5"
        className="text-rule"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="square"
      />
      <path
        d="M13.5 11h5"
        className="text-hot"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="square"
      />
      <path
        d="M13.5 14.5h3"
        className="text-hot"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="square"
      />
    </svg>
  )
}

/** By app id, so an app with no mark simply has none. */
export const APP_MARK: Record<string, () => React.ReactElement> = {
  documentation: DocumentationMark,
  ask: AskMark,
  drift: DriftMark,
}
