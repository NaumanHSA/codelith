import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../lib/api'
import type { FileEntry, FileTree, ModuleEntry, Modules, SymbolEntry } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * The knowledge base, as something you walk into.
 *
 * The list this replaces was honest and unreadable: twenty modules
 * with a paragraph each is a wall of prose, and the shape of the
 * codebase - which roles carry the weight, what sits under them - was
 * nowhere in it.
 *
 * So: the project at the centre, roles on the first ring, and each
 * ring outward is one more question answered. Click a role and its
 * modules fan out; click a module and its files do; click a file and
 * the symbols the parser found in it appear. Four levels, and the last
 * one lands you on a line of source.
 *
 * **Angles are apportioned by what is currently visible.** Every node
 * gets a wedge sized by the number of leaves beneath it, recomputed on
 * every expansion. That is what keeps an expanded branch readable
 * without a hand-tuned rule per depth: a module with nine files takes
 * nine times the arc of a collapsed neighbour, because it needs it.
 *
 * The prose does not disappear - it moves to the panel beside the
 * canvas, where one selected thing is described at a time instead of
 * twenty at once.
 * ------------------------------------------------------------------ */

/**
 * How far the ring sits from the hub.
 *
 * A single ring, so this is a reach rather than a spacing: far enough that the
 * labels radiating off it have somewhere to go, near enough that the whole
 * wheel and its labels fit the frame at roughly life size.
 */
const RING_R = 186

/** Below this much arc a label cannot be read and is not drawn. The dot stays,
 *  the hover title stays, and the details panel says the rest. Better than a
 *  ring of overlapping text that has to be zoomed into to be dismissed. */
const MIN_ARC_FOR_LABEL = 26

/** How long the wheel takes to re-centre. */
const TWEEN_MS = 520

const ROLE_INK: Record<string, string> = {
  api: 'var(--hot)',
  service: 'var(--ink)',
  worker: 'var(--ink)',
  cli: 'var(--warn)',
  config: 'var(--ink-dim)',
  utility: 'var(--ink-dim)',
  schema: 'var(--ink-mid)',
  model: 'var(--ink-mid)',
  data_access: 'var(--ink-mid)',
  infra: 'var(--warn)',
  ui: 'var(--hot)',
  test: 'var(--ok)',
}

const roleInk = (role: string) => ROLE_INK[role.toLowerCase()] ?? 'var(--ink-mid)'

type Kind = 'root' | 'role' | 'module' | 'file' | 'symbol'

type Node = {
  id: string
  kind: Kind
  /** What the ring shows. Short by construction: a file is its basename. */
  label: string
  /** What the panel and the hover title show. */
  full: string
  parent: string | null
  children: Node[]
  /** True when the children are fetched rather than derived. */
  lazy?: boolean
  role?: string
  module?: ModuleEntry
  file?: FileEntry
  path?: string
  symbol?: SymbolEntry
}

type Polar = { r: number; a: number }

/* ── The tree ─────────────────────────────────────────────────────── */

function buildTree(
  title: string,
  modules: Modules,
  files: Map<string, FileEntry>,
  symbols: Map<string, SymbolEntry[]>,
): { root: Node; byId: Map<string, Node> } {
  const byRole = new Map<string, ModuleEntry[]>()
  for (const m of modules.modules) {
    const key = m.role || 'unknown'
    byRole.set(key, [...(byRole.get(key) ?? []), m])
  }

  const root: Node = {
    id: 'root',
    kind: 'root',
    label: title,
    full: title,
    parent: null,
    children: [],
  }

  // Heaviest role first, so the wheel reads clockwise from what matters most.
  const roles = [...byRole.entries()].sort(
    (a, b) =>
      b[1].reduce((n, m) => n + m.loc, 0) - a[1].reduce((n, m) => n + m.loc, 0),
  )

  for (const [role, entries] of roles) {
    const roleNode: Node = {
      id: `role:${role}`,
      kind: 'role',
      label: role.replace(/_/g, ' '),
      full: role,
      parent: 'root',
      children: [],
      role,
    }
    for (const m of entries) {
      const moduleNode: Node = {
        id: `mod:${m.path}`,
        kind: 'module',
        label: m.name,
        full: m.name,
        parent: roleNode.id,
        children: [],
        role,
        module: m,
      }
      for (const path of m.files) {
        const fileNode: Node = {
          id: `file:${path}`,
          kind: 'file',
          // The module already named the directory; repeating it costs the arc
          // the name needs.
          label: path.split('/').pop() ?? path,
          full: path,
          parent: moduleNode.id,
          children: [],
          lazy: true,
          role,
          path,
          file: files.get(path),
        }
        for (const s of symbols.get(path) ?? []) {
          fileNode.children.push({
            id: `sym:${path}:${s.qname || s.name}:${s.line}`,
            kind: 'symbol',
            label: s.name,
            full: `${s.qname || s.name} · ${s.kind || 'symbol'} · line ${s.line}`,
            parent: fileNode.id,
            children: [],
            role,
            path,
            symbol: s,
          })
        }
        moduleNode.children.push(fileNode)
      }
      roleNode.children.push(moduleNode)
    }
    root.children.push(roleNode)
  }

  const byId = new Map<string, Node>()
  const walk = (n: Node) => {
    byId.set(n.id, n)
    n.children.forEach(walk)
  }
  walk(root)
  return { root, byId }
}

