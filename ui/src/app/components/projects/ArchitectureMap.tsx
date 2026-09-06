import { useMemo, useState } from 'react'
import type { Architecture, ArchService } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * The shape of the system, drawn.
 *
 * Analysis has written this on every run since the architecture agent
 * landed: services, the relations between them with the verb naming
 * each one, the layers they group into. Nothing has ever read it. It is
 * the one thing on this page that answers "what is this project?" in a
 * glance rather than in a table of counts.
 *
 * **Laid out from the data, not placed by hand.** How many services a
 * repository has is not knowable in advance: this one has ten, the next
 * has three, a monorepo has sixty. So nodes are assigned a depth by
 * longest path from a root and spread within their row, which puts
 * entry points at the top and whatever they reach beneath them. That is
 * the reading order somebody already has in their head.
 *
 * **Cycles are expected.** Real systems call back. The depth pass caps
 * its iterations rather than assuming a DAG, and an edge that runs
 * upward is drawn as one: a fact about the code, not a defect in the
 * drawing.
 *
 * **Direction is animated, not decorated.** An arrowhead is six pixels
 * of geometry doing the most important job in the diagram. On hover the
 * edge itself marches from source to target, which says which way the
 * call goes at a size a reader can actually see.
 *
 * Above a size where a diagram stops being readable it stops being a
 * diagram. Sixty overlapping boxes joined by two hundred lines is not
 * more informative than a list, and pretending otherwise is the failure
 * mode of every architecture visualiser.
 * ------------------------------------------------------------------ */

/** Past this many services the drawing is a hairball, and a list is more use. */
const MAX_DRAWN = 24

const NODE_W = 156
const NODE_H = 52
const NODE_R = 13
const ROW_GAP = 88
const COL_GAP = 26
const PAD = 20

/** Space left between the end of an edge and the box it points at. An arrowhead
 *  touching the border reads as a smudge on the box rather than as an arrow. */
const ARROW_GAP = 8

/** One row lands, then the next. Slow enough to read as an order being built up,
 *  fast enough that the map is settled before anyone reaches for the mouse. */
const ROW_DELAY = 0.11
const EDGE_DELAY = 0.34

type Placed = ArchService & { x: number; y: number; row: number }

/**
 * A colour per kind of service.
 *
 * Not decoration: what a component *is* is the second question after what it is
 * called, and the type text is eight pixels tall. Anything the writer invents that
 * is not in this table gets the neutral ink, which is the honest answer.
 */
const TYPE_INK: Record<string, string> = {
  api: 'var(--hot)',
  gateway: 'var(--hot)',
  entrypoint: 'var(--hot)',
  frontend: 'var(--hot)',
  service: 'var(--ink)',
  worker: 'var(--ink)',
  cli: 'var(--warn)',
  database: 'var(--ok)',
  store: 'var(--ok)',
  cache: 'var(--ok)',
  utility: 'var(--ink-dim)',
  library: 'var(--ink-dim)',
  config: 'var(--ink-dim)',
}

function typeInk(type: string): string {
  return TYPE_INK[type.toLowerCase().trim()] ?? 'var(--ink-mid)'
}

/**
 * Depth per service: one more than the deepest thing that reaches it.
 *
 * Roots are services nothing points at. A graph that is all cycles has none, in which
 * case the busiest node starts things off — some root is better than no drawing.
 */
function layout(arch: Architecture): { nodes: Placed[]; rows: number; width: number } {
  const names = arch.services.map(s => s.name)
  const incoming = new Map<string, string[]>(names.map(n => [n, []]))
  const outgoing = new Map<string, string[]>(names.map(n => [n, []]))
  for (const r of arch.relations) {
    incoming.get(r.target)?.push(r.source)
    outgoing.get(r.source)?.push(r.target)
  }

  const depth = new Map<string, number>(names.map(n => [n, 0]))
  let roots = names.filter(n => (incoming.get(n) ?? []).length === 0)
  if (!roots.length && names.length) {
    roots = [[...names].sort(
      (a, b) => (outgoing.get(b)?.length ?? 0) - (outgoing.get(a)?.length ?? 0),
    )[0]]
  }

  // Relax depths until they settle. The cap is what makes a cycle terminate: after
  // `names.length` passes any further change is the cycle going round again.
  for (let pass = 0; pass < names.length; pass++) {
    let moved = false
    for (const r of arch.relations) {
      const next = (depth.get(r.source) ?? 0) + 1
      if (next > (depth.get(r.target) ?? 0) && next <= names.length) {
        depth.set(r.target, next)
        moved = true
      }
    }
    if (!moved) break
  }

  const byRow = new Map<number, ArchService[]>()
  for (const service of arch.services) {
    const row = depth.get(service.name) ?? 0
    byRow.set(row, [...(byRow.get(row) ?? []), service])
  }

  const rows = [...byRow.keys()].sort((a, b) => a - b)
  const widest = Math.max(...rows.map(r => byRow.get(r)!.length), 1)
  const width = widest * NODE_W + (widest - 1) * COL_GAP + PAD * 2

  const nodes: Placed[] = []
  rows.forEach((row, index) => {
    const inRow = byRow.get(row)!
    const rowWidth = inRow.length * NODE_W + (inRow.length - 1) * COL_GAP
    const left = (width - rowWidth) / 2
    inRow.forEach((service, i) => {
      nodes.push({
        ...service,
        row: index,
        x: left + i * (NODE_W + COL_GAP),
        y: PAD + index * (NODE_H + ROW_GAP),
      })
    })
  })

  return { nodes, rows: rows.length, width }
}

