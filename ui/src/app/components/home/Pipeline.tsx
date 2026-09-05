import { useEffect, useState } from 'react'
import type { AppCatalogItem } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * Read once, use many times — drawn rather than asserted.
 *
 * Home said this in a sentence and then showed three cards that looked
 * like three separate products. The claim the whole architecture rests
 * on is that they are not separate: one pass over the repository builds
 * one knowledge base, and everything else reads it. A row of equal cards
 * cannot show that, because equal boxes have no order and no source.
 *
 * The design is one the user brought in, and it is followed as given:
 * plates with a solid badge overhanging the corner, marching dashed
 * connectors, a hub that breathes, a staged reveal on mount and then a
 * highlight travelling the pipeline for as long as the page is open.
 * Two things are ours rather than the draft's, both required here:
 *
 *   Colour comes from the theme, never from a literal. The draft's
 *   #E85A26 is one orange used for lines and for text alike; the studio
 *   splits them — `--hot` for graphics, `--hot-ink` for anything read as
 *   text, because #ff6b35 fails AA on paper. Hardcoding would also make
 *   this the one page a dark variant could not reach.
 *
 *   Fonts are the bundled ones. The draft pulled JetBrains Mono and
 *   Inter from Google; both are already in `src/assets/fonts` behind
 *   `--font-mono` and `--font-sans`, and the product's claim is that
 *   nothing leaves the machine.
 *
 * Geometry is arithmetic, not percentages. Plates share the row and the
 * gap between them is what is fixed, so a column's centre is a `calc`
 * over the row's own width — which puts every drop on its column at any
 * width, and still lands when the registry carries fewer than three
 * apps. Percentages only work for plates of a fixed width, and a fixed
 * width in a container this wide just spends the difference on gaps.
 * ------------------------------------------------------------------ */

/** The plate metrics the whole layout is measured against.
 *
 *  Plates share the row rather than holding a fixed 240px, because a fixed width in
 *  a container this wide spends the difference on gaps — the same air, moved. They
 *  grow instead, and the gap between them is what stays fixed. Heights are floors,
 *  not fixed: the row stretches every plate to its tallest, so a plate is as tall as
 *  it needs to be and no taller. */
const GAP = 68
const NODE_MIN_H = 150
const FEATURE_MIN_H = 210

/** A marching dash, horizontal and vertical. Painted as a repeating gradient on an
 *  HTML rule rather than an SVG stroke, so it can be laid out with the cards. */
const FLOW_X: React.CSSProperties = {
  height: 2,
  backgroundImage:
    'repeating-linear-gradient(90deg, var(--hot) 0, var(--hot) 5px, transparent 5px, transparent 9px)',
  animation: 'pipe-dash-x 0.65s linear infinite',
}
const FLOW_Y: React.CSSProperties = {
  width: 2,
  backgroundImage:
    'repeating-linear-gradient(180deg, var(--hot) 0, var(--hot) 5px, transparent 5px, transparent 9px)',
  animation: 'pipe-dash-y 0.65s linear infinite',
}

/** The faint plotting grid inside a plate — cool on the reading side, warm on the
 *  writing side, which is the only cue that separates them at a glance. */
const INNER_GRID: React.CSSProperties = {
  backgroundImage:
    'linear-gradient(var(--grid-line) 1px, transparent 1px), linear-gradient(90deg, var(--grid-line) 1px, transparent 1px)',
  backgroundSize: '16px 16px',
}
const INNER_GRID_WARM: React.CSSProperties = {
  backgroundImage:
    'linear-gradient(color-mix(in srgb, var(--hot) 5%, transparent) 1px, transparent 1px), linear-gradient(90deg, color-mix(in srgb, var(--hot) 5%, transparent) 1px, transparent 1px)',
  backgroundSize: '16px 16px',
}

const MONO: React.CSSProperties = { fontFamily: 'var(--font-mono)' }

/* ── Icons ─────────────────────────────────────────────────────────── */
/* Stroke is set by `.pipe-badge svg`, so each glyph inherits the badge's cream. */

const ICON = {
  width: 30,
  height: 30,
  viewBox: '0 0 24 24',
  fill: 'none',
  strokeWidth: 1.4,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
} as const