/* ── Layout ───────────────────────────────────────────────────────── */

/**
 * Where every visible node sits, in polar coordinates.
 *
 * The one rule: a node's angular wedge is its share of its parent's wedge, by
 * leaf count of what is *visible*. Collapsed subtrees count as one leaf, so
 * closing a branch gives its space back to its siblings rather than leaving a
 * hole in the wheel.
 */
function layout(focus: Node): {
  places: Map<string, Polar>
  arcs: Map<string, number>
  visible: Node[]
  reach: number
} {
  const places = new Map<string, Polar>([[focus.id, { r: 0, a: 0 }]])
  const arcs = new Map<string, number>([[focus.id, Infinity]])
  const visible: Node[] = [focus]

  const children = focus.children
  const each = children.length ? (Math.PI * 2) / children.length : 0

  children.forEach((child, i) => {
    // Starting at -90 degrees puts the first child at the top, and the tree is
    // already ordered by weight, so the wheel reads clockwise from the heaviest.
    const angle = -Math.PI / 2 + each * i
    places.set(child.id, { r: RING_R, a: angle })
    arcs.set(child.id, each * RING_R)
    visible.push(child)
  })

  return { places, arcs, visible, reach: children.length ? RING_R : 0 }
}

const xy = (p: Polar) => ({ x: Math.cos(p.a) * p.r, y: Math.sin(p.a) * p.r })

/** A smooth radial link: out along the parent's angle, round to the child's. */
function linkPath(from: Polar, to: Polar): string {
  const a = xy(from)
  const b = xy(to)
  const mid = (from.r + to.r) / 2
  const c1 = xy({ r: mid, a: from.a })
  const c2 = xy({ r: mid, a: to.a })
  return `M${a.x} ${a.y} C${c1.x} ${c1.y} ${c2.x} ${c2.y} ${b.x} ${b.y}`
}

const easeOut = (t: number) => 1 - Math.pow(1 - t, 3)

/* ── The component ────────────────────────────────────────────────── */