type Point = { x: number; y: number }
type Curve = { p0: Point; c1: Point; c2: Point; p3: Point }

/**
 * The curve between two boxes, and the control points it was drawn with.
 *
 * Both come back together on purpose. The verb that labels an edge has to sit *on*
 * the line, and a label placed from the straight-line midpoint of a curved path
 * floats beside it, which is how the first version of this looked.
 */
function edgePath(from: Placed, to: Placed): Curve {
  const level = Math.abs(to.y - from.y) < 1

  if (level) {
    // Side to side, so a same-row edge does not disappear behind the boxes.
    const rightwards = to.x > from.x
    const p0 = { x: from.x + (rightwards ? NODE_W : 0), y: from.y + NODE_H / 2 }
    const p3 = {
      x: to.x + (rightwards ? -ARROW_GAP : NODE_W + ARROW_GAP),
      y: to.y + NODE_H / 2,
    }
    const bow = Math.min(Math.abs(p3.x - p0.x) * 0.3, 46)
    return {
      p0,
      c1: { x: p0.x + (rightwards ? bow : -bow), y: p0.y - bow * 0.55 },
      c2: { x: p3.x + (rightwards ? -bow : bow), y: p3.y - bow * 0.55 },
      p3,
    }
  }

  const down = to.y > from.y
  const p0 = { x: from.x + NODE_W / 2, y: from.y + (down ? NODE_H : 0) }
  const p3 = {
    x: to.x + NODE_W / 2,
    y: to.y + (down ? -ARROW_GAP : NODE_H + ARROW_GAP),
  }
  // Control points pulled a fixed fraction of the vertical run, which keeps the
  // curve's shoulders in the same place whether the rows are near or far apart.
  const lift = Math.abs(p3.y - p0.y) * 0.46
  return {
    p0,
    c1: { x: p0.x, y: p0.y + (down ? lift : -lift) },
    c2: { x: p3.x, y: p3.y + (down ? -lift : lift) },
    p3,
  }
}

function d({ p0, c1, c2, p3 }: Curve): string {
  return `M${p0.x} ${p0.y} C${c1.x} ${c1.y} ${c2.x} ${c2.y} ${p3.x} ${p3.y}`
}

/** A point on the cubic itself, so the verb lands on the line it names. */
function at({ p0, c1, c2, p3 }: Curve, t: number): Point {
  const u = 1 - t
  const a = u * u * u
  const b = 3 * u * u * t
  const c = 3 * u * t * t
  const e = t * t * t
  return {
    x: a * p0.x + b * c1.x + c * c2.x + e * p3.x,
    y: a * p0.y + b * c1.y + c * c2.y + e * p3.y,
  }
}