function RepoIcon() {
  return (
    <svg {...ICON}>
      <rect x="3" y="3" width="18" height="18" />
      <path d="M9 3v18" />
      <path d="M3 9h6" />
      <path d="M3 15h6" />
      <path d="M13 8h5M13 12h5M13 16h3" strokeOpacity={0.4} />
    </svg>
  )
}

function AnalysisIcon() {
  return (
    <svg {...ICON}>
      <circle cx="11" cy="11" r="8" />
      <path d="m21 21-4.35-4.35" />
      <path d="M8 11h6" strokeOpacity={0.5} />
      <path d="M11 8v6" strokeOpacity={0.5} />
    </svg>
  )
}

function KBIcon() {
  return (
    <svg {...ICON}>
      <ellipse cx="12" cy="5" rx="9" ry="3" />
      <path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3" />
      <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
    </svg>
  )
}

function DocsIcon() {
  return (
    <svg {...ICON}>
      <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
      <polyline points="14,2 14,8 20,8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
      <line x1="10" y1="9" x2="8" y2="9" />
    </svg>
  )
}

function AskIcon() {
  return (
    <svg {...ICON}>
      <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
      <line x1="9" y1="10" x2="15" y2="10" strokeOpacity={0.5} />
      <line x1="9" y1="14" x2="12" y2="14" strokeOpacity={0.5} />
    </svg>
  )
}

function DriftIcon() {
  return (
    <svg {...ICON}>
      <circle cx="6" cy="6" r="3" />
      <circle cx="6" cy="18" r="3" />
      <line x1="6" y1="9" x2="6" y2="15" />
      <path d="M9 6h12M9 18h12" />
      <polyline points="17,3 21,6 17,9" />
      <polyline points="17,15 21,18 17,21" />
    </svg>
  )
}

/* ── Pieces ────────────────────────────────────────────────────────── */

/** The solid badge overhanging a plate's top-right corner. */
function Badge({
  icon,
  hub,
  active,
}: {
  icon: React.ReactNode
  hub?: boolean
  active?: boolean
}) {
  return (
    <div
      className={`pipe-badge${active ? ' is-active' : ''}`}
      style={{
        position: 'absolute',
        top: -18,
        right: -18,
        zIndex: 3,
        width: 50,
        height: 50,
        borderRadius: 10,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: hub ? 'var(--hot)' : 'var(--ink)',
      }}
    >
      {icon}
    </div>
  )
}

/** `01 · CODEBASE` — the eyebrow every plate opens with. */
function Eyebrow({ step, label, hot }: { step: string; label: string; hot: boolean }) {
  return (
    <div
      style={{
        ...MONO,
        fontSize: 9.5,
        letterSpacing: '0.1em',
        color: hot ? 'var(--hot-ink)' : 'var(--ink-dim)',
        marginBottom: 14,
        paddingRight: 44,
        display: 'flex',
        gap: 6,
        alignItems: 'center',
      }}
    >
      <span style={{ fontWeight: 600 }}>{step}</span>
      <span style={{ opacity: 0.35 }}>·</span>
      <span>{label}</span>
    </div>
  )
}

function Title({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        ...MONO,
        fontSize: 13.5,
        fontWeight: 600,
        color: 'var(--ink)',
        marginBottom: 8,
        lineHeight: 1.35,
      }}
    >
      {children}
    </div>
  )
}

function Body({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontSize: 11.5, color: 'var(--ink-mid)', lineHeight: 1.65 }}>{children}</div>
  )
}

/** A stage on the reading side. The knowledge base is the hub: warm ground, a hot
 *  cap along its top edge, and a slow glow while the pulse is elsewhere. */