export default function KnowledgeGraph({
  title,
  modules,
  files,
  projectId,
}: {
  title: string
  modules: Modules
  files: FileTree | undefined
  projectId: number
}) {
  const [focusId, setFocusId] = useState('root')
  const [selected, setSelected] = useState<string>('root')
  const [symbols, setSymbols] = useState<Map<string, SymbolEntry[]>>(new Map())
  const [loading, setLoading] = useState<Set<string>>(new Set())
  const [view, setView] = useState({ k: 1, x: 0, y: 0 })
  // The zoom follows the graph until the reader takes hold of it, and the fit
  // button hands control back. Without this, opening a fourth level either
  // clips or forces everyone to zoom out by hand every single time.
  const [steered, setSteered] = useState(false)

  const fileIndex = useMemo(
    () => new Map((files?.files ?? []).map(f => [f.path, f])),
    [files],
  )

  const { root, byId } = useMemo(
    () => buildTree(title, modules, fileIndex, symbols),
    [title, modules, fileIndex, symbols],
  )

  const focus = byId.get(focusId) ?? root
  const target = useMemo(() => layout(focus), [focus])
  const trail = useMemo(() => {
    const path: Node[] = []
    let node: Node | undefined = focus
    while (node) {
      path.unshift(node)
      node = node.parent ? byId.get(node.parent) : undefined
    }
    return path
  }, [focus, byId])

  /* The tween. New nodes start where their parent is, so a branch grows out of
     the thing it belongs to rather than fading in on top of it. */
  const [drawn, setDrawn] = useState<Map<string, Polar>>(target.places)
  const drawnRef = useRef(drawn)
  drawnRef.current = drawn
  const frame = useRef(0)

  const rings = useMemo(
    () =>
      [...new Set([...target.places.values()].map(p => Math.round(p.r)))]
        .filter(r => r > 0)
        .sort((a, b) => a - b),
    [target],
  )

  /**
   * How far the drawing actually extends: the ring, plus the longest label
   * hanging off it.
   *
   * A fixed allowance wastes the frame when the labels are short - five roles
   * with names like UTILITY left a third of the canvas empty - and clips when
   * they are long, which a ring of qualified symbol names manages easily.
   */
  const extent = useMemo(() => {
    const longest = Math.max(
      0,
      ...target.visible
        .filter(n => n.id !== focusId)
        .map(n => trim(n.label, 20).length),
    )
    return target.reach + 18 + longest * 5.6
  }, [target, focusId])

  // 292 is the visible half-height of the viewBox below, less a hair of margin.
  useEffect(() => {
    if (steered) return
    setView({ k: Math.min(1.7, Math.max(0.4, 292 / extent)), x: 0, y: 0 })
  }, [extent, steered])

  useEffect(() => {
    const from = new Map<string, Polar>()
    for (const node of target.visible) {
      const previous = drawnRef.current.get(node.id)
      if (previous) {
        from.set(node.id, previous)
        continue
      }
      const parent = node.parent ? drawnRef.current.get(node.parent) : undefined
      const here = target.places.get(node.id)!
      from.set(node.id, parent ?? { r: 0, a: here.a })
    }

    const started = performance.now()
    const step = (now: number) => {
      const t = Math.min(1, (now - started) / TWEEN_MS)
      const e = easeOut(t)
      const next = new Map<string, Polar>()
      for (const node of target.visible) {
        const a0 = from.get(node.id)!
        const a1 = target.places.get(node.id)!
        next.set(node.id, {
          r: a0.r + (a1.r - a0.r) * e,
          // Angles are already close after a re-apportionment, so a plain
          // interpolation is right; nothing here ever crosses the seam.
          a: a0.a + (a1.a - a0.a) * e,
        })
      }
      setDrawn(next)
      if (t < 1) frame.current = requestAnimationFrame(step)
    }
    frame.current = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame.current)
  }, [target])

  /* Symbols are the only level that is fetched. A file's chunks are stored per
     file, so asking for all of them up front would be dozens of calls for
     material nobody has asked to see. */
  const loadSymbols = useCallback(
    async (path: string) => {
      if (symbols.has(path) || loading.has(path)) return
      setLoading(s => new Set(s).add(path))
      try {
        const file = await api.file(projectId, path)
        setSymbols(m => new Map(m).set(path, file.symbols))
      } catch {
        // An unreadable file simply has no symbols to fan out. The node stays,
        // and the panel still says what is known about it.
        setSymbols(m => new Map(m).set(path, []))
      } finally {
        setLoading(s => {
          const next = new Set(s)
          next.delete(path)
          return next
        })
      }
    },
    [projectId, symbols, loading],
  )

  /**
   * One click, two outcomes, decided by where the node already is.
   *
   * The centre goes back up to its parent; anything on the ring goes in. A
   * symbol is a leaf and only ever selects, because there is nothing under it
   * but a line of source, and the panel offers that as a link.
   */
  const activate = useCallback(
    (node: Node) => {
      setSelected(node.id)

      if (node.id === focusId) {
        if (node.parent) setFocusId(node.parent)
        return
      }
      if (node.kind === 'symbol') return
      // A file's symbols are fetched, so the ring fills a moment after the wheel
      // has re-centred rather than blocking the movement on a request.
      if (node.path) void loadSymbols(node.path)
      setFocusId(node.id)
    },
    [focusId, loadSymbols],
  )

  /* ── Zoom and pan ─────────────────────────────────────────────── */
  const svgRef = useRef<SVGSVGElement>(null)
  const drag = useRef<{ x: number; y: number } | null>(null)
  // Whether this press has turned into a pan yet. Without it every click on a
  // node was swallowed: the press that selects a node also starts a drag, so a
  // guard on "is a drag in progress" rejects the very click that began it.
  const moved = useRef(false)
  const [dragging, setDragging] = useState(false)

  // Wheel has to be a non-passive listener or the page scrolls behind the zoom.
  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const rect = svg.getBoundingClientRect()
      const px = e.clientX - rect.left - rect.width / 2
      const py = e.clientY - rect.top - rect.height / 2
      setSteered(true)
      setView(v => {
        const k = Math.min(4, Math.max(0.35, v.k * (e.deltaY < 0 ? 1.12 : 1 / 1.12)))
        // Keep the point under the cursor still, which is what makes a zoom
        // feel like moving closer rather than like the diagram jumping.
        const ratio = k / v.k
        return { k, x: px - (px - v.x) * ratio, y: py - (py - v.y) * ratio }
      })
    }
    svg.addEventListener('wheel', onWheel, { passive: false })
    return () => svg.removeEventListener('wheel', onWheel)
  }, [])

  // No pointer capture on purpose. Capturing on the SVG would retarget every
  // later pointer event to it, and the node's own pointerup - the click - would
  // never fire. Leaving the element ends the drag instead, which is the same
  // behaviour for anything short of a throw off the edge of the canvas.
  const onPointerDown = (e: React.PointerEvent) => {
    drag.current = { x: e.clientX - view.x, y: e.clientY - view.y }
    moved.current = false
    setDragging(true)
  }
  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag.current) return
    const next = { x: e.clientX - drag.current.x, y: e.clientY - drag.current.y }
    // A few pixels of travel is a hand resting on a button, not a pan.
    if (Math.abs(next.x - view.x) > 3 || Math.abs(next.y - view.y) > 3) {
      moved.current = true
      setSteered(true)
    }
    setView(v => ({ ...v, ...next }))
  }
  const endDrag = () => {
    drag.current = null
    setDragging(false)
  }

  const zoom = (factor: number) => {
    setSteered(true)
    setView(v => ({ ...v, k: Math.min(4, Math.max(0.35, v.k * factor)) }))
  }

  const fit = useCallback(() => {
    // Also gives the automatic fit back, so the button is "stop steering" as
    // much as it is "fit now".
    setSteered(false)
    setView({ k: Math.min(1.7, Math.max(0.4, 292 / extent)), x: 0, y: 0 })
  }, [extent])

  const current = byId.get(selected) ?? focus

  return (
    // The canvas takes the full width and the details sit under it. Beside it,
    // a 290px panel came out of the one dimension the wheel needs most, and
    // four rings of labels had nowhere to go.
    <div>
      {/* Where you are, and every step back. A drill-down that re-centres has to
          say what it re-centred on, or going in three levels is a one-way trip
          through a wheel that keeps looking the same. */}
      <div className="flex flex-wrap items-center gap-x-1 gap-y-1 border-b border-rule bg-sunk/40 px-3 py-1.5">
        {trail.map((node, i) => (
          <span key={node.id} className="flex items-center gap-1">
            {i > 0 && <span className="text-[10px] text-ink-dim">/</span>}
            <button
              type="button"
              onClick={() => {
                setFocusId(node.id)
                setSelected(node.id)
              }}
              className={`px-1 py-[1px] font-mono text-[10.5px] tracking-wide ${
                i === trail.length - 1
                  ? 'text-hot-ink'
                  : 'text-ink-dim hover:text-ink hover:underline'
              }`}
            >
              {trim(node.kind === 'role' ? node.full.toUpperCase() : node.label, 24)}
            </button>
          </span>
        ))}
        <span className="ml-auto tag text-ink-dim">
          {focus.children.length}{' '}
          {focus.kind === 'root'
            ? 'roles'
            : focus.kind === 'role'
              ? 'modules'
              : focus.kind === 'module'
                ? 'files'
                : 'symbols'}
        </span>
      </div>

      <div className="relative">
        <svg
          ref={svgRef}
          viewBox="-300 -300 600 600"
          className={`kb-canvas h-[440px] w-full sm:h-[560px] lg:h-[620px] ${
            dragging ? 'dragging' : ''
          }`}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={endDrag}
          onPointerLeave={endDrag}
          role="img"
          aria-label={`Knowledge base: ${modules.modules.length} modules across ${root.children.length} roles.`}
        >
          <g transform={`translate(${view.x} ${view.y}) scale(${view.k})`}>
            {/* The rings, so depth reads even where a branch is closed. */}
            {rings.map(r => (
              <circle
                key={r}
                r={r}
                fill="none"
                stroke="var(--rule)"
                strokeWidth="0.6"
                strokeDasharray="2 5"
                opacity="0.7"
              />
            ))}

            {target.visible.map(node => {
              if (!node.parent) return null
              const from = drawn.get(node.parent)
              const to = drawn.get(node.id)
              if (!from || !to) return null
              const lit = selected === node.id || selected === node.parent
              return (
                <path
                  key={`e-${node.id}`}
                  d={linkPath(from, to)}
                  fill="none"
                  stroke={lit ? 'var(--hot)' : 'var(--rule)'}
                  strokeWidth={lit ? 1.5 : 1}
                  opacity={lit ? 0.9 : 0.55}
                />
              )
            })}

            {target.visible.map(node => {
              const at = drawn.get(node.id)
              if (!at) return null
              const { x, y } = xy(at)
              const isHub = node.id === focusId
              const on = selected === node.id
              const ink = node.kind === 'root' ? 'var(--hot)' : roleInk(node.role ?? '')
              const arc = target.arcs.get(node.id) ?? 0
              const busy = node.path ? loading.has(node.path) : false

              return (
                <g
                  key={node.id}
                  className="kb-node"
                  transform={`translate(${x} ${y})`}
                  onPointerUp={() => {
                    // A drag that happens to end over a node is a pan, not a
                    // click. Deliberately not stopping propagation: this event
                    // still has to reach the canvas to end the drag.
                    if (!moved.current) activate(node)
                  }}
                >
                  <title>{node.full}</title>
                  <Dot node={node} ink={ink} on={on} open={isHub} busy={busy} />
                  {arc >= MIN_ARC_FOR_LABEL && (
                    <Label
                      node={node}
                      angle={at.a}
                      on={on}
                      centre={node.id === focusId}
                    />
                  )}
                </g>
              )
            })}
          </g>
        </svg>

        <div className="absolute right-2 top-2 flex flex-col gap-px border border-rule bg-panel">
          {[
            ['+', () => zoom(1.25), 'Zoom in'],
            ['−', () => zoom(1 / 1.25), 'Zoom out'],
            ['⤢', fit, 'Fit to view'],
          ].map(([label, onClick, tip]) => (
            <button
              key={tip as string}
              type="button"
              title={tip as string}
              onClick={onClick as () => void}
              className="h-6 w-6 border-b border-rule text-[12px] leading-none text-ink-dim last:border-b-0 hover:bg-sunk hover:text-hot-ink"
            >
              {label as string}
            </button>
          ))}
        </div>

        <p className="pointer-events-none absolute bottom-2 left-3 font-sans text-[10.5px] text-ink-dim">
          Click a node to go in · click the centre to come back · drag and scroll to move
        </p>
      </div>

      <Details node={current} projectId={projectId} onSelect={setSelected} byId={byId} />
    </div>
  )
}