export default function ArchitectureMap({ arch }: { arch: Architecture }) {
  const [hover, setHover] = useState<string | null>(null)
  const { nodes, rows, width } = useMemo(() => layout(arch), [arch])

  if (!arch.available || !arch.services.length) return null

  const byName = new Map(nodes.map(n => [n.name, n]))
  const height = PAD * 2 + rows * NODE_H + (rows - 1) * ROW_GAP
  const shown = hover ? arch.services.find(s => s.name === hover) : null

  // Everything the hovered service touches, so pointing at one thing dims the rest
  // rather than leaving the reader to trace lines.
  const lit = new Set<string>()
  if (hover) {
    lit.add(hover)
    for (const r of arch.relations) {
      if (r.source === hover) lit.add(r.target)
      if (r.target === hover) lit.add(r.source)
    }
  }

  if (arch.services.length > MAX_DRAWN) {
    return (
      <div className="p-3">
        <p className="mb-2 font-sans text-[12px] text-ink-mid">
          {arch.services.length} services. Too many to draw legibly, so here they are.
        </p>
        <div className="flex flex-wrap gap-1.5">
          {arch.services.map(s => (
            <span key={s.name} className="tag border border-rule px-2 py-1 text-ink-mid">
              {s.name}
            </span>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div>
      <div className="overflow-x-auto px-3 pt-3">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="w-full"
          style={{ minWidth: Math.min(width, 560) }}
          role="img"
          aria-label={`Architecture: ${arch.services.length} services and ${arch.relations.length} relations between them.`}
        >
          <defs>
            {/* The ground. Every other surface in the studio sits on a ruled or
                hatched field, and the one place actually drawing a plan was on
                blank paper. Faint enough to read as texture, not as data. */}
            <pattern
              id="arch-grid"
              width="18"
              height="18"
              patternUnits="userSpaceOnUse"
            >
              <circle cx="1" cy="1" r="0.9" fill="var(--rule)" />
            </pattern>

            {/* An open chevron rather than a filled triangle. At this size a solid
                head reads as a blob, and `userSpaceOnUse` keeps it from growing
                with the stroke when an edge lights up. */}
            {(
              [
                ['arch-arrow', 'var(--ink-dim)'],
                ['arch-arrow-on', 'var(--hot)'],
              ] as const
            ).map(([id, ink]) => (
              <marker
                key={id}
                id={id}
                viewBox="0 0 10 10"
                refX="8"
                refY="5"
                markerWidth="10"
                markerHeight="10"
                markerUnits="userSpaceOnUse"
                orient="auto"
              >
                <path
                  d="M2.5 1.6 L8 5 L2.5 8.4"
                  fill="none"
                  stroke={ink}
                  strokeWidth="1.7"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </marker>
            ))}

            {/* Lifts the boxes off the paper. Two stacked shadows rather than one,
                because a single soft shadow at this size just looks like a smudge. */}
            <filter id="arch-lift" x="-30%" y="-30%" width="160%" height="180%">
              <feDropShadow
                dx="0"
                dy="1"
                stdDeviation="0.8"
                floodColor="var(--ink)"
                floodOpacity="0.07"
              />
              <feDropShadow
                dx="0"
                dy="4"
                stdDeviation="5"
                floodColor="var(--ink)"
                floodOpacity="0.06"
              />
            </filter>
            <filter id="arch-lift-on" x="-40%" y="-40%" width="180%" height="200%">
              <feDropShadow
                dx="0"
                dy="3"
                stdDeviation="7"
                floodColor="var(--hot)"
                floodOpacity="0.28"
              />
            </filter>
          </defs>

          <rect
            x="0"
            y="0"
            width={width}
            height={height}
            fill="url(#arch-grid)"
            opacity="0.75"
          />

          {arch.relations.map((r, i) => {
            const from = byName.get(r.source)
            const to = byName.get(r.target)
            if (!from || !to) return null

            const curve = edgePath(from, to)
            const path = d(curve)
            const on = hover === r.source || hover === r.target
            const dim = hover && !on
            // Alternating so two edges between the same pair of rows do not land
            // their verbs in the same place.
            const label = at(curve, i % 2 ? 0.62 : 0.38)
            const plate = r.kind.length * 4.9 + 11
            // Edges draw after the rows they join have landed.
            const delay = EDGE_DELAY + Math.max(from.row, to.row) * ROW_DELAY

            return (
              <g key={i} opacity={dim ? 0.14 : 1} style={{ transition: 'opacity .18s' }}>
                <path
                  className="arch-edge"
                  style={{ animationDelay: `${delay}s` }}
                  pathLength={1}
                  d={path}
                  fill="none"
                  stroke={on ? 'var(--hot)' : 'var(--rule)'}
                  strokeWidth={on ? 1.9 : 1.4}
                  strokeLinecap="round"
                  markerEnd={`url(#${on ? 'arch-arrow-on' : 'arch-arrow'})`}
                />

                {/* The direction, marching source to target. Only while the reader
                    is pointing at one of its ends: every edge crawling at once is
                    a screensaver, not a diagram. */}
                {on && (
                  <path
                    className="arch-flow"
                    d={path}
                    fill="none"
                    stroke="var(--hot)"
                    strokeWidth="2.4"
                    strokeLinecap="round"
                    opacity="0.5"
                  />
                )}

                {r.kind && (
                  <g className="arch-label" style={{ animationDelay: `${delay + 0.3}s` }}>
                    {/* Knocked out of the line behind it, so the verb is legible
                        wherever it lands rather than striped by its own edge. */}
                    <rect
                      x={label.x - plate / 2}
                      y={label.y - 7.5}
                      width={plate}
                      height={15}
                      rx="7.5"
                      fill={on ? 'var(--hot-wash)' : 'var(--panel)'}
                      stroke={on ? 'var(--hot-edge)' : 'var(--rule)'}
                      strokeWidth="0.8"
                    />
                    <text
                      x={label.x}
                      y={label.y + 2.8}
                      textAnchor="middle"
                      fontSize="8.5"
                      letterSpacing="0.06em"
                      fontFamily="var(--font-mono)"
                      fill={on ? 'var(--hot-ink)' : 'var(--ink-dim)'}
                    >
                      {r.kind}
                    </text>
                  </g>
                )}
              </g>
            )
          })}

          {nodes.map(n => {
            const on = hover === n.name
            const near = lit.has(n.name)
            const dim = hover && !near
            const ink = typeInk(n.type)
            return (
              <g
                key={n.name}
                className="arch-node cursor-default"
                style={{ animationDelay: `${n.row * ROW_DELAY}s`, opacity: dim ? 0.28 : 1 }}
                onMouseEnter={() => setHover(n.name)}
                onMouseLeave={() => setHover(null)}
              >
                <rect
                  x={n.x}
                  y={n.y}
                  width={NODE_W}
                  height={NODE_H}
                  rx={NODE_R}
                  fill={on ? 'var(--hot-wash)' : 'var(--panel)'}
                  stroke={on ? 'var(--hot)' : 'var(--rule)'}
                  strokeWidth={on ? 1.6 : 1.1}
                  filter={`url(#${on ? 'arch-lift-on' : 'arch-lift'})`}
                />
                {/* A rounded stripe down the leading edge, coloured by what the
                    service is. Reads at a glance; the word underneath confirms it. */}
                <rect
                  x={n.x + 5}
                  y={n.y + 12}
                  width={3}
                  height={NODE_H - 24}
                  rx="1.5"
                  fill={on ? 'var(--hot)' : ink}
                  opacity={on ? 1 : 0.8}
                />
                <text
                  x={n.x + 17}
                  y={n.y + 23}
                  fontSize="11"
                  fontWeight="700"
                  fontFamily="var(--font-mono)"
                  fill="var(--ink)"
                >
                  {n.name.length > 19 ? `${n.name.slice(0, 18)}…` : n.name}
                </text>
                {n.type && (
                  <text
                    x={n.x + 17}
                    y={n.y + 38}
                    fontSize="8"
                    letterSpacing="0.12em"
                    fontFamily="var(--font-mono)"
                    fill={on ? 'var(--hot-ink)' : 'var(--ink-dim)'}
                  >
                    {n.type.toUpperCase()}
                  </text>
                )}
                {n.modules.length > 1 && (
                  <text
                    x={n.x + NODE_W - 13}
                    y={n.y + 38}
                    textAnchor="end"
                    fontSize="8"
                    fontFamily="var(--font-mono)"
                    fill="var(--ink-dim)"
                  >
                    {n.modules.length} mod
                  </text>
                )}
              </g>
            )
          })}
        </svg>
      </div>

      {/* The diagram carries the shape; this carries the sentence. Without it,
          hovering only lights things up. */}
      <div className="min-h-[52px] border-t border-rule bg-sunk/40 px-3 py-2">
        {shown ? (
          <p className="font-sans text-[11.5px] leading-relaxed text-ink-mid">
            <span
              className="mr-1.5 inline-block h-2 w-2 rounded-full align-middle"
              style={{ background: typeInk(shown.type) }}
            />
            <span className="font-semibold text-ink">{shown.name}</span>
            {shown.type ? <span className="text-ink-dim"> · {shown.type}</span> : null}
            {shown.description ? ` · ${shown.description}` : ''}
            {shown.modules.length ? (
              <span className="text-ink-dim">
                {' '}
                ({shown.modules.slice(0, 4).join(', ')}
                {shown.modules.length > 4 ? `, +${shown.modules.length - 4}` : ''})
              </span>
            ) : null}
          </p>
        ) : (
          <p className="font-sans text-[11.5px] leading-relaxed text-ink-dim">
            {arch.services.length} service{arch.services.length === 1 ? '' : 's'},{' '}
            {arch.relations.length} relation{arch.relations.length === 1 ? '' : 's'}. Point at
            one to see what it is, what it touches, and which way each call runs.
            {arch.dangling_relations > 0 && (
              <span className="text-warn">
                {' '}
                {arch.dangling_relations} relation
                {arch.dangling_relations === 1 ? '' : 's'} named a service that was not
                listed, and could not be drawn.
              </span>
            )}
          </p>
        )}
      </div>
    </div>
  )
}