function Node({
  step,
  label,
  title,
  description,
  icon,
  hub,
  visible,
  active,
}: {
  step: string
  label: string
  title: string
  description: string
  icon: React.ReactNode
  hub?: boolean
  visible: boolean
  active: boolean
}) {
  return (
    <div
      className="pipe-card"
      style={{
        flex: '1 1 0',
        minWidth: 0,
        minHeight: NODE_MIN_H,
        display: 'flex',
        flexDirection: 'column',
        border: `1.5px solid ${active || hub ? 'var(--hot)' : 'var(--ink)'}`,
        backgroundColor: hub ? 'var(--hot-wash)' : 'var(--panel)',
        ...(hub ? INNER_GRID_WARM : INNER_GRID),
        padding: '20px 22px 18px',
        position: 'relative',
        opacity: visible ? 1 : 0,
        transform: active
          ? 'translateY(-4px) scale(1.02)'
          : visible
            ? 'translateY(0)'
            : 'translateY(10px)',
        boxShadow: active
          ? '0 16px 32px -16px color-mix(in srgb, var(--hot) 50%, transparent)'
          : undefined,
        animation: hub && !active ? 'pipe-hub-glow 3.5s ease-in-out infinite' : undefined,
      }}
    >
      <div className="pipe-wash" />
      <Badge icon={icon} hub={hub} active={active} />
      {hub && (
        <div
          style={{
            position: 'absolute',
            top: -1.5,
            left: -1.5,
            right: -1.5,
            height: 3,
            backgroundColor: 'var(--hot)',
          }}
        />
      )}
      <Eyebrow step={step} label={label} hot={!!hub} />
      <Title>{title}</Title>
      <Body>{description}</Body>
      <div
        className="pipe-rule"
        style={{
          marginTop: 'auto',
          height: hub ? 2 : 1,
          width: 24,
          backgroundColor: hub ? 'var(--hot)' : 'var(--rule)',
        }}
      />
    </div>
  )
}

/** A plate on the writing side. Dashed until the pulse reaches it — these are things
 *  the reading makes possible, not stages it passes through. */
function Feature({
  step,
  label,
  title,
  description,
  icon,
  preview,
  visible,
  active,
}: {
  step: string
  label: string
  title: string
  description: string
  icon: React.ReactNode
  preview: React.ReactNode
  visible: boolean
  active: boolean
}) {
  return (
    <div
      className="pipe-card"
      style={{
        flex: '1 1 0',
        minWidth: 0,
        minHeight: FEATURE_MIN_H,
        display: 'flex',
        flexDirection: 'column',
        border: `1.5px ${active ? 'solid' : 'dashed'} var(--hot)`,
        backgroundColor: 'var(--hot-wash)',
        ...INNER_GRID_WARM,
        padding: '20px 22px 18px',
        position: 'relative',
        opacity: visible ? 1 : 0,
        transform: active
          ? 'translateY(-4px) scale(1.02)'
          : visible
            ? 'translateY(0)'
            : 'translateY(10px)',
        boxShadow: active
          ? '0 16px 32px -16px color-mix(in srgb, var(--hot) 50%, transparent)'
          : undefined,
      }}
    >
      <div className="pipe-wash" />
      <Badge icon={icon} hub active={active} />
      <Eyebrow step={step} label={label} hot />
      <Title>{title}</Title>
      <Body>{description}</Body>
      <div style={{ marginTop: 12 }}>{preview}</div>
      <div
        className="pipe-rule"
        style={{ marginTop: 'auto', height: 2, width: 28, backgroundColor: 'var(--hot)' }}
      />
    </div>
  )
}

/** The hairline each preview sits under. */
const PREVIEW_TOP: React.CSSProperties = {
  paddingTop: 10,
  borderTop: '1px solid color-mix(in srgb, var(--hot) 20%, transparent)',
}

function DocsPreview() {
  return (
    <div style={PREVIEW_TOP}>
      {[
        ['80%', 2.5, 55],
        ['62%', 1.5, 22],
        ['75%', 1.5, 22],
        ['48%', 1.5, 22],
      ].map(([w, h, pct], i) => (
        <div
          key={i}
          style={{
            height: h as number,
            width: w as string,
            backgroundColor: `color-mix(in srgb, var(--hot) ${pct}%, transparent)`,
            marginBottom: 4,
          }}
        />
      ))}
    </div>
  )
}

