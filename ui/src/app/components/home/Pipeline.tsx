import { useEffect, useState } from 'react'
import type { AppCatalogItem, Project } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * Read once, use many times — drawn rather than asserted.
 *
 * Home said this in a sentence and then showed three cards that looked
 * like three separate products. The claim the whole architecture rests
 * on is that they are not separate: one pass over the repository builds
 * one knowledge base, and everything else reads it. A row of equal cards
 * cannot show that, because equal boxes have no order and no source.
 *
 * Drawn in the landing page's schematic language, deliberately and down
 * to the measurements: the same small plates on a gridded ground, the
 * same hard ink border, the same dashed marquee and crawling dash on the
 * wire, the same 8px letter-spaced caps. Somebody arrives here from that
 * page, and the diagram they were reading two clicks ago should be the
 * diagram they are reading now.
 *
 * What is Home's own is the shape. The landing page runs four stages in
 * a line; here the spine turns down at the knowledge base and fans to the
 * three apps, so the dashed rule dividing READ ONCE from WRITE MANY TIMES
 * runs horizontally between them — and exactly one line crosses it. That
 * crossing is the argument: nothing reaches an app except through the
 * reading, and once the reading exists all three become available
 * together.
 *
 * One SVG rather than HTML cards with connectors behind them. Lines that
 * have to find the edges of a responsive grid are lines that are wrong at
 * some width; inside a viewBox the geometry is fixed and the whole thing
 * scales.
 *
 * Hover is not decoration and not a link — the cards on Home used to be
 * links that could not do what they promised, which is why they are gone.
 * Hovering a plate explains it underneath, so the diagram doubles as the
 * copy it replaced.
 * ------------------------------------------------------------------ */

/** Phases of one loop. The spine advances a plate at a time; the fan-out is a single
 *  phase because the three apps arrive together, which is the point being made. */
const PHASES = ['source', 'analysis', 'kb', 'apps'] as const
type Phase = (typeof PHASES)[number]

/** Slower than the landing page's 3.2s. There is more to take in here — six plates
 *  and a fan-out rather than four in a row — and a schematic that has moved on before
 *  you have finished reading a plate is a schematic nobody reads. */
const STEP_MS = 3600

const W = 540
const H = 256
const CARD_W = 100
const CARD_H = 68
/** The three columns. Leaves sit on the spine's columns so the fan-out drops read as
 *  columns rather than as diagonals. */
const COLS = [30, 220, 410]
const SPINE_Y = 24
const LEAF_Y = 170
/** Where READ ONCE stops being true. Exactly one line crosses it. */
const SPLIT_Y = 122
const BUS_Y = 152

type NodeSpec = {
  id: string
  x: number
  y: number
  num: string
  label: string
  /** Up to two lines. The plates are narrow by design, and a name that wraps is
   *  better than one that runs off the edge or shrinks to fit. */
  lines: string[]
  tagline: string
  detail: string
  phase: Phase
}

const SPINE: NodeSpec[] = [
  {
    id: 'source',
    x: COLS[0], y: SPINE_Y, num: '01',
    label: 'Your repository', lines: ['Your', 'repository'],
    tagline: 'A URL or a folder',
    detail:
      'Cloned once, read once. Nothing is sent anywhere — the repository is walked on this machine, and the clone is discarded when the reading is built.',
    phase: 'source',
  },
  {
    id: 'analysis',
    x: COLS[1], y: SPINE_Y, num: '02',
    label: 'Analysis', lines: ['Analysis'],
    tagline: 'Every file, once',
    detail:
      'Nine agents walk the source: modules and their roles, routes, entry points, env vars, the import graph, and a semantic index. It takes no document type and never has.',
    phase: 'analysis',
  },
  {
    id: 'kb',
    x: COLS[2], y: SPINE_Y, num: '03',
    label: 'Knowledge base', lines: ['Knowledge', 'base'],
    tagline: 'Pinned to the commit',
    detail:
      'The product of analysis, not a step toward one. Stored against the commit SHA it was read at, so two readings of one repository can be compared — which is what What changed is.',
    phase: 'kb',
  },
]

