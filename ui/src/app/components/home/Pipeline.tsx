import { useEffect, useState } from 'react'
import type { AppCatalogItem, Project } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * Read once, use many times — drawn rather than asserted.
 *
 * Home said this in a sentence and then showed three cards that looked
 * like three separate products. The claim the whole architecture rests
 * on is that they are not separate: one pass over the repository builds
 * one knowledge base, and everything else reads it. A row of equal
 * cards cannot show that, because equal boxes have no order and no
 * source.
 *
 * So it is a diagram. The spine runs left to right — repository,
 * analysis, knowledge base — and the three apps hang below the knowledge
 * base, sharing one bus. The pulse travels the spine, and only when it
 * reaches the knowledge base does it fan out to all three at once.
 * That timing is the argument: nothing downstream can start until the
 * reading exists, and once it does they all become available together.
 *
 * One SVG rather than HTML cards with connectors behind them. Lines
 * that have to find the edges of a responsive grid are lines that are
 * wrong at some width; inside a viewBox the geometry is fixed and the
 * whole thing scales.
 *
 * Hover is not decoration and not a link — the cards on Home used to be
 * links that could not do what they promised, which is why they are
 * gone. Hovering a node explains it underneath, so the diagram doubles
 * as the copy it replaced.
 * ------------------------------------------------------------------ */

/** Phases of one loop. The spine advances a node at a time; the fan-out is a single
 *  phase because the three apps arrive together, which is the point being made. */
const PHASES = ['source', 'analysis', 'kb', 'apps'] as const
type Phase = (typeof PHASES)[number]

const STEP_MS = 1250

type NodeSpec = {
  id: string
  x: number
  y: number
  w: number
  h: number
  num: string
  label: string
  line: string
  detail: string
  phase: Phase
}

const W = 880
const H = 340
const CARD_H = 82
const LEAF_H = 74

/** The spine, then the leaves under it. Leaves sit on the same x as the spine cards
 *  so the fan-out drops read as columns rather than as diagonals. */
const SPINE: NodeSpec[] = [
  {
    id: 'source',
    x: 24, y: 26, w: 240, h: CARD_H,
    num: '01', label: 'Your repository',
    line: 'A URL or a folder',
    detail:
      'Cloned once, read once. Nothing is sent anywhere — the repository is walked on this machine and the clone is discarded when the reading is built.',
    phase: 'source',
  },
  {
    id: 'analysis',
    x: 320, y: 26, w: 240, h: CARD_H,
    num: '02', label: 'Analysis',
    line: 'Every file, once',
    detail:
      'Nine agents walk the source: modules and their roles, routes, entrypoints, env vars, the import graph, and a semantic index. It takes no document type and never has.',
    phase: 'analysis',
  },
  {
    id: 'kb',
    x: 616, y: 26, w: 240, h: CARD_H,
    num: '03', label: 'Knowledge base',
    line: 'Pinned to the commit',
    detail:
      'The product of analysis, not a step toward one. Stored against the commit SHA it was read at, so two readings of one repository can be compared — which is what What changed is.',
    phase: 'kb',
  },
]

const LEAF_Y = 236
const LEAVES: Omit<NodeSpec, 'phase'>[] = [
  {
    id: 'documentation',
    x: 24, y: LEAF_Y, w: 240, h: LEAF_H,
    num: '04', label: 'Documentation',
    line: 'retrieval · narratives',
    detail:
      'Markdown, DOCX, MkDocs or Docusaurus, written from the reading. Document types are offered from what the code contains, so a project with no HTTP routes is never offered an API reference.',
  },
  {
    id: 'ask',
    x: 320, y: LEAF_Y, w: 240, h: LEAF_H,
    num: '05', label: 'Ask the code',
    line: 'retrieval · code graph',
    detail:
      'Answers grounded in the source, with every citation checked against the evidence actually retrieved. One that does not resolve is stripped rather than shown.',
  },
  {
    id: 'drift',
    x: 616, y: LEAF_Y, w: 240, h: LEAF_H,
    num: '06', label: 'What changed',
    line: 'modules · written pages',
    detail:
      'What moved between two readings, and which written pages now describe code that is no longer there. Needs the codebase analysed twice.',
  },
]

const ALL = [...SPINE, ...LEAVES.map(l => ({ ...l, phase: 'apps' as Phase }))]

/** Reached by the pulse at or before this phase. */
function isLit(phase: Phase, at: Phase): boolean {
  return PHASES.indexOf(at) >= PHASES.indexOf(phase)
}

function Node({
  node,
  lit,
  arriving,
  hovered,
  onHover,
}: {
  node: NodeSpec
  lit: boolean
  arriving: boolean
  hovered: boolean
  onHover: (id: string | null) => void
}) {
  const active = lit || hovered
  return (
    <g
      onMouseEnter={() => onHover(node.id)}
      onMouseLeave={() => onHover(null)}
      className="cursor-default"
    >
      <rect
        x={node.x}
        y={node.y}
        width={node.w}
        height={node.h}
        rx="8"
        fill={active ? 'var(--hot-wash)' : 'var(--panel)'}
        stroke={active ? 'var(--hot)' : 'var(--rule)'}
        strokeWidth={hovered ? 2.2 : active ? 1.6 : 1.2}
        style={arriving ? { animation: 'pipe-arrive 620ms ease-out' } : undefined}
        className="transition-[fill,stroke] duration-300"
      />
      <text
        x={node.x + 16}
        y={node.y + 24}
        className="font-mono"
        fontSize="10"
        letterSpacing="1"
        fill={active ? 'var(--hot-ink)' : 'var(--ink-dim)'}
      >
        {node.num}
      </text>
      <text
        x={node.x + 16}
        y={node.y + 46}
        className="font-mono"
        fontSize="15"
        fontWeight="600"
        fill={active ? 'var(--hot-ink)' : 'var(--ink)'}
      >
        {node.label}
      </text>
      <text
        x={node.x + 16}
        y={node.y + 65}
        className="font-mono"
        fontSize="10.5"
        fill="var(--ink-dim)"
      >
        {node.line}
      </text>
    </g>
  )
}