function AskPreview() {
  return (
    <div style={{ ...PREVIEW_TOP, ...MONO, fontSize: 10 }}>
      <div
        style={{
          color: 'color-mix(in srgb, var(--hot-ink) 85%, transparent)',
          marginBottom: 3,
        }}
      >
        {'>'} how does auth work?
      </div>
      <div style={{ color: 'var(--ink-dim)', lineHeight: 1.55 }}>
        auth starts at middleware/
        <br />
        session.ts, line 42...
        <span
          className="pipe-dash"
          style={{
            display: 'inline-block',
            width: 5,
            height: 10,
            backgroundColor: 'var(--hot)',
            marginLeft: 1,
            opacity: 0.7,
            animation: 'blink 1s step-end infinite',
            verticalAlign: 'middle',
          }}
        />
      </div>
    </div>
  )
}

function DriftPreview() {
  return (
    <div style={{ ...PREVIEW_TOP, ...MONO, fontSize: 10, lineHeight: 1.7 }}>
      <div style={{ color: 'var(--bad)' }}>- getUser(id)</div>
      <div style={{ color: 'var(--ok)' }}>+ fetchUser(id, opts)</div>
      <div style={{ color: 'var(--ink-dim)', fontSize: 9, marginTop: 2 }}>
        +14 / -8 across 3 files
      </div>
    </div>
  )
}

/** The arrow between two stages on the reading side. */
function Arrow({ visible, active }: { visible: boolean; active: boolean }) {
  const glow = active
    ? 'drop-shadow(0 0 4px color-mix(in srgb, var(--hot) 70%, transparent))'
    : undefined
  return (
    <div
      style={{
        flex: `0 0 ${GAP}px`,
        display: 'flex',
        alignItems: 'center',
        opacity: visible ? 1 : 0,
        transition: 'opacity 0.45s ease',
      }}
    >
      <div
        className="pipe-dash"
        style={{
          flex: 1,
          ...FLOW_X,
          height: active ? 3 : 2,
          filter: glow,
          transition: 'height 0.3s ease, filter 0.3s ease',
        }}
      />
      <div
        style={{
          width: 0,
          height: 0,
          borderTop: `${active ? 7 : 5}px solid transparent`,
          borderBottom: `${active ? 7 : 5}px solid transparent`,
          borderLeft: `${active ? 11 : 8}px solid var(--hot)`,
          filter: glow,
          transition: 'border-width 0.3s ease',
        }}
      />
    </div>
  )
}

/**
 * The fan from the knowledge base to the apps.
 *
 * Positioned in `calc` against the card width, not in percentages. A plate's centre
 * is 120px from the row's edge however wide the row is, and the columns between are
 * evenly spread — so every drop lands on its plate at any width, and with any number
 * of apps the registry happens to carry.
 */
function Fan({ count, visible, active }: { count: number; visible: boolean; active: boolean }) {
  /**
   * The centre of column `i`, as a CSS length.
   *
   * The rows lay out as `count` equal plates separated by fixed gaps, so a column is
   * `(100% - gaps) / count` wide and column `i` starts `i` gaps further along. Written
   * out rather than in percentages because percentages only land when the plates are a
   * fixed width — these grow, and the arithmetic has to grow with them.
   */
  const at = (i: number) =>
    `calc((100% - ${(count - 1) * GAP}px) * ${2 * i + 1} / ${2 * count} + ${GAP * i}px)`
  const last = at(count - 1)

  return (
    <div
      style={{
        position: 'relative',
        height: 72,
        filter: active
          ? 'drop-shadow(0 0 4px color-mix(in srgb, var(--hot) 70%, transparent))'
          : undefined,
        transition: 'filter 0.3s ease',
      }}
    >
      {/* Down out of the knowledge base, which shares the last column. */}
      <div
        className="pipe-dash"
        style={{
          position: 'absolute',
          left: last,
          top: 0,
          height: 30,
          opacity: visible ? 1 : 0,
          transition: 'opacity 0.4s ease',
          ...FLOW_Y,
        }}
      />
      {/* Across, from the first column to the last. */}
      <div
        className="pipe-dash"
        style={{
          position: 'absolute',
          left: at(0),
          width: `calc(${last} - ${at(0)})`,
          top: 30,
          opacity: visible ? 1 : 0,
          transition: 'opacity 0.4s ease 80ms',
          ...FLOW_X,
        }}
      />
      {/* And down again, one drop per app — all at once, because they arrive together. */}
      {Array.from({ length: count }, (_, i) => (
        <div
          key={i}
          className="pipe-dash"
          style={{
            position: 'absolute',
            left: at(i),
            top: 30,
            height: 42,
            opacity: visible ? 1 : 0,
            transition: `opacity 0.4s ease ${130 + i * 40}ms`,
            ...FLOW_Y,
          }}
        />
      ))}
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: 6,
          ...MONO,
          fontSize: 9,
          color: 'var(--ink-dim)',
          letterSpacing: '0.14em',
          opacity: visible ? 1 : 0,
          transition: 'opacity 0.5s ease 260ms',
        }}
      >
        READ ONCE
      </div>
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: 26,
          ...MONO,
          fontSize: 9,
          color: 'var(--hot-ink)',
          letterSpacing: '0.14em',
          opacity: visible ? 1 : 0,
          transition: 'opacity 0.5s ease 360ms',
        }}
      >
        WRITE MANY TIMES
      </div>
    </div>
  )
}

