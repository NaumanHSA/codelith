import { useId, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Icon, type IconName } from '../../lib/icons'
import type { BrandName } from '../../lib/brands'
import { kindOf, lookOf } from '../../lib/kinds'
import type { Atlas, FileCalls } from '../../lib/types'
import { IconTile } from '../primitives'
import { shortName, type Adjacency } from './graph'
import { TIERS, type ComponentEdge, type ComponentInfo, type RequestPath } from './model'

/* ------------------------------------------------------------------ *
 * The flow under the map: whatever is selected, flattened to a left-to-
 * right diagram a reader can follow without turning the camera. Arrows
 * always run the way the call goes, from the code that calls to the code
 * it calls, and dashes travel along them in that direction.
 *
 *   nothing selected   every component, callers on the left, the data
 *                      and the outside world on the right
 *   a component        what uses it → it → what it uses
 *   a file             who calls into it → it → what it calls, with the
 *                      function names on the arrows where analysis
 *                      recorded the calls
 *   its request path   from the nearest entry point, through this file,
 *                      to the nearest data or outside service
 *
 * Every box is a link: walking the code here moves the map too.
 * ------------------------------------------------------------------ */

export type Selection = { kind: 'file'; i: number } | { kind: 'component'; c: number } | null
export type FlowTab = 'links' | 'path' | 'flows'

export interface FNode {
  key: string
  title: string
  sub?: string
  icon?: IconName
  brand?: BrandName
  color: string
  current?: boolean
  mono?: boolean
  muted?: boolean
  onClick?: () => void
  onHover?: (on: boolean) => void
  hint?: string
}

export interface FEdge {
  from: string
  to: string
  label?: string
  /** Shown instead of nothing while either end is pointed at. */
  hoverLabel?: string
  /** Hot, and travelled by a dot. */
  strong?: boolean
  /** Drawn only while either end is pointed at: links that run against the columns. */
  quiet?: boolean
  /** A link that breaks a rule: drawn in the warning colour, whatever else it is. */
  bad?: boolean
}

const NODE_H = 46
const HEAD = 26
const GAP_Y = 12
const GAP_X = 64
const PAD = 16
const MAX_SIDE = 6
const MAX_W = 1280

function names(list: string[], max = 2): string {
  const uniq = [...new Set(list.map(n => n.split('.').pop() || n))]
  const shown = uniq.slice(0, max).map(n => `${n}()`)
  return uniq.length > max ? `${shown.join(', ')} +${uniq.length - max}` : shown.join(', ')
}

export function fileNode(atlas: Atlas, i: number, extra: Partial<FNode> = {}): FNode {
  const n = atlas.nodes[i]
  const look = lookOf(n)
  const kind = kindOf(n.kind)
  return {
    key: `f${i}`,
    title: n.fact ? n.path : shortName(n.path),
    sub: n.fact ? kind.label : `${kind.label} · ${atlas.components[n.component]?.name ?? ''}`,
    icon: look.icon,
    brand: look.brand,
    color: kind.color,
    mono: true,
    hint: n.path,
    ...extra,
  }
}

function more(key: string, n: number, what: string): FNode {
  return { key, title: `+${n} more`, sub: what, color: 'var(--ink-dim)', muted: true }
}

/* ── the diagram ─────────────────────────────────────────────────────── */