/** A connector, and the pulse that runs along it when its phase is reached. */
function Edge({ d, flowing }: { d: string; flowing: boolean }) {
  return (
    <>
      <path d={d} fill="none" stroke="var(--rule)" strokeWidth="1.4" />
      {flowing && (
        <path
          d={d}
          pathLength={100}
          fill="none"
          stroke="var(--hot)"
          strokeWidth="2.4"
          strokeLinecap="round"
          strokeDasharray="18 100"
          style={{ animation: `pipe-flow ${STEP_MS}ms linear` }}
        />
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

  // Stopped for anybody who has asked for less motion. A loop that runs regardless is
  // the reason that setting exists.
  useEffect(() => {
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)')
    if (reduce?.matches) setRunning(false)
  }, [])

  useEffect(() => {
    if (!running || hovered) return
    const id = setInterval(() => {
      setPhase(p => PHASES[(PHASES.indexOf(p) + 1) % PHASES.length])
    }, STEP_MS)
    return () => clearInterval(id)
  }, [running, hovered])

  const ready = (projects ?? []).filter(p => p.apps_ready).length
  const shown = hovered ? ALL.find(n => n.id === hovered) : null
  // Named apps are checked against the registry, so the diagram cannot promise one
  // the studio does not have. Only once the catalogue has actually arrived, though —
  // an empty set while it loads would blink all three leaves out and back in.
  const catalogue = features?.length ? new Set(features.map(f => f.id)) : null
  const nodes = catalogue
    ? ALL.filter(n => n.phase !== 'apps' || catalogue.has(n.id))
    : ALL

  // Drawn from the nodes rather than written out, so an app the registry does not
  // carry takes its own connector with it instead of leaving a line into blank paper.
  const kbBottom = { x: 616 + 120, y: 26 + CARD_H }
  const busY = 178
  const drops = nodes
    .filter(n => n.phase === 'apps')
    .map(n => `M${kbBottom.x} ${busY} H${n.x + n.w / 2} V${n.y}`)

  return (
    <section className="mb-5">
      <div className="mb-2 flex items-center gap-2">
        <span className="tag text-ink-dim">Read once, use many times</span>
        <span className="h-px flex-1 bg-rule" />
        <button
          type="button"
          onClick={() => setRunning(r => !r)}
          className="tag text-ink-dim transition-colors hover:text-hot-ink"
        >
          {running ? '❙❙ pause' : '▶ play'}
        </button>
      </div>

      <div className="overflow-hidden rounded-sm border border-rule bg-panel">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="w-full bg-sunk/70"
          role="img"
          aria-label="A repository is analysed once into a knowledge base, which Documentation, Ask the code and What changed all read."
        >
          <defs>
            <pattern id="pipe-grid" width="16" height="16" patternUnits="userSpaceOnUse">
              <path d="M16 0H0V16" fill="none" stroke="var(--grid-line)" />
            </pattern>
          </defs>
          <rect width={W} height={H} fill="url(#pipe-grid)" />

          {/* Spine */}
          <Edge d="M264 67 H320" flowing={phase === 'analysis'} />
          <Edge d="M560 67 H616" flowing={phase === 'kb'} />

          {/* The fan-out: one trunk down from the knowledge base, then a branch to
              each app. Every branch is normalised to the same pathLength, so the
              three pulses arrive together however far each one has to travel —
              which is the claim. Drawing them in sequence would say the opposite. */}
          <Edge d={`M${kbBottom.x} ${kbBottom.y} V${busY}`} flowing={phase === 'apps'} />
          {drops.map(d => (
            <Edge key={d} d={d} flowing={phase === 'apps'} />
          ))}

          {/* Arrowheads on the spine, so direction reads when the loop is paused. */}
          <path d="M314 67 l-6 -3.5 v7 z" fill="var(--rule)" />
          <path d="M610 67 l-6 -3.5 v7 z" fill="var(--rule)" />

          {nodes.map(n => (
            <Node
              key={n.id}
              node={n}
              lit={isLit(n.phase, phase)}
              arriving={n.phase === phase}
              hovered={hovered === n.id}
              onHover={setHovered}
            />
          ))}

          <text
            x="24"
            y={busY - 12}
            className="font-mono"
            fontSize="10"
            letterSpacing="1.5"
            fill="var(--ink-dim)"
          >
            ONE READING — READ BY ALL THREE
          </text>
        </svg>

        {/* What the hovered node is. The diagram carries the shape; this carries the
            sentence, so hovering does something rather than merely lighting up. */}
        <div className="min-h-[58px] border-t border-rule bg-panel px-4 py-2.5">
          {shown ? (
            <p className="font-sans text-[12px] leading-relaxed text-ink-mid">
              <span className="font-semibold text-ink">{shown.label} — </span>
              {shown.detail}
            </p>
          ) : (
            <p className="font-sans text-[12px] leading-relaxed text-ink-dim">
              One pass over the repository builds one knowledge base, and all three apps
              read it. {ready ? `${ready} codebase${ready > 1 ? 's are' : ' is'} ready.` : 'Add a codebase to start.'}{' '}
              Hover any step to see what it does.
            </p>
          )}
        </div>
      </div>
    </section>
  )
}