const LEAVES: NodeSpec[] = [
  {
    id: 'documentation',
    x: COLS[0], y: LEAF_Y, num: '04',
    label: 'Documentation', lines: ['Documentation'],
    tagline: 'Retrieval · narratives',
    detail:
      'Markdown, DOCX, MkDocs or Docusaurus, written from the reading. Document types are offered from what the code contains, so a project with no HTTP routes is never offered an API reference.',
    phase: 'apps',
  },
  {
    id: 'ask',
    x: COLS[1], y: LEAF_Y, num: '05',
    label: 'Ask the code', lines: ['Ask the', 'code'],
    tagline: 'Retrieval · code graph',
    detail:
      'Answers grounded in the source, with every citation checked against the evidence actually retrieved. One that does not resolve is stripped rather than shown.',
    phase: 'apps',
  },
  {
    id: 'drift',
    x: COLS[2], y: LEAF_Y, num: '06',
    label: 'What changed', lines: ['What', 'changed'],
    tagline: 'Modules · written pages',
    detail:
      'What moved between two readings, and which written pages now describe code that is no longer there. Needs the codebase analysed twice.',
    phase: 'apps',
  },
]

const ALL = [...SPINE, ...LEAVES]

/** Reached by the pulse at or before this phase. */
const reached = (phase: Phase, at: Phase) => PHASES.indexOf(at) >= PHASES.indexOf(phase)

/** One plate. Square-cornered and hard-bordered, with the marquee, the growing rule
 *  and the beacon that mark the stage the pulse is standing on. */
function Plate({
  node,
  current,
  lit,
  hovered,
  onHover,
}: {
  node: NodeSpec
  current: boolean
  lit: boolean
  hovered: boolean
  onHover: (id: string | null) => void
}) {
  const on = current || hovered
  const { x, y } = node

  return (
    <g
      opacity={lit || hovered ? 1 : 0.4}
      style={{ transition: 'opacity .2s' }}
      onMouseEnter={() => onHover(node.id)}
      onMouseLeave={() => onHover(null)}
    >
      {on && (
        <rect
          x={x - 3} y={y - 3} width={CARD_W + 6} height={CARD_H + 6}
          fill="none" stroke="var(--hot)" strokeWidth="1" strokeDasharray="3 3"
        />
      )}
      <rect
        x={x} y={y} width={CARD_W} height={CARD_H}
        fill={on ? 'var(--hot-wash)' : 'var(--panel)'}
        stroke={on ? 'var(--hot)' : 'var(--ink)'}
        strokeWidth={on ? 2 : 1.2}
      />
      <text
        x={x + 9} y={y + 17} fontSize="8" fontWeight="700" letterSpacing="0.1em"
        fill={on ? 'var(--hot-ink)' : 'var(--ink-dim)'} fontFamily="var(--font-mono)"
      >
        {node.num}
      </text>
      {node.lines.map((line, i) => (
        <text
          key={line}
          x={x + 9} y={y + 34 + i * 13} fontSize="10.5" fontWeight="700"
          fill="var(--ink)" fontFamily="var(--font-mono)"
        >
          {line}
        </text>
      ))}
      <rect
        x={x + 9} y={y + 54} width={on ? 52 : 18} height="3"
        fill={on ? 'var(--hot)' : 'var(--rule)'}
        style={{ transition: 'width .3s' }}
      />
      {current && (
        <circle cx={x + CARD_W - 9} cy={y + 12} r="3" fill="var(--hot)">
          <animate attributeName="opacity" values="1;.2;1" dur="1.3s" repeatCount="indefinite" />
        </circle>
      )}
    </g>
  )
}