export function Diagram({
  columns,
  edges,
  heads,
  reduced,
}: {
  columns: FNode[][]
  edges: FEdge[]
  heads?: { name: string; hint: string }[]
  reduced: boolean
}) {
  const box = useRef<HTMLDivElement>(null)
  const uid = useId().replace(/:/g, '')
  const [width, setWidth] = useState(800)
  const [hot, setHot] = useState<string | null>(null)

  useLayoutEffect(() => {
    const el = box.current
    if (!el) return
    const ro = new ResizeObserver(() => setWidth(el.clientWidth))
    ro.observe(el)
    setWidth(el.clientWidth)
    return () => ro.disconnect()
  }, [])

  const kept = columns.map((c, k) => [c, heads?.[k]] as const).filter(([c]) => c.length)
  const cols = kept.map(([c]) => c)
  const colHeads = heads ? kept.map(([, h]) => h) : null
  const top0 = colHeads ? HEAD : 0
  const n = cols.length
  const nodeW = Math.max(150, Math.min(230, (width - PAD * 2 - GAP_X * (n - 1)) / Math.max(1, n)))
  // Wide screens get a diagram of a readable width, centred, not columns a metre apart.
  const inner = Math.max(Math.min(width, MAX_W), PAD * 2 + n * nodeW + (n - 1) * GAP_X)
  const step = n > 1 ? (inner - PAD * 2 - nodeW) / (n - 1) : 0
  const tallest = Math.max(1, ...cols.map(c => c.length))
  const height = PAD * 2 + top0 + tallest * NODE_H + (tallest - 1) * GAP_Y

  const at = new Map<string, { x: number; y: number; col: number }>()
  cols.forEach((col, k) => {
    const h = col.length * NODE_H + (col.length - 1) * GAP_Y
    const top = top0 + (height - top0 - h) / 2
    const x = n > 1 ? PAD + k * step : (inner - nodeW) / 2
    col.forEach((node, r) => at.set(node.key, { x, y: top + r * (NODE_H + GAP_Y), col: k }))
  })

  const drawn = edges
    .map(e => {
      const a = at.get(e.from)
      const b = at.get(e.to)
      if (!a || !b) return null
      const forward = b.col > a.col
      const x1 = forward ? a.x + nodeW : a.x + nodeW / 2
      const y1 = forward ? a.y + NODE_H / 2 : a.y + NODE_H
      const x2 = forward ? b.x : b.x + nodeW / 2
      const y2 = forward ? b.y + NODE_H / 2 : b.y + NODE_H
      const dx = Math.max(30, (x2 - x1) * 0.45)
      // A link that goes back (a cycle) loops under the boxes instead of through them.
      const d = forward
        ? `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`
        : `M${x1},${y1} C${x1},${y1 + 40} ${x2},${y2 + 40} ${x2},${y2}`
      const mid = forward
        ? { x: (x1 + x2) / 2, y: (y1 + y2) / 2 }
        : { x: (x1 + x2) / 2, y: Math.max(y1, y2) + 30 }
      const lit = hot !== null && (e.from === hot || e.to === hot)
      if (e.quiet && !lit) return null
      return { e, d, mid, lit }
    })
    .filter(Boolean) as { e: FEdge; d: string; mid: { x: number; y: number }; lit: boolean }[]

  const anyLit = hot !== null

  return (
    <div ref={box} className="relative w-full overflow-x-auto">
      {/* Marker ids are per diagram: two on one page (or in two tabs) must not share them. */}
      <div className="relative mx-auto" style={{ width: inner, height: height + 24 }}>
        <svg className="pointer-events-none absolute inset-0" width={inner} height={height + 24} aria-hidden>
          <defs>
            <marker id={`${uid}-arrow`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0,1 L9,5 L0,9 z" fill="var(--ink-dim)" />
            </marker>
            <marker id={`${uid}-arrow-hot`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0,1 L9,5 L0,9 z" fill="var(--hot)" />
            </marker>
            <marker id={`${uid}-arrow-bad`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0,1 L9,5 L0,9 z" fill="var(--bad)" />
            </marker>
          </defs>
          {drawn.map(({ e, d, lit }, k) => {
            const strong = e.strong || lit || e.bad
            const colour = e.bad ? 'var(--bad)' : strong ? 'var(--hot)' : 'var(--line-2)'
            return (
              <g key={k} opacity={anyLit && !lit ? 0.25 : 1}>
                <path
                  d={d}
                  fill="none"
                  stroke={colour}
                  strokeWidth={strong ? 1.6 : 1.3}
                  markerEnd={`url(#${uid}-${e.bad ? 'arrow-bad' : strong ? 'arrow-hot' : 'arrow'})`}
                />
                {!reduced && (
                  <path
                    d={d}
                    fill="none"
                    stroke={e.bad ? 'var(--bad)' : strong ? 'var(--hot-ink)' : 'var(--ink-dim)'}
                    strokeWidth={strong ? 2 : 1.4}
                    strokeDasharray="3 13"
                    strokeLinecap="round"
                    style={{ animation: `flow ${strong ? 26 : 40}s linear infinite` }}
                  />
                )}
                {!reduced && strong && (
                  <circle r="3.2" fill={e.bad ? 'var(--bad)' : 'var(--hot)'}>
                    <animateMotion dur="1.8s" repeatCount="indefinite" path={d} begin={`-${(k % 5) * 0.33}s`} />
                  </circle>
                )}
              </g>
            )
          })}
        </svg>

        {colHeads &&
          colHeads.map((h, k) =>
            h ? (
              <span
                key={`h${k}`}
                className="absolute top-2 truncate text-[12px] font-semibold text-ink-mid"
                style={{ left: n > 1 ? PAD + k * step : (inner - nodeW) / 2, width: nodeW }}
                title={h.hint}
              >
                {h.name}
              </span>
            ) : null,
          )}

        {drawn.map(({ e, mid, lit }, k) => {
          const text = lit ? (e.label ?? e.hoverLabel) : e.label
          return text && (e.strong || e.bad || lit || !anyLit) ? (
            <span
              key={`l${k}`}
              className={`pointer-events-none absolute z-[1] max-w-[180px] -translate-x-1/2 -translate-y-1/2 truncate rounded-md border px-1.5 py-px font-mono text-[11px] ${
                e.bad
                  ? 'border-bad/40 bg-bad-wash text-bad'
                  : e.strong || lit
                    ? 'border-hot-edge bg-hot-wash text-hot-ink'
                    : 'border-rule bg-paper text-ink-dim'
              }`}
              style={{ left: mid.x, top: mid.y }}
              title={text}
            >
              {text}
            </span>
          ) : null
        })}

        {cols.flat().map(node => {
          const p = at.get(node.key)!
          const Tag = node.onClick ? 'button' : 'div'
          return (
            <Tag
              key={node.key}
              type={node.onClick ? 'button' : undefined}
              onClick={node.onClick}
              onMouseEnter={() => {
                setHot(node.key)
                node.onHover?.(true)
              }}
              onMouseLeave={() => {
                setHot(h => (h === node.key ? null : h))
                node.onHover?.(false)
              }}
              title={node.hint ?? node.title}
              className={`absolute z-[2] flex items-center gap-2.5 rounded-lg border px-2.5 text-left transition-colors ${
                node.current
                  ? 'border-hot bg-hot-wash shadow-[0_0_0_3px_color-mix(in_srgb,var(--hot)_18%,transparent)]'
                  : node.muted
                    ? 'border-dashed border-rule bg-transparent'
                    : 'border-rule bg-panel hover:border-line-2 hover:bg-hover'
              } ${node.onClick ? 'cursor-pointer' : 'cursor-default'}`}
              style={{ left: p.x, top: p.y, width: nodeW, height: NODE_H }}
            >
              {!node.muted && (
                <IconTile icon={node.icon} brand={node.brand} color={node.color} tint={!node.brand} size={26} />
              )}
              <span className="flex min-w-0 flex-1 flex-col leading-tight">
                <span
                  className={`truncate text-[12.5px] font-medium ${node.mono ? 'font-mono' : ''} ${
                    node.muted ? 'text-ink-dim' : 'text-ink'
                  }`}
                >
                  {node.title}
                </span>
                {node.sub && <span className="mt-0.5 truncate text-[11.5px] text-ink-dim">{node.sub}</span>}
              </span>
            </Tag>
          )
        })}
      </div>
    </div>
  )
}

/* ── the panel ───────────────────────────────────────────────────────── */

export default function FlowPanel({
  atlas,
  adj,
  components,
  edges,
  tiers,
  selection,
  calls,
  path,
  tab,
  onTab,
  onPickFile,
  onPickComponent,
  onFocusComponent,
  reduced,
  open,
  onToggle,
  fill = false,
  stretch = false,
  onExpand,
  flowsView,
}: {
  atlas: Atlas
  adj: Adjacency
  components: ComponentInfo[]
  edges: ComponentEdge[]
  /** The parts by column, as `tierColumns` orders them for the map. */
  tiers: { tier: number; parts: number[] }[]
  selection: Selection
  calls?: FileCalls
  path: RequestPath | null
  tab: FlowTab
  onTab: (t: FlowTab) => void
  onPickFile: (i: number) => void
  onPickComponent: (c: number) => void
  onFocusComponent: (c: number | null) => void
  reduced: boolean
  open: boolean
  onToggle: () => void
  /** Given the whole height, with the 3D map folded away. */
  fill?: boolean
  /** Fill whatever height its box is given (the splitter sets it). */
  stretch?: boolean
  /** Take the whole height, or give half back to the map. */
  onExpand?: () => void
  /** What the Flows tab shows: every way into the code and the path one takes. */
  flowsView?: React.ReactNode
}) {
  const compNode = (c: number, extra: Partial<FNode> = {}): FNode => {
    const info = components[c]
    const top = info.dominant[0]
    const kind = kindOf(top)
    return {
      key: `c${c}`,
      title: info.name,
      sub: `${info.members.length} file${info.members.length === 1 ? '' : 's'}${top ? ` · mostly ${kind.plural.toLowerCase()}` : ''}`,
      icon: kind.icon,
      color: kind.color,
      hint: info.description || info.name,
      onClick: () => onPickComponent(c),
      onHover: on => onFocusComponent(on ? c : null),
      ...extra,
    }
  }

  const view = useMemo((): {
    title: string
    lead: React.ReactNode
    columns: FNode[][]
    edges: FEdge[]
    heads?: { name: string; hint: string }[]
  } => {
    /* nothing selected: the whole system, in the map's columns */
    if (!selection) {
      const col = new Map<number, number>()
      tiers.forEach((t, k) => t.parts.forEach(c => col.set(c, k)))
      return {
        title: 'How the parts connect',
        lead: (
          <>
            Read left to right, the way work moves through the code: each arrow runs from the part that calls to
            the part it calls. Point at a part to see all its links; pick one to open it.
          </>
        ),
        heads: tiers.map(t => TIERS[t.tier]),
        columns: tiers.map(t => t.parts.map(c => compNode(c))),
        edges: edges
          .filter(e => col.has(e.from) && col.has(e.to))
          .map(e => ({
            from: `c${e.from}`,
            to: `c${e.to}`,
            label: e.verb ?? undefined,
            hoverLabel: `${e.imports} import${e.imports === 1 ? '' : 's'}`,
            // A relation the architecture pass named is always drawn: it is often the one
            // link imports cannot show, such as a web UI calling its API over HTTP.
            quiet: !e.verb && col.get(e.from)! >= col.get(e.to)!,
          })),
      }
    }

    /* a component: what uses it, it, what it uses */
    if (selection.kind === 'component') {
      const c = selection.c
      const into = edges.filter(e => e.to === c).sort((a, b) => b.imports - a.imports)
      const out = edges.filter(e => e.from === c).sort((a, b) => b.imports - a.imports)
      const label = (e: ComponentEdge) => e.verb ?? `${e.imports} import${e.imports === 1 ? '' : 's'}`
      const left = into.slice(0, MAX_SIDE).map(e => compNode(e.from, { key: `in:c${e.from}` }))
      const right = out.slice(0, MAX_SIDE).map(e => compNode(e.to, { key: `out:c${e.to}` }))
      if (into.length > MAX_SIDE) left.push(more('more-in', into.length - MAX_SIDE, 'more callers'))
      if (out.length > MAX_SIDE) right.push(more('more-out', out.length - MAX_SIDE, 'more it uses'))
      const name = components[c].name
      const list = (xs: ComponentEdge[], pick: (e: ComponentEdge) => number) =>
        xs.slice(0, 3).map(e => components[pick(e)].name).join(', ') + (xs.length > 3 ? ` and ${xs.length - 3} more` : '')
      return {
        title: name,
        lead: (
          <>
            <b className="font-medium text-ink">{name}</b>
            {into.length ? <> is used by {list(into, e => e.from)}</> : <> is used by nothing else here</>}
            {out.length ? <>, and uses {list(out, e => e.to)}.</> : <>, and uses nothing else here.</>}
          </>
        ),
        columns: [left, [compNode(c, { current: true, onClick: undefined })], right],
        edges: [
          ...into.slice(0, MAX_SIDE).map(e => ({ from: `in:c${e.from}`, to: `c${c}`, label: label(e), strong: true })),
          ...out.slice(0, MAX_SIDE).map(e => ({ from: `c${c}`, to: `out:c${e.to}`, label: label(e), strong: true })),
        ],
      }
    }

    const i = selection.i
    const node = atlas.nodes[i]
    const incomingBy = new Map<string, string[]>()
    const outgoingBy = new Map<string, string[]>()
    if (calls && calls.path === node.path) {
      for (const c of calls.incoming) incomingBy.set(c.path, [...(incomingBy.get(c.path) ?? []), c.callee])
      for (const c of calls.outgoing) outgoingBy.set(c.path, [...(outgoingBy.get(c.path) ?? []), c.callee])
    }
    const pick = (j: number) => () => onPickFile(j)

    /* a file's request path */
    if (tab === 'path' && path) {
      const chain = [...path.upstream, i, ...path.downstream]
      const fe: FEdge[] = []
      for (let k = 0; k + 1 < chain.length; k++) {
        const a = chain[k]
        const b = chain[k + 1]
        let label: string | undefined
        if (b === i) label = names(incomingBy.get(atlas.nodes[a].path) ?? []) || undefined
        if (a === i) label = names(outgoingBy.get(atlas.nodes[b].path) ?? []) || undefined
        fe.push({ from: `p${k}`, to: `p${k + 1}`, label, strong: true })
      }
      const first = path.upstream[0]
      const last = path.downstream[path.downstream.length - 1]
      const nm = (j: number) => <span className="font-mono text-ink">{atlas.nodes[j].fact ? atlas.nodes[j].path : shortName(atlas.nodes[j].path)}</span>
      return {
        title: 'Request path',
        lead: (
          <>
            {first !== undefined ? (
              <>
                A request enters at {nm(first)} ({kindOf(atlas.nodes[first].kind).label.toLowerCase()})
                {path.upstream.length > 1 ? `, passes ${path.upstream.length - 1} more file${path.upstream.length > 2 ? 's' : ''}` : ''} and
                reaches {nm(i)}
              </>
            ) : (
              <>Nothing that receives requests leads to {nm(i)} within eight imports</>
            )}
            {last !== undefined ? (
              <>
                ; from here it goes on to {nm(last)} ({kindOf(atlas.nodes[last].kind).label.toLowerCase()}).
              </>
            ) : (
              <>, and it reaches no data or outside service from here.</>
            )}
          </>
        ),
        columns: chain.map((j, k) => [
          fileNode(atlas, j, j === i ? { key: `p${k}`, current: true } : { key: `p${k}`, onClick: pick(j) }),
        ]),
        edges: fe,
      }
    }

    /* a file: who calls in, what it calls */
    const rank = (byPath: Map<string, string[]>) => (a: number, b: number) =>
      (byPath.get(atlas.nodes[b].path)?.length ?? 0) - (byPath.get(atlas.nodes[a].path)?.length ?? 0) ||
      atlas.nodes[a].path.localeCompare(atlas.nodes[b].path)
    const ins = [...adj.dependants[i]].sort(rank(incomingBy))
    const outs = [...adj.uses[i]].sort(rank(outgoingBy))
    const left = ins.slice(0, MAX_SIDE).map(j => fileNode(atlas, j, { key: `in:f${j}`, onClick: pick(j) }))
    const right = outs.slice(0, MAX_SIDE).map(j => fileNode(atlas, j, { key: `out:f${j}`, onClick: pick(j) }))
    if (ins.length > MAX_SIDE) left.push(more('more-in', ins.length - MAX_SIDE, 'more import it'))
    if (outs.length > MAX_SIDE) right.push(more('more-out', outs.length - MAX_SIDE, 'more it imports'))
    const fnIn = calls && calls.path === node.path ? new Set(calls.incoming.map(c => c.callee)).size : 0
    return {
      title: node.fact ? node.path : shortName(node.path),
      lead: (
        <>
          {ins.length ? `${ins.length} file${ins.length === 1 ? '' : 's'} import it` : 'Nothing imports it'}
          {fnIn ? `, calling ${fnIn} of its functions` : ''}; it imports{' '}
          {outs.length ? `${outs.length} file${outs.length === 1 ? '' : 's'}` : 'nothing here'}.
          {(ins.length > 0 || outs.length > 0) && ' Function names on an arrow are the calls analysis recorded.'}
        </>
      ),
      columns: [left, [fileNode(atlas, i, { current: true })], right],
      edges: [
        ...ins.slice(0, MAX_SIDE).map(j => ({
          from: `in:f${j}`,
          to: `f${i}`,
          label: names(incomingBy.get(atlas.nodes[j].path) ?? []) || undefined,
          strong: true,
        })),
        ...outs.slice(0, MAX_SIDE).map(j => ({
          from: `f${i}`,
          to: `out:f${j}`,
          label: names(outgoingBy.get(atlas.nodes[j].path) ?? []) || undefined,
          strong: true,
        })),
      ],
    }
    // compNode closes over the callbacks, which are stable for the page's life.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selection, components, edges, tiers, atlas, adj, calls, tab, path])

  const isFile = selection?.kind === 'file'
  const flowsTab = tab === 'flows' && flowsView !== undefined
  const tabs: [FlowTab, string, IconName][] = [
    ...((isFile
      ? [
          ['links', 'Calls in and out', 'arrow-left-right'],
          ['path', 'Request path', 'route'],
        ]
      : [['links', selection ? 'Links' : 'Parts', 'boxes']]) as [FlowTab, string, IconName][]),
    ...(flowsView !== undefined ? ([['flows', 'Flows', 'workflow']] as [FlowTab, string, IconName][]) : []),
  ]

  return (
    <section
      className={`flex min-h-0 flex-col rounded-[10px] border border-rule bg-panel ${fill || stretch ? 'flex-1' : ''}`}
      aria-label="Flow"
    >
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-4 py-2.5">
        <Icon name="workflow" size={16} className="text-hot" />
        <h2 className="min-w-0 truncate text-[13.5px] font-semibold text-ink">
          {flowsTab ? 'How requests flow' : view.title}
        </h2>
        {tabs.length > 1 && (
          <div className="flex gap-0.5 rounded-lg border border-rule bg-paper p-[3px]" role="tablist" aria-label="Flow view">
            {tabs.map(([t, label, icon]) => (
              <button
                key={t}
                type="button"
                role="tab"
                aria-selected={tab === t}
                onClick={() => onTab(t)}
                className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[12.5px] font-medium transition-colors ${
                  tab === t ? 'bg-sunk text-ink shadow-[inset_0_0_0_1px_var(--line-2)]' : 'text-ink-mid hover:text-ink'
                }`}
              >
                <Icon name={icon} size={13} />
                {label}
              </button>
            ))}
          </div>
        )}
        <div className="ml-auto flex items-center gap-0.5">
          {open && onExpand && (
            <button
              type="button"
              onClick={onExpand}
              title={fill ? 'Give half the height back to the 3D map' : 'Fold the 3D map away and give this the whole height'}
              className="flex items-center gap-1.5 rounded-md px-2 py-1 text-[12.5px] text-ink-mid transition-colors hover:bg-hover hover:text-ink"
            >
              <Icon name={fill ? 'minimize-2' : 'maximize-2'} size={14} />
              {fill ? 'Show the map too' : 'Expand'}
            </button>
          )}
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={open}
            title={open ? 'Fold the flow away and give the 3D map the whole height' : 'Show the flow under the map'}
            className="flex items-center gap-1.5 rounded-md px-2 py-1 text-[12.5px] text-ink-mid transition-colors hover:bg-hover hover:text-ink"
          >
            {open ? 'Hide' : 'Show the flow'}
            <Icon name={open ? 'chevron-down' : 'chevron-up'} size={14} />
          </button>
        </div>
      </header>
      {open && flowsTab && (
        <div className={`flex min-h-0 flex-col border-t border-rule ${fill || stretch ? 'flex-1' : 'h-[320px]'}`}>
          {flowsView}
        </div>
      )}
      {open && !flowsTab && (
        <div className={`flex min-h-0 flex-col gap-2 border-t border-rule ${fill || stretch ? 'flex-1' : ''}`}>
          <p className="px-4 pt-2.5 text-[13px] leading-relaxed text-ink-mid">{view.lead}</p>
          <div className={`min-h-0 overflow-y-auto pb-1 ${fill || stretch ? 'flex-1' : 'max-h-[300px]'}`}>
            {view.columns.some(c => c.length) ? (
              <Diagram columns={view.columns} edges={view.edges} heads={view.heads} reduced={reduced} />
            ) : (
              <p className="px-4 pb-3 text-[13px] text-ink-dim">Nothing to draw.</p>
            )}
          </div>
        </div>
      )}
    </section>
  )
}

