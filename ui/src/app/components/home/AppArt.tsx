/* ------------------------------------------------------------------ *
 * A drawing for each app.
 *
 * Nothing may load from a network here, so these are drawn rather than
 * fetched — which is the better answer anyway: stock developer imagery
 * would say nothing about what these three things actually do, and would
 * look like every other tool.
 *
 * Each one draws the shape of its app's output. A page, a claim joined
 * to the source that backs it, two readings with a line between them.
 * Hairlines and one accent, so they read as plate drawings rather than
 * icons — and the accent always falls on the thing the app is for.
 * ------------------------------------------------------------------ */

const SVG = 'h-full w-full'
const BOX = '0 0 120 64'

/** Documentation — sheets, and one of them written. */
export function DocumentationArt() {
  return (
    <svg viewBox={BOX} className={SVG} fill="none" aria-hidden>
      {/* Two unwritten sheets behind. */}
      <g className="text-rule" stroke="currentColor" strokeWidth="1">
        <rect x="30" y="8" width="40" height="46" />
        <rect x="36" y="11" width="40" height="46" fill="var(--panel)" />
      </g>

      {/* The written one. */}
      <rect
        x="42"
        y="14"
        width="40"
        height="46"
        fill="var(--panel)"
        className="text-ink"
        stroke="currentColor"
        strokeWidth="1.2"
      />
      <rect x="48" y="20" width="17" height="3.5" className="text-hot" fill="currentColor" />
      <g className="text-rule" stroke="currentColor" strokeWidth="1.5" strokeLinecap="square">
        <path d="M48 30h28M48 36h28M48 42h20M48 48h24" />
      </g>
    </svg>
  )
}

/** Ask the code — a claim, joined to the evidence under it. */
export function AskArt() {
  return (
    <svg viewBox={BOX} className={SVG} fill="none" aria-hidden>
      {/* The question. */}
      <rect
        x="16"
        y="8"
        width="52"
        height="20"
        fill="var(--panel)"
        className="text-ink"
        stroke="currentColor"
        strokeWidth="1.2"
      />
      <g className="text-rule" stroke="currentColor" strokeWidth="1.5" strokeLinecap="square">
        <path d="M23 16h30M23 21h20" />
      </g>

      {/* The citation, drawn as a join rather than a footnote — the point is
          that it resolves to something. */}
      <path
        d="M30 28v12h24"
        className="text-hot"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeDasharray="3 2.5"
      />
      <path d="M52 37.5l4 2.5-4 2.5z" className="text-hot" fill="currentColor" />

      {/* The evidence. */}
      <rect
        x="56"
        y="32"
        width="48"
        height="24"
        fill="var(--panel)"
        className="text-ink"
        stroke="currentColor"
        strokeWidth="1.2"
      />
      <rect x="62" y="38" width="14" height="3" className="text-hot" fill="currentColor" />
      <g className="text-rule" stroke="currentColor" strokeWidth="1.5" strokeLinecap="square">
        <path d="M62 45h30M62 50h22" />
      </g>
    </svg>
  )
}

/** What changed — two readings of one repository, and the line between them. */
export function DriftArt() {
  return (
    <svg viewBox={BOX} className={SVG} fill="none" aria-hidden>
      {/* The earlier reading. Set back and lighter: it is the one being compared
          against, not the one you are looking at. */}
      <rect
        x="10"
        y="12"
        width="40"
        height="42"
        fill="var(--panel)"
        className="text-rule"
        stroke="currentColor"
        strokeWidth="1"
      />
      <g className="text-rule" stroke="currentColor" strokeWidth="1.5" strokeLinecap="square">
        <path d="M16 22h26M16 28h20M16 40h26M16 46h18" />
      </g>
      {/* A line that is gone in the later reading — struck rather than absent, so
          the drawing says "removed" rather than "shorter". */}
      <path d="M16 34h22" className="text-rule" stroke="currentColor" strokeWidth="1.5" />
      <path d="M14 34h26" className="text-ink" stroke="currentColor" strokeWidth="0.9" />

      {/* Between the two: the comparison itself. */}
      <path
        d="M52 33h12"
        className="text-hot"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeDasharray="3 2.5"
      />
      <path d="M62 30.5l4 2.5-4 2.5z" className="text-hot" fill="currentColor" />

      {/* The later reading, forward and drawn in full. */}
      <rect
        x="70"
        y="8"
        width="40"
        height="42"
        fill="var(--panel)"
        className="text-ink"
        stroke="currentColor"
        strokeWidth="1.2"
      />
      <g className="text-rule" stroke="currentColor" strokeWidth="1.5" strokeLinecap="square">
        <path d="M76 18h26M76 24h20M76 36h22" />
      </g>
      {/* What arrived. The one accent, on the one thing this app exists to show. */}
      <rect x="76" y="28.5" width="24" height="3.5" className="text-hot" fill="currentColor" />
      <rect x="76" y="41" width="16" height="3.5" className="text-hot" fill="currentColor" />
    </svg>
  )
}

/** Drawn by app id, so an app with no drawing simply has none. */
export const APP_ART: Record<string, () => React.ReactElement> = {
  documentation: DocumentationArt,
  ask: AskArt,
  drift: DriftArt,
}
