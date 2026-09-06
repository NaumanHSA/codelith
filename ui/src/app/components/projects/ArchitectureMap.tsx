import { useMemo, useState } from 'react'
import type { Architecture, ArchService } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * The shape of the system, drawn.
 *
 * Analysis has written this on every run since the architecture agent
 * landed — services, the relations between them with the verb naming
 * each one, the layers they group into — and nothing has ever read it.
 * It is the one thing on this page that answers "what is this project?"
 * in a glance rather than in a table of counts.
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
 * upward is drawn as one — it is a fact about the code, not a defect in
 * the drawing.
 *
 * Above a size where a diagram stops being readable it stops being a
 * diagram. Sixty overlapping boxes joined by two hundred lines is not
 * more informative than a list, and pretending otherwise is the failure
 * mode of every architecture visualiser.
 * ------------------------------------------------------------------ */

/** Past this many services the drawing is a hairball, and a list is more use. */
const MAX_DRAWN = 24

const NODE_W = 132
const NODE_H = 42
const ROW_GAP = 78
const COL_GAP = 22
const PAD = 16

type Placed = ArchService & { x: number; y: number; row: number }

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

/** Where an edge leaves and arrives, given which way it runs. */
function anchors(from: Placed, to: Placed) {
  const down = to.y > from.y
  const level = Math.abs(to.y - from.y) < 1
  if (level) {
    // Side to side, so a same-row edge does not disappear behind the boxes.
    const rightwards = to.x > from.x
    return {
      x1: from.x + (rightwards ? NODE_W : 0),
      y1: from.y + NODE_H / 2,
      x2: to.x + (rightwards ? 0 : NODE_W),
      y2: to.y + NODE_H / 2,
    }
  }
  return {
    x1: from.x + NODE_W / 2,
    y1: from.y + (down ? NODE_H : 0),
    x2: to.x + NODE_W / 2,
    y2: to.y + (down ? 0 : NODE_H),
  }
}

/**
 * A point along the edge's own curve.
 *
 * The verb used to sit at the straight-line midpoint of every edge, and two edges
 * running between the same two rows have the same midpoint — so "calls" and "uses"
 * printed on top of each other and read as neither. Walking each edge's actual
 * Bezier, at a fraction that alternates, separates them: the curves differ even when
 * the endpoints nearly do.
 */
function along(
  x1: number, y1: number, x2: number, y2: number, my: number, t: number,
) {
  const u = 1 - t
  // Cubic through P0(x1,y1) C1(x1,my) C2(x2,my) P3(x2,y2) — the same control points
  // the path below is drawn with, or the label would sit off the line.
  return {
    x: u * u * u * x1 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t * t * t * x2,
    y: u * u * u * y1 + 3 * u * u * t * my + 3 * u * t * t * my + t * t * t * y2,
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
            <marker
              id="arch-arrow"
              viewBox="0 0 8 8"
              refX="7"
              refY="4"
              markerWidth="7"
              markerHeight="7"
              orient="auto-start-reverse"
            >
              <path d="M0 0 L8 4 L0 8 z" fill="var(--rule)" />
            </marker>
            <marker
              id="arch-arrow-on"
              viewBox="0 0 8 8"
              refX="7"
              refY="4"
              markerWidth="7"
              markerHeight="7"
              orient="auto-start-reverse"
            >
              <path d="M0 0 L8 4 L0 8 z" fill="var(--hot)" />
            </marker>
          </defs>

          {arch.relations.map((r, i) => {
            const from = byName.get(r.source)
            const to = byName.get(r.target)
            if (!from || !to) return null
            const { x1, y1, x2, y2 } = anchors(from, to)
            const on = hover === r.source || hover === r.target
            const dim = hover && !on
            const my = (y1 + y2) / 2
            // Alternating so adjacent edges do not land their verbs in the same place.
            const at = along(x1, y1, x2, y2, my, i % 2 ? 0.62 : 0.38)
            const width = r.kind.length * 4.9 + 7
            return (
              <g key={i} opacity={dim ? 0.16 : 1} style={{ transition: 'opacity .15s' }}>
                <path
                  d={`M${x1} ${y1} C${x1} ${my} ${x2} ${my} ${x2} ${y2}`}
                  fill="none"
                  stroke={on ? 'var(--hot)' : 'var(--rule)'}
                  strokeWidth={on ? 1.8 : 1.2}
                  markerEnd={`url(#${on ? 'arch-arrow-on' : 'arch-arrow'})`}
                />
                {r.kind && (
                  <>
                    {/* Knocked out of the line behind it, so the verb is legible
                        wherever it lands rather than striped by its own edge. */}
                    <rect
                      x={at.x - width / 2}
                      y={at.y - 6.5}
                      width={width}
                      height={12}
                      rx="2"
                      fill={on ? 'var(--hot-wash)' : 'var(--panel)'}
                    />
                    <text
                      x={at.x}
                      y={at.y + 2.5}
                      textAnchor="middle"
                      fontSize="8.5"
                      letterSpacing="0.06em"
                      fontFamily="var(--font-mono)"
                      fill={on ? 'var(--hot-ink)' : 'var(--ink-dim)'}
                    >
                      {r.kind}
                    </text>
                  </>
                )}
              </g>
            )
          })}

          {nodes.map(n => {
            const on = hover === n.name
            const near = lit.has(n.name)
            const dim = hover && !near
            return (
              <g
                key={n.name}
                opacity={dim ? 0.3 : 1}
                className="cursor-default"
                style={{ transition: 'opacity .15s' }}
                onMouseEnter={() => setHover(n.name)}
                onMouseLeave={() => setHover(null)}
              >
                <rect
                  x={n.x}
                  y={n.y}
                  width={NODE_W}
                  height={NODE_H}
                  rx="4"
                  fill={on ? 'var(--hot-wash)' : 'var(--panel)'}
                  stroke={on ? 'var(--hot)' : 'var(--ink)'}
                  strokeWidth={on ? 1.8 : 1.1}
                />
                <text
                  x={n.x + 10}
                  y={n.y + 18}
                  fontSize="10.5"
                  fontWeight="700"
                  fontFamily="var(--font-mono)"
                  fill="var(--ink)"
                >
                  {n.name.length > 17 ? `${n.name.slice(0, 16)}…` : n.name}
                </text>
                {n.type && (
                  <text
                    x={n.x + 10}
                    y={n.y + 32}
                    fontSize="8"
                    letterSpacing="0.1em"
                    fontFamily="var(--font-mono)"
                    fill={on ? 'var(--hot-ink)' : 'var(--ink-dim)'}
                  >
                    {n.type.toUpperCase()}
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
            one to see what it is and what it touches.
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