/** The apps, in the order they hang off the knowledge base. */
const FEATURES = [
  {
    id: 'documentation',
    step: '04',
    label: 'DOCUMENTATION',
    title: 'Documentation',
    description:
      'Markdown, DOCX, MkDocs, or Docusaurus — written from the reading. Document types emerge from what the code contains.',
    icon: <DocsIcon />,
    preview: <DocsPreview />,
  },
  {
    id: 'ask',
    step: '05',
    label: 'ASK THE CODE',
    title: 'Ask the Code',
    description:
      'Query any aspect of the codebase. Ask about architecture, data flows, a specific module, or how auth works.',
    icon: <AskIcon />,
    preview: <AskPreview />,
  },
  {
    id: 'drift',
    step: '06',
    label: 'CODE DRIFT',
    title: 'What Changed',
    description:
      'Track what changed between any two commits — structure, dependencies, API contracts, and behavior.',
    icon: <DriftIcon />,
    preview: <DriftPreview />,
  },
]

/** When each piece appears on first paint. */
const REVEAL = [120, 420, 740, 1060, 1380, 1700, 2020]
/** How long the travelling highlight rests on each stage once the reveal is done. */
const TRAVEL_MS = 3000

export default function Pipeline({ features }: { features: AppCatalogItem[] | null }) {
  const [phase, setPhase] = useState(0)
  /** Where the highlight is: 0 repository, 1 analysis, 2 knowledge base, 3 the apps. */
  const [active, setActive] = useState(-1)

  useEffect(() => {
    const timers = REVEAL.map((d, i) => setTimeout(() => setPhase(i + 1), d))
    return () => timers.forEach(clearTimeout)
  }, [])

  useEffect(() => {
    if (phase < REVEAL.length) return
    // The CSS stops the dashes and the badge for reduced motion, but the travelling
    // highlight lives here — left running it would go on lifting and scaling plates
    // for as long as the page is open, which is the thing that setting is asking
    // about. The schematic reads fine standing still.
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
    setActive(0)
    const id = setInterval(() => setActive(a => (a + 1) % 4), TRAVEL_MS)
    return () => clearInterval(id)
  }, [phase])

  const v = (n: number) => phase >= n

  // Checked against the registry, so the diagram cannot promise an app the studio
  // does not have — but only once the catalogue has arrived, or all three would
  // blink out and back in behind the reveal.
  const catalogue = features?.length ? new Set(features.map(f => f.id)) : null
  const shown = catalogue ? FEATURES.filter(f => catalogue.has(f.id)) : FEATURES

  return (
    <section
      className="mb-5 border border-rule"
      style={{
        // Prose is sans here, as the draft had it. The studio's body font is the mono
        // one — every other component opts into `font-sans` for prose — and the draft
        // got Inter from an outer wrapper it had as a standalone page and this has not.
        fontFamily: 'var(--font-sans)',
        backgroundColor: 'var(--paper)',
        backgroundImage:
          'linear-gradient(var(--grid-line) 1px, transparent 1px), linear-gradient(90deg, var(--grid-line) 1px, transparent 1px)',
        backgroundSize: '32px 32px',
        padding: '32px',
      }}
    >
      <div style={{ width: '100%' }}>
        <div
          style={{ marginBottom: 26, opacity: v(1) ? 1 : 0, transition: 'opacity 0.6s ease' }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              ...MONO,
              fontSize: 10,
              letterSpacing: '0.13em',
              marginBottom: 16,
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                color: 'var(--hot-ink)',
              }}
            >
              <span style={{ fontSize: 8 }}>◆</span>
              <span>CODELITH — LOCAL-FIRST CODE INTELLIGENCE</span>
            </div>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 5,
                color: 'var(--ink-mid)',
              }}
            >
              <div
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  backgroundColor: 'var(--ok)',
                  flexShrink: 0,
                }}
              />
              <span>RUNS FULLY OFFLINE</span>
            </div>
          </div>

          <div
            style={{
              ...MONO,
              fontSize: 9.5,
              color: 'var(--hot-ink)',
              letterSpacing: '0.15em',
              marginBottom: 10,
            }}
          >
            HOW IT WORKS
          </div>
          <h2
            style={{
              ...MONO,
              fontSize: 20,
              fontWeight: 600,
              color: 'var(--ink)',
              margin: 0,
              lineHeight: 1.35,
              letterSpacing: '-0.01em',
            }}
          >
            Analyse once.{' '}
            <span style={{ color: 'var(--hot-ink)' }}>Use it as many times as you need.</span>
          </h2>
          <p
            style={{
              marginTop: 10,
              fontSize: 12.5,
              color: 'var(--ink-mid)',
              maxWidth: 500,
              lineHeight: 1.7,
            }}
          >
            Point Codelith at a repository. It reads every file and builds a structured
            knowledge base of what is actually there —{' '}
            <strong style={{ color: 'var(--ink)', fontWeight: 600 }}>not a summary of it.</strong>{' '}
            That knowledge base is the product.
          </p>
        </div>

        <div style={{ display: 'flex', alignItems: 'stretch' }}>
          <Node
            step="01"
            label="CODEBASE"
            title="Your Repository"
            description="Every file, route, entry point, module boundary, and dependency — read once, pinned to the commit."
            icon={<RepoIcon />}
            visible={v(2)}
            active={active === 0}
          />
          <Arrow visible={v(3)} active={active === 1} />
          <Node
            step="02"
            label="ANALYSIS"
            title="Analysis"
            description="Structure, dependencies, module boundaries, and all cross-file relationships fully mapped."
            icon={<AnalysisIcon />}
            visible={v(4)}
            active={active === 1}
          />
          <Arrow visible={v(5)} active={active === 2} />
          <Node
            step="03"
            label="KNOWLEDGE BASE"
            title="Knowledge Base"
            description="A structured index of what is actually in the code. Not a summary. The real thing."
            icon={<KBIcon />}
            hub
            visible={v(6)}
            active={active === 2}
          />
        </div>

        <Fan count={shown.length} visible={v(7)} active={active === 3} />

        <div style={{ display: 'flex', alignItems: 'stretch', gap: GAP }}>
          {shown.map(f => (
            <Feature
              key={f.id}
              step={f.step}
              label={f.label}
              title={f.title}
              description={f.description}
              icon={f.icon}
              preview={f.preview}
              visible={v(7)}
              active={active === 3}
            />
          ))}
        </div>

        <div
          style={{
            marginTop: 22,
            paddingTop: 16,
            borderTop: '1px solid var(--rule)',
            display: 'flex',
            alignItems: 'center',
            gap: 20,
            opacity: v(7) ? 1 : 0,
            transition: 'opacity 0.5s ease 500ms',
          }}
        >
          <div
            style={{
              ...MONO,
              fontSize: 9,
              color: 'var(--hot-ink)',
              letterSpacing: '0.14em',
              flexShrink: 0,
            }}
          >
            ONE READING · THREE APPS
          </div>
          <div
            style={{ width: 1, height: 12, backgroundColor: 'var(--rule)', flexShrink: 0 }}
          />
          <div style={{ fontSize: 11.5, color: 'var(--ink-dim)', lineHeight: 1.6 }}>
            One pass over the repository builds one knowledge base, and all three apps read
            it. Nothing opens the repository again.
          </div>
        </div>
      </div>
    </section>
  )
}