/** A wire, and the crawling dash that marks it as carried. */
function Wire({ d, live }: { d: string; live: boolean }) {
  return (
    <>
      <path d={d} fill="none" stroke="var(--rule)" strokeWidth="1.5" />
      {live && (
        <path d={d} fill="none" stroke="var(--hot)" strokeWidth="1.5" className="anim-flow" />
      )}
    </>
  )
}

export default function Pipeline({
  features,
  projects,
}: {
  features: AppCatalogItem[] | null
  projects: Project[] | null
}) {
  const [phase, setPhase] = useState<Phase>('source')
  const [running, setRunning] = useState(true)
  const [hovered, setHovered] = useState<string | null>(null)

  // Held still for anybody who has asked for less motion. A loop that runs regardless
  // is the reason that setting exists.
  useEffect(() => {
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) setRunning(false)
  }, [])

  useEffect(() => {
    if (!running || hovered) return
    const t = setInterval(
      () => setPhase(p => PHASES[(PHASES.indexOf(p) + 1) % PHASES.length]),
      STEP_MS,
    )
    return () => clearInterval(t)
  }, [running, hovered])

  const ready = (projects ?? []).filter(p => p.apps_ready).length

  // Named apps are checked against the registry, so the diagram cannot promise one the
  // studio does not have. Only once the catalogue has actually arrived, though — an
  // empty set while it loads would blink all three leaves out and back in.
  const catalogue = features?.length ? new Set(features.map(f => f.id)) : null
  const leaves = catalogue ? LEAVES.filter(l => catalogue.has(l.id)) : LEAVES
  const nodes = [...SPINE, ...leaves]

  const shown = hovered ? (ALL.find(n => n.id === hovered) ?? null) : null
  const step = PHASES.indexOf(phase) + 1
  const writing = reached('apps', phase)
  const kbCx = COLS[2] + CARD_W / 2

  // Ends of the bus: every app's column, plus the trunk's. Null when they coincide,
  // so a lone app directly under the knowledge base gets no zero-length segment.
  const stops = [kbCx, ...leaves.map(l => l.x + CARD_W / 2)]
  const busSpan =
    Math.min(...stops) === Math.max(...stops)
      ? null
      : ([Math.min(...stops), Math.max(...stops)] as const)

  return (
    <section className="mb-5">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3 border-b border-rule pb-3">
        <div>
          <p className="tag mb-1.5 text-hot-ink">How it works</p>
          <h2 className="text-[17px] leading-tight font-bold tracking-[-0.03em] text-ink">
            Analyse once. Use it as many times as you need.
          </h2>
        </div>
        <button
          onClick={() => setRunning(r => !r)}
          className="tag border border-rule bg-panel px-3 py-2 text-ink-dim transition-colors hover:border-ink hover:text-ink"
        >
          {running ? '❚❚ pause' : '▶ resume'}
        </button>
      </div>

      <div className="border border-rule bg-panel p-4">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="w-full"
          role="img"
          aria-label="A repository is analysed once into a knowledge base, which Documentation, Ask the code and What changed all read."
        >
          <defs>
            <pattern id="pipe-grid" width="12" height="12" patternUnits="userSpaceOnUse">
              <path d="M12 0H0V12" fill="none" stroke="var(--grid-line)" />
            </pattern>
          </defs>
          <rect width={W} height={H} fill="url(#pipe-grid)" />

          {/* The spine. */}
          {[0, 1].map(i => {
            const x1 = COLS[i] + CARD_W
            const x2 = COLS[i + 1]
            const live = reached(SPINE[i + 1].phase, phase)
            return (
              <g key={i}>
                <Wire d={`M${x1} ${SPINE_Y + 34} H${x2 - 6}`} live={live} />
                <path
                  d={`M${x2 - 6} ${SPINE_Y + 30} L${x2} ${SPINE_Y + 34} L${x2 - 6} ${SPINE_Y + 38}`}
                  fill="none"
                  strokeWidth="1.5"
                  stroke={live ? 'var(--hot)' : 'var(--rule)'}
                />
              </g>
            )
          })}

          {/* Where reading stops and writing starts. Exactly one line crosses it, and
              it leaves the knowledge base — which is the whole claim, drawn. */}
          <line
            x1="20" y1={SPLIT_Y} x2={W - 20} y2={SPLIT_Y}
            stroke="var(--rule)" strokeDasharray="2 4"
          />
          <text
            x="20" y={SPLIT_Y - 8} fontSize="8" letterSpacing="0.12em"
            fill="var(--ink-dim)" fontFamily="var(--font-mono)"
          >
            READ ONCE
          </text>
          <text
            x="20" y={SPLIT_Y + 16} fontSize="8" letterSpacing="0.12em"
            fill={writing ? 'var(--hot-ink)' : 'var(--ink-dim)'}
            fontFamily="var(--font-mono)"
          >
            WRITE MANY TIMES
          </text>

          {/* The fan-out: one trunk down across the split, then a branch to each app.
              Drawn from the plates rather than written out, so an app the registry does
              not carry takes its own branch with it instead of leaving a line into
              blank paper. */}
          <Wire d={`M${kbCx} ${SPINE_Y + CARD_H} V${BUS_Y}`} live={writing} />
          {/* The bus is drawn once across its full span, not once per app. Running a
              branch the whole way from the trunk to its own column overlaps the others,
              and the later branch's grey base then paints over the earlier one's hot
              overlay — a diagram that reports the pulse reaching two of three apps. */}
          {busSpan && <Wire d={`M${busSpan[0]} ${BUS_Y} H${busSpan[1]}`} live={writing} />}
          {leaves.map(leaf => {
            const cx = leaf.x + CARD_W / 2
            return (
              <g key={leaf.id}>
                <Wire d={`M${cx} ${BUS_Y} V${LEAF_Y - 6}`} live={writing} />
                <path
                  d={`M${cx - 4} ${LEAF_Y - 6} L${cx} ${LEAF_Y} L${cx + 4} ${LEAF_Y - 6}`}
                  fill="none"
                  strokeWidth="1.5"
                  stroke={writing ? 'var(--hot)' : 'var(--rule)'}
                />
              </g>
            )
          })}

          {nodes.map(n => (
            <Plate
              key={n.id}
              node={n}
              current={n.phase === phase}
              lit={reached(n.phase, phase)}
              hovered={hovered === n.id}
              onHover={setHovered}
            />
          ))}
        </svg>
      </div>

      {/* What the hovered plate is. The diagram carries the shape; this carries the
          sentence, so hovering does something rather than merely lighting up. */}
      <div
        key={shown?.id ?? 'idle'}
        className="anim-rise border border-t-0 border-rule bg-panel p-4"
      >
        <p className="tag mb-2.5 text-hot-ink">
          {shown ? shown.tagline : 'One reading, three apps'}
        </p>
        <p className="mb-3 max-w-[72ch] font-sans text-[13.5px] leading-[1.75] text-ink-mid">
          {shown ? (
            <>
              <span className="font-semibold text-ink">{shown.label} — </span>
              {shown.detail}
            </>
          ) : (
            <>
              One pass over the repository builds one knowledge base, and all three apps
              read it. Nothing opens the repository again.{' '}
              {ready
                ? `${ready} codebase${ready > 1 ? 's are' : ' is'} ready.`
                : 'Add a codebase to start.'}{' '}
              Hover any step to see what it does.
            </>
          )}
        </p>
        {running && !shown && (
          <div className="flex items-center gap-2.5">
            <span className="h-[2px] w-40 overflow-hidden bg-rule">
              <span
                key={phase}
                className="block h-full bg-hot"
                style={{ animation: `sweep ${STEP_MS}ms linear` }}
              />
            </span>
            <span className="tag text-ink-dim">
              {step} / {PHASES.length}
            </span>
          </div>
        )}
      </div>
    </section>
  )
}