/** Whether `id` sits anywhere beneath `ancestor`. */
function inside(byId: Map<string, Node>, id: string, ancestor: string): boolean {
  let node = byId.get(id)
  while (node?.parent) {
    if (node.parent === ancestor) return true
    node = byId.get(node.parent)
  }
  return false
}

function Dot({
  node,
  ink,
  on,
  open,
  busy,
}: {
  node: Node
  ink: string
  on: boolean
  open: boolean
  busy: boolean
}) {
  const size =
    node.kind === 'root' ? 9 : node.kind === 'role' ? 6.5 : node.kind === 'module' ? 5 : 3.5

  return (
    <>
      {/* The target, not the mark. A role dot is six pixels across; asking a
          reader to hit that is asking them to aim. Transparent rather than
          `fill="none"`, because none is not painted and so is not hit. */}
      <circle r={size + 11} fill="transparent" />
      {on && <circle r={size + 5} fill="var(--hot)" opacity="0.14" pointerEvents="none" />}
      <circle
        pointerEvents="none"
        className={busy ? 'kb-loading' : 'kb-enter'}
        r={size}
        // Hollow when there is more inside that has not been opened, filled once
        // it is: the shape says whether clicking again will do anything.
        fill={open || !node.children.length ? ink : 'var(--panel)'}
        stroke={on ? 'var(--hot)' : ink}
        strokeWidth={on ? 2 : 1.4}
      />
    </>
  )
}

function Label({
  node,
  angle,
  on,
  centre,
}: {
  node: Node
  angle: number
  on: boolean
  /** The hub. Its label sits above the dot rather than radiating from it,
   *  because at the centre every direction is somebody's edge. */
  centre: boolean
}) {
  const degrees = (angle * 180) / Math.PI
  // Past the vertical the text would be upside down, so it is flipped and
  // anchored from the other end instead.
  const flipped = degrees > 90 || degrees < -90
  const size = node.kind === 'root' ? 12 : node.kind === 'role' ? 10 : 9
  const gap = node.kind === 'root' ? 0 : 10

  if (centre) {
    const width = trim(node.label, 26).length * 7 + 14
    return (
      <>
        <rect
          className="kb-label"
          x={-width / 2}
          y={-29}
          width={width}
          height={16}
          rx="3"
          fill="var(--panel)"
          opacity="0.92"
        />
        <text
          className="kb-label kb-enter"
          y={-18}
          textAnchor="middle"
          fontSize={12}
          fontWeight="700"
          letterSpacing={node.kind === 'role' ? '0.08em' : '0'}
          fontFamily="var(--font-mono)"
          fill="var(--ink)"
        >
          {trim(node.kind === 'role' ? node.full.toUpperCase() : node.label, 26)}
        </text>
      </>
    )
  }

  return (
    <g
      className="kb-label kb-enter"
      transform={`rotate(${flipped ? degrees + 180 : degrees})`}
    >
      <text
        x={flipped ? -gap : gap}
        y={3}
        textAnchor={flipped ? 'end' : 'start'}
        fontSize={size}
        fontWeight={node.kind === 'role' ? 700 : 400}
        letterSpacing={node.kind === 'role' ? '0.08em' : '0'}
        fontFamily="var(--font-mono)"
        fill={on ? 'var(--hot-ink)' : node.kind === 'role' ? 'var(--ink)' : 'var(--ink-mid)'}
      >
        {node.kind === 'role' ? trim(node.label, 14).toUpperCase() : trim(node.label, 20)}
      </text>
    </g>
  )
}

const trim = (text: string, n: number) => (text.length > n ? `${text.slice(0, n - 1)}…` : text)

/* ── The panel ────────────────────────────────────────────────────── */

/**
 * One thing described at a time.
 *
 * This is where the prose from the old list went. Twenty summaries on screen at
 * once is a wall nobody reads; the same twenty, one per selection, is the thing
 * the summaries were written for.
 */
function Details({
  node,
  projectId,
  onSelect,
  byId,
}: {
  node: Node
  projectId: number
  onSelect: (id: string) => void
  byId: Map<string, Node>
}) {
  const code = (path: string, line?: number) =>
    `/app/projects/${projectId}/code?file=${encodeURIComponent(path)}${
      line ? `#L${line}` : ''
    }`

  return (
    <aside className="min-w-0 border-t border-rule">
      <div className="flex items-baseline gap-2 border-b border-rule bg-sunk/50 px-3 py-1.5">
        <span className="tag text-ink-dim">{node.kind}</span>
        <span className="min-w-0 flex-1 truncate font-mono text-[11.5px] font-semibold text-ink">
          {node.kind === 'role' ? node.full.toUpperCase() : node.label}
        </span>
        {node.parent && (
          <button
            type="button"
            onClick={() => onSelect(node.parent!)}
            className="tag shrink-0 text-ink-dim hover:text-hot-ink"
          >
            up to {trim(byId.get(node.parent)?.label ?? 'parent', 18)}
          </button>
        )}
      </div>

      {/* Two columns on a wide screen: the facts read as a block and the prose
          gets a measure it can be read at, rather than one line of summary
          stretched across nine hundred pixels. */}
      <div className="grid max-h-[300px] grid-cols-1 gap-x-6 overflow-y-auto px-3 py-2.5 md:grid-cols-[260px_1fr]">
        {node.kind === 'root' && (
          <>
            <Facts
              rows={[
                ['roles', node.children.length],
                ['modules', node.children.reduce((n, r) => n + r.children.length, 0)],
              ]}
            />
            <div className="min-w-0">
              <p className="font-sans text-[11.5px] leading-relaxed text-ink-mid">
                Every module analysis found, grouped by what it is for. Open a role to
                see its modules, a module to see its files, and a file to see the
                symbols the parser found in it.
              </p>
            </div>
          </>
        )}

        {node.kind === 'role' && (
          <>
            <Facts
              rows={[
                ['modules', node.children.length],
                [
                  'lines',
                  node.children
                    .reduce((n, m) => n + (m.module?.loc ?? 0), 0)
                    .toLocaleString(),
                ],
              ]}
            />
            <ul className="min-w-0 md:columns-2">
              {node.children.map(m => (
                <li key={m.id}>
                  <button
                    type="button"
                    onClick={() => onSelect(m.id)}
                    className="flex w-full items-baseline gap-2 py-[3px] text-left font-mono text-[11px] text-ink-mid hover:text-hot-ink"
                  >
                    <span className="min-w-0 flex-1 truncate">{m.label}</span>
                    <span className="shrink-0 text-[9.5px] tabular-nums text-ink-dim">
                      {m.module?.loc.toLocaleString()}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}

        {node.kind === 'module' && node.module && (
          <>
            <Facts
              rows={[
                ['role', node.module.role],
                ['language', node.module.language || 'mixed'],
                ['lines', node.module.loc.toLocaleString()],
                ['files', node.module.file_count],
                ['symbols', node.module.symbols],
              ]}
            />
            <div className="min-w-0">
              <p className="font-sans text-[11.5px] leading-relaxed text-ink-mid">
                {node.module.summary ||
                  (node.module.is_test
                    ? 'Test modules are not summarised.'
                    : 'No summary was written for this module.')}
              </p>
              <p className="mt-2 font-mono text-[10px] text-ink-dim">{node.module.path}</p>
            </div>
          </>
        )}

        {node.kind === 'file' && node.path && (
          <>
            <Facts
              rows={[
                ['language', node.file?.language || 'unknown'],
                ['lines', node.file?.loc ? node.file.loc.toLocaleString() : '-'],
                ['symbols', node.file?.symbols ?? '-'],
                ...(node.file && !node.file.has_source
                  ? ([['source', 'not kept']] as [string, string][])
                  : []),
              ]}
            />
            <div className="min-w-0">
              <p className="break-all font-mono text-[10.5px] text-ink-dim">{node.path}</p>
              <Link
                to={code(node.path)}
                className="mt-2 inline-block font-mono text-[11px] text-hot-ink hover:underline"
              >
                open in source
              </Link>
              {node.children.length > 0 && (
                <p className="mt-1.5 font-sans text-[11px] text-ink-dim">
                  {node.children.length} symbol
                  {node.children.length === 1 ? '' : 's'} on the ring outside.
                </p>
              )}
            </div>
          </>
        )}

        {node.kind === 'symbol' && node.symbol && node.path && (
          <>
            <Facts
              rows={[
                ['kind', node.symbol.kind || 'symbol'],
                ['line', node.symbol.line],
                ...(node.symbol.end_line
                  ? ([['ends', node.symbol.end_line]] as [string, number][])
                  : []),
                ...(node.symbol.visibility
                  ? ([['visibility', node.symbol.visibility]] as [string, string][])
                  : []),
              ]}
            />
            <div className="min-w-0">
              <p className="break-all font-mono text-[10.5px] text-ink-dim">
                {node.symbol.qname || node.symbol.name}
              </p>
              <Link
                to={code(node.path, node.symbol.line)}
                className="mt-2 inline-block font-mono text-[11px] text-hot-ink hover:underline"
              >
                open at line {node.symbol.line}
              </Link>
            </div>
          </>
        )}

      </div>
    </aside>
  )
}

function Facts({ rows }: { rows: [string, string | number][] }) {
  return (
    <dl className="grid grid-cols-[74px_1fr] gap-x-2 gap-y-[3px]">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="tag text-ink-dim">{k}</dt>
          <dd className="min-w-0 truncate font-mono text-[11px] text-ink">{v}</dd>
        </div>
      ))}
    </dl>
  )
}
