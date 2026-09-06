import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../lib/api'
import type { FileEntry, FileTree, ModuleEntry, Modules, SymbolEntry } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * The knowledge base as one growing graph.
 *
 * Two earlier attempts at this were radial and both failed the same
 * way. A wheel apportioned by leaf count puts a parent nowhere near its
 * children the moment one branch dominates - SERVICE holds fourteen of
 * twenty modules here - and re-centring to fix that threw the rest of
 * the graph away, so three levels in you were looking at two nodes and
 * an edge with no idea where you were.
 *
 * The answer to both is to stop deciding where things go. Nodes repel,
 * edges pull, and the layout settles into whatever shape the data
 * actually has. Expanding adds nodes to the graph you are already
 * looking at; nothing is replaced, and the path back to the project is
 * always drawn on screen.
 *
 * Edges are straight because these are containment links between cards
 * a few centimetres apart, and a curve on a short straight run is
 * decoration pretending to be information.
 * ------------------------------------------------------------------ */

type Kind = 'root' | 'role' | 'module' | 'file' | 'symbol'

type Node = {
  id: string
  kind: Kind
  label: string
  /** The second line on the card: what this is, in numbers. */
  meta: string
  /** Full text for the detail card, where a truncated label is not enough. */
  full: string
  parent: string | null
  children: Node[]
  role?: string
  module?: ModuleEntry
  file?: FileEntry
  path?: string
  symbol?: SymbolEntry
}

type Body = { x: number; y: number; vx: number; vy: number; pinned?: boolean }

/* ── Sizes ────────────────────────────────────────────────────────── */

const SIZE: Record<Kind, { w: number; h: number }> = {
  root: { w: 196, h: 42 },
  role: { w: 136, h: 38 },
  module: { w: 152, h: 38 },
  file: { w: 146, h: 38 },
  // Two lines like every other card. Name on one row and kind on the other used
  // less height and collided the moment a symbol was called `sessionOpts`.
  symbol: { w: 124, h: 34 },
}

/* ── Forces ───────────────────────────────────────────────────────── */

/**
 * Everything pushes everything else apart, gently.
 *
 * Gently is the correction. At the strength this started with, twenty symbols
 * around one file blew each other out to four hundred units and the automatic
 * framing then shrank the whole graph to a smudge. Overlap is prevented by the
 * separation pass below, which is a hard constraint; repulsion only has to
 * suggest breathing room, so it can afford to be weak.
 */
const REPULSION = 7_000
const REPULSION_RANGE = 320

/** Stiff enough to hold a child at its rest length against that repulsion. */
const SPRING_K = 0.1

/** A drift back to the origin so a subtree pushed outward does not sail off the
 *  canvas. Weak enough that it never fights the repulsion. */
const CENTRE_K = 0.0022

const DAMPING = 0.86

/**
 * The simulation cools rather than running forever. Expanding reheats it.
 *
 * Tuned down from a gentler decay that took seven seconds to settle, which
 * meant clicking a card you could see was clicking where it used to be. The
 * separation pass is a hard constraint and runs at every temperature, so
 * cooling this fast costs the last few pixels of spring relaxation and nothing
 * that matters.
 */
const ALPHA_DECAY = 0.955
const ALPHA_MIN = 0.01

/**
 * How far a parent holds its children.
 *
 * Derived rather than guessed: n cards of a given width need a ring of at least
 * n(w + gap)/2pi to sit side by side without touching. A rest length shorter
 * than that puts the springs and the separation pass in direct opposition - the
 * springs pull the ring in, separation shoves it back out, and the layout
 * oscillates instead of settling.
 */
const restLength = (kids: number, childWidth: number) =>
  Math.max(112, (kids * (childWidth + 16)) / (2 * Math.PI))

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

const trim = (text: string, n: number) => (text.length > n ? `${text.slice(0, n - 1)}…` : text)

/** A card's second line has about twenty-three characters. "javascript" spends
 *  eight of them saying what "js" says, and the line counts and file counts it
 *  crowds out are the part nobody can infer from the name. */
const SHORT_LANGUAGE: Record<string, string> = {
  javascript: 'js',
  typescript: 'ts',
  python: 'py',
  markdown: 'md',
}
const shortLanguage = (name: string) => SHORT_LANGUAGE[name.toLowerCase()] ?? name

/* ── The tree ─────────────────────────────────────────────────────── */

function buildTree(
  title: string,
  modules: Modules,
  files: Map<string, FileEntry>,
  symbols: Map<string, SymbolEntry[]>,
): { root: Node; byId: Map<string, Node> } {
  const byRole = new Map<string, ModuleEntry[]>()
  for (const m of modules.modules) {
    byRole.set(m.role || 'unknown', [...(byRole.get(m.role || 'unknown') ?? []), m])
  }

  const totalFiles = modules.modules.reduce((n, m) => n + m.file_count, 0)
  const root: Node = {
    id: 'root',
    kind: 'root',
    label: title,
    meta: `${modules.modules.length} modules · ${totalFiles} files`,
    full: title,
    parent: null,
    children: [],
  }

  const roles = [...byRole.entries()].sort(
    (a, b) => b[1].reduce((n, m) => n + m.loc, 0) - a[1].reduce((n, m) => n + m.loc, 0),
  )

  for (const [role, entries] of roles) {
    const lines = entries.reduce((n, m) => n + m.loc, 0)
    const roleNode: Node = {
      id: `role:${role}`,
      kind: 'role',
      label: role.replace(/_/g, ' ').toUpperCase(),
      meta: `${entries.length} modules · ${lines.toLocaleString()} lines`,
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
        meta: [
          shortLanguage(m.language || 'mixed'),
          `${m.loc.toLocaleString()} loc`,
          `${m.file_count} files`,
        ].join(
          ' · ',
        ),
        full: m.path,
        parent: roleNode.id,
        children: [],
        role,
        module: m,
      }
      for (const path of m.files) {
        const entry = files.get(path)
        const fileNode: Node = {
          id: `file:${path}`,
          kind: 'file',
          label: path.split('/').pop() ?? path,
          meta: entry
            ? [
                shortLanguage(entry.language || 'text'),
                entry.loc ? `${entry.loc.toLocaleString()} loc` : null,
                entry.symbols ? `${entry.symbols} sym` : null,
              ]
                .filter(Boolean)
                .join(' · ')
            : 'file',
          full: path,
          parent: moduleNode.id,
          children: [],
          role,
          path,
          file: entry,
        }
        for (const s of symbols.get(path) ?? []) {
          fileNode.children.push({
            id: `sym:${path}:${s.qname || s.name}:${s.line}`,
            kind: 'symbol',
            label: s.name,
            meta: `${s.kind || 'symbol'} · L${s.line}`,
            full: s.qname || s.name,
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

/** Where a line from the centre of a card towards a point crosses its border. */
function border(x: number, y: number, w: number, h: number, tx: number, ty: number) {
  const dx = tx - x
  const dy = ty - y
  if (!dx && !dy) return { x, y }
  const sx = dx ? w / 2 / Math.abs(dx) : Infinity
  const sy = dy ? h / 2 / Math.abs(dy) : Infinity
  const s = Math.min(sx, sy, 1)
  return { x: x + dx * s, y: y + dy * s }
}

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
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(['root']))
  const [selected, setSelected] = useState<string | null>(null)
  const [hovered, setHovered] = useState<string | null>(null)
  const [symbols, setSymbols] = useState<Map<string, SymbolEntry[]>>(new Map())
  const [loading, setLoading] = useState<Set<string>>(new Set())
  const [view, setView] = useState({ k: 1, x: 0, y: 0 })
  /** The view follows the graph until the reader takes hold of it. */
  const [steered, setSteered] = useState(false)
  const steeredRef = useRef(false)
  steeredRef.current = steered

  const fileIndex = useMemo(() => new Map((files?.files ?? []).map(f => [f.path, f])), [files])
  const { root, byId } = useMemo(
    () => buildTree(title, modules, fileIndex, symbols),
    [title, modules, fileIndex, symbols],
  )

  /** Every node currently on the canvas, parents before children. */
  const visible = useMemo(() => {
    const out: Node[] = []
    const walk = (n: Node) => {
      out.push(n)
      if (expanded.has(n.id)) n.children.forEach(walk)
    }
    walk(root)
    return out
  }, [root, expanded])

  /* ── Simulation ─────────────────────────────────────────────── */

  const bodies = useRef(new Map<string, Body>())
  const alpha = useRef(1)
  const frame = useRef(0)
  const [, redraw] = useState(0)

  // New nodes start on their parent, offset away from the centre, so a fan opens
  // outward instead of unfolding back through the graph it came from.
  useEffect(() => {
    const map = bodies.current
    const live = new Set(visible.map(n => n.id))
    for (const id of [...map.keys()]) if (!live.has(id)) map.delete(id)

    visible.forEach((node, i) => {
      if (map.has(node.id)) return
      const parent = node.parent ? map.get(node.parent) : undefined
      if (!parent) {
        map.set(node.id, { x: 0, y: 0, vx: 0, vy: 0, pinned: node.kind === 'root' })
        return
      }
      const away = Math.atan2(parent.y, parent.x) || 0
      const spread = ((i % 7) - 3) * 0.42
      const d = 30 + Math.random() * 12
      map.set(node.id, {
        x: parent.x + Math.cos(away + spread) * d,
        y: parent.y + Math.sin(away + spread) * d,
        vx: 0,
        vy: 0,
      })
    })
    alpha.current = 1
  }, [visible])

  useEffect(() => {
    const step = () => {
      const map = bodies.current
      const list = visible
        .map(n => ({ node: n, body: map.get(n.id)! }))
        .filter(entry => entry.body)

      for (const { body } of list) {
        body.vx += -body.x * CENTRE_K
        body.vy += -body.y * CENTRE_K
      }

      for (let i = 0; i < list.length; i++) {
        for (let j = i + 1; j < list.length; j++) {
          const a = list[i].body
          const b = list[j].body
          let dx = b.x - a.x
          let dy = b.y - a.y
          let d2 = dx * dx + dy * dy
          if (d2 > REPULSION_RANGE * REPULSION_RANGE) continue
          // Two nodes on exactly the same point have no direction to separate
          // along, so give them one rather than dividing by zero.
          if (d2 < 1) {
            dx = Math.random() - 0.5
            dy = Math.random() - 0.5
            d2 = 1
          }
          const d = Math.sqrt(d2)
          const f = REPULSION / d2
          const fx = (dx / d) * f
          const fy = (dy / d) * f
          a.vx -= fx
          a.vy -= fy
          b.vx += fx
          b.vy += fy
        }
      }

      for (const { node, body } of list) {
        if (!node.parent) continue
        const parent = map.get(node.parent)
        if (!parent) continue
        const rest = restLength(
          byId.get(node.parent)?.children.length ?? 1,
          SIZE[node.kind].w,
        )
        const dx = body.x - parent.x
        const dy = body.y - parent.y
        const d = Math.hypot(dx, dy) || 1
        const f = (d - rest) * SPRING_K
        const fx = (dx / d) * f
        const fy = (dy / d) * f
        body.vx -= fx
        body.vy -= fy
        parent.vx += fx
        parent.vy += fy
      }

      for (const { body } of list) {
        if (body.pinned) {
          body.vx = 0
          body.vy = 0
          continue
        }
        body.vx *= DAMPING
        body.vy *= DAMPING
        body.x += body.vx * alpha.current
        body.y += body.vy * alpha.current
      }

      // Cards must not sit on top of each other, and no arrangement of springs
      // guarantees that. Resolved directly on the positions, along whichever
      // axis they overlap by less, which is what keeps a row of siblings a row.
      for (let pass = 0; pass < 2; pass++) {
        for (let i = 0; i < list.length; i++) {
          for (let j = i + 1; j < list.length; j++) {
            const a = list[i]
            const b = list[j]
            const sa = SIZE[a.node.kind]
            const sb = SIZE[b.node.kind]
            const minX = (sa.w + sb.w) / 2 + 14
            const minY = (sa.h + sb.h) / 2 + 12
            const dx = b.body.x - a.body.x
            const dy = b.body.y - a.body.y
            const ox = minX - Math.abs(dx)
            const oy = minY - Math.abs(dy)
            if (ox <= 0 || oy <= 0) continue
            if (ox < oy) {
              const push = (ox / 2) * (dx < 0 ? -1 : 1)
              if (!a.body.pinned) a.body.x -= push
              if (!b.body.pinned) b.body.x += push
            } else {
              const push = (oy / 2) * (dy < 0 ? -1 : 1)
              if (!a.body.pinned) a.body.y -= push
              if (!b.body.pinned) b.body.y += push
            }
          }
        }
      }

      // Frame the whole graph, every frame, while the reader has not taken the
      // view. A settling simulation grows past any fixed viewBox - forty-two
      // cards ran off all four edges - and asking somebody to hunt for what they
      // just opened is worse than the wheel this replaced.
      if (!steeredRef.current && list.length) {
        let minX = Infinity
        let minY = Infinity
        let maxX = -Infinity
        let maxY = -Infinity
        for (const { node, body } of list) {
          const { w, h } = SIZE[node.kind]
          minX = Math.min(minX, body.x - w / 2)
          maxX = Math.max(maxX, body.x + w / 2)
          minY = Math.min(minY, body.y - h / 2)
          maxY = Math.max(maxY, body.y + h / 2)
        }
        // Floored, not just capped. Squeezing forty cards into the frame at any
        // cost produces a picture of a graph rather than a graph; below this the
        // view stops shrinking and the reader pans instead.
        const k = Math.min(
          1.15,
          Math.max(0.5, Math.min(820 / (maxX - minX + 40), 620 / (maxY - minY + 40))),
        )
        const cx = (minX + maxX) / 2
        const cy = (minY + maxY) / 2
        // Eased rather than snapped, so the frame drifts with the layout instead
        // of jumping on every tick.
        setView(v => ({
          k: v.k + (k - v.k) * 0.14,
          x: v.x + (-cx * k - v.x) * 0.14,
          y: v.y + (-cy * k - v.y) * 0.14,
        }))
      }

      alpha.current *= ALPHA_DECAY
      redraw(t => t + 1)
      if (alpha.current > ALPHA_MIN) frame.current = requestAnimationFrame(step)
    }

    frame.current = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame.current)
  }, [visible, byId])

  /* ── Data ───────────────────────────────────────────────────── */

  const loadSymbols = useCallback(
    async (path: string) => {
      if (symbols.has(path) || loading.has(path)) return
      setLoading(s => new Set(s).add(path))
      try {
        const file = await api.file(projectId, path)
        setSymbols(m => new Map(m).set(path, file.symbols))
      } catch {
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

  const toggle = useCallback(
    (node: Node) => {
      setSelected(node.id)
      if (node.kind === 'symbol') return
      if (node.path) void loadSymbols(node.path)
      setExpanded(current => {
        const next = new Set(current)
        if (next.has(node.id)) {
          // Closing takes everything under it, so re-opening does not restore a
          // shape the reader has forgotten choosing.
          const drop = (n: Node) => {
            next.delete(n.id)
            n.children.forEach(drop)
          }
          drop(node)
        } else {
          next.add(node.id)
        }
        return next
      })
    },
    [loadSymbols],
  )

  /* ── Zoom, pan, and dragging a card ─────────────────────────── */

  const svgRef = useRef<SVGSVGElement>(null)
  const layerRef = useRef<SVGGElement>(null)
  const pan = useRef<{ x: number; y: number } | null>(null)
  const dragged = useRef<string | null>(null)
  const moved = useRef(false)
  const [panning, setPanning] = useState(false)

  const toGraph = (clientX: number, clientY: number) => {
    const ctm = layerRef.current?.getScreenCTM()
    if (!ctm || !svgRef.current) return { x: 0, y: 0 }
    const point = svgRef.current.createSVGPoint()
    point.x = clientX
    point.y = clientY
    const p = point.matrixTransform(ctm.inverse())
    return { x: p.x, y: p.y }
  }

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
        const k = Math.min(2.6, Math.max(0.22, v.k * (e.deltaY < 0 ? 1.12 : 1 / 1.12)))
        const ratio = k / v.k
        return { k, x: px - (px - v.x) * ratio, y: py - (py - v.y) * ratio }
      })
    }
    svg.addEventListener('wheel', onWheel, { passive: false })
    return () => svg.removeEventListener('wheel', onWheel)
  }, [])

  const onPointerDown = (e: React.PointerEvent) => {
    pan.current = { x: e.clientX - view.x, y: e.clientY - view.y }
    moved.current = false
    setPanning(true)
  }
  const onPointerMove = (e: React.PointerEvent) => {
    if (dragged.current) {
      const body = bodies.current.get(dragged.current)
      if (body) {
        const p = toGraph(e.clientX, e.clientY)
        body.x = p.x
        body.y = p.y
        body.vx = 0
        body.vy = 0
        // Reheat, so the neighbours get out of the way of where you put it.
        alpha.current = Math.max(alpha.current, 0.5)
      }
      moved.current = true
      return
    }
    if (!pan.current) return
    const next = { x: e.clientX - pan.current.x, y: e.clientY - pan.current.y }
    if (Math.abs(next.x - view.x) > 3 || Math.abs(next.y - view.y) > 3) {
      moved.current = true
      setSteered(true)
    }
    setView(v => ({ ...v, ...next }))
  }
  const endGesture = () => {
    if (dragged.current) {
      // Dropped where you put it. A card that springs back the moment you let go
      // makes the layout feel like it is arguing with you.
      const body = bodies.current.get(dragged.current)
      if (body && moved.current) body.pinned = true
      dragged.current = null
    }
    pan.current = null
    setPanning(false)
  }

  const zoom = (factor: number) => {
    setSteered(true)
    setView(v => ({ ...v, k: Math.min(2.6, Math.max(0.22, v.k * factor)) }))
  }

  /** Hands the automatic framing back, so the button is "stop steering" as much
   *  as it is "fit now". The next frame does the actual fitting. */
  const fit = useCallback(() => {
    setSteered(false)
    alpha.current = Math.max(alpha.current, ALPHA_MIN * 2)
  }, [])

  const expandRoles = () => setExpanded(new Set(['root', ...root.children.map(r => r.id)]))
  const collapseAll = () => {
    setExpanded(new Set(['root']))
    setSelected(null)
    for (const body of bodies.current.values()) body.pinned = false
    const rootBody = bodies.current.get('root')
    if (rootBody) rootBody.pinned = true
  }

  const detail = byId.get(hovered ?? selected ?? '') ?? null

  return (
    <div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-rule bg-sunk/40 px-3 py-1.5">
        <span className="tag text-ink-dim">
          {visible.length} of {byId.size} nodes
        </span>
        <button type="button" onClick={expandRoles} className="tag text-hot-ink hover:underline">
          open every role
        </button>
        <button type="button" onClick={collapseAll} className="tag text-ink-dim hover:text-ink">
          collapse
        </button>
        <span className="ml-auto font-sans text-[10.5px] text-ink-dim">
          Click a card to open it · drag a card to place it · drag the canvas to move
        </span>
      </div>

      <div className="relative">
        <svg
          ref={svgRef}
          viewBox="-420 -320 840 640"
          className={`kb-canvas h-[520px] w-full lg:h-[640px] ${panning ? 'dragging' : ''}`}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={endGesture}
          onPointerLeave={endGesture}
          role="img"
          aria-label={`Knowledge base: ${modules.modules.length} modules across ${root.children.length} roles.`}
        >
          <g ref={layerRef} transform={`translate(${view.x} ${view.y}) scale(${view.k})`}>
            {visible.map(node => {
              if (!node.parent) return null
              const a = bodies.current.get(node.parent)
              const b = bodies.current.get(node.id)
              const pa = byId.get(node.parent)
              if (!a || !b || !pa) return null
              const from = border(a.x, a.y, SIZE[pa.kind].w, SIZE[pa.kind].h, b.x, b.y)
              const to = border(b.x, b.y, SIZE[node.kind].w, SIZE[node.kind].h, a.x, a.y)
              const lit = detail?.id === node.id || detail?.id === node.parent
              return (
                <line
                  key={`e-${node.id}`}
                  x1={from.x}
                  y1={from.y}
                  x2={to.x}
                  y2={to.y}
                  stroke={lit ? 'var(--hot)' : 'var(--rule)'}
                  strokeWidth={lit ? 1.6 : 1}
                />
              )
            })}

            {visible.map(node => {
              const body = bodies.current.get(node.id)
              if (!body) return null
              const { w, h } = SIZE[node.kind]
              const open = expanded.has(node.id)
              const on = detail?.id === node.id
              const ink = node.kind === 'root' ? 'var(--hot)' : roleInk(node.role ?? '')
              const busy = node.path ? loading.has(node.path) : false
              const more =
                node.children.length > 0 ||
                (node.kind === 'file' && !!node.path && !symbols.has(node.path))

              return (
                <g
                  key={node.id}
                  className="kb-node"
                  transform={`translate(${body.x - w / 2} ${body.y - h / 2})`}
                  onPointerDown={e => {
                    e.stopPropagation()
                    dragged.current = node.id
                    moved.current = false
                    pan.current = null
                  }}
                  onPointerUp={() => {
                    if (!moved.current) toggle(node)
                  }}
                  onPointerEnter={() => setHovered(node.id)}
                  onPointerLeave={() => setHovered(null)}
                >
                  <title>{node.full}</title>
                  <rect
                    width={w}
                    height={h}
                    rx="8"
                    fill={on ? 'var(--hot-wash)' : 'var(--panel)'}
                    stroke={on ? 'var(--hot)' : body.pinned ? 'var(--ink-dim)' : 'var(--rule)'}
                    strokeWidth={on ? 1.8 : 1.1}
                  />
                  <rect
                    className={busy ? 'kb-loading' : undefined}
                    x="6"
                    y="8"
                    width="3"
                    height={h - 16}
                    rx="1.5"
                    fill={on ? 'var(--hot)' : ink}
                  />
                  <text
                    x="16"
                    y={h / 2 - 2}
                    fontSize={node.kind === 'root' ? 12 : 10.5}
                    fontWeight={node.kind === 'root' || node.kind === 'role' ? 700 : 500}
                    letterSpacing={node.kind === 'role' ? '0.06em' : '0'}
                    fontFamily="var(--font-mono)"
                    fill="var(--ink)"
                  >
                    {trim(node.label, node.kind === 'root' ? 21 : 17)}
                  </text>
                  <text
                    x="16"
                    y={h / 2 + 11}
                    fontSize="8.5"
                    fontFamily="var(--font-mono)"
                    fill="var(--ink-dim)"
                  >
                    {trim(node.meta, 23)}
                  </text>
                  {node.kind !== 'symbol' && more && (
                    // Says whether clicking again will do anything, which the
                    // card alone cannot.
                    <text
                      x={w - 9}
                      y={h / 2 + 4}
                      textAnchor="end"
                      fontSize="13"
                      fontFamily="var(--font-mono)"
                      fill={open ? 'var(--hot-ink)' : 'var(--ink-dim)'}
                    >
                      {open ? '−' : '+'}
                    </text>
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

        {detail && <Card node={detail} projectId={projectId} pinned={detail.id === selected} />}
      </div>
    </div>
  )
}

/**
 * What is on the card you are pointing at.
 *
 * Anchored in the corner rather than following the cursor, because the thing it
 * describes is the thing under the cursor and a panel that chases you covers it.
 * Hovering peeks; clicking pins, and clicking also opens the node, so the panel
 * outlives the hover that summoned it.
 */
function Card({ node, projectId, pinned }: { node: Node; projectId: number; pinned: boolean }) {
  const code = (path: string, line?: number) =>
    `/app/projects/${projectId}/code?file=${encodeURIComponent(path)}${line ? `#L${line}` : ''}`

  return (
    <div className="absolute bottom-2 left-2 max-h-[62%] w-[300px] overflow-y-auto border border-rule bg-panel/95 shadow-[0_2px_14px_rgba(20,18,15,0.10)] backdrop-blur">
      <div className="flex items-baseline gap-2 border-b border-rule bg-sunk/60 px-2.5 py-1.5">
        <span className="tag text-ink-dim">{node.kind}</span>
        <span className="min-w-0 flex-1 truncate font-mono text-[11px] font-semibold text-ink">
          {node.label}
        </span>
        {pinned && <span className="tag text-hot-ink">selected</span>}
      </div>

      <div className="px-2.5 py-2">
        {node.full !== node.label && (
          <p className="mb-1.5 break-all font-mono text-[10px] text-ink-dim">{node.full}</p>
        )}

        {node.kind === 'root' && (
          <p className="font-sans text-[11px] leading-relaxed text-ink-mid">
            {node.meta}. Every module analysis found, grouped by what it is for. Open a
            role for its modules, a module for its files, a file for its symbols.
          </p>
        )}

        {node.kind === 'role' && (
          <p className="font-sans text-[11px] leading-relaxed text-ink-mid">
            {node.meta}. What analysis decided these modules are for, read from how they
            are written rather than from where they sit.
          </p>
        )}

        {node.kind === 'module' && node.module && (
          <>
            <Rows
              rows={[
                ['language', node.module.language || 'mixed'],
                ['lines', node.module.loc.toLocaleString()],
                ['files', node.module.file_count],
                ['symbols', node.module.symbols],
              ]}
            />
            <p className="mt-1.5 font-sans text-[11px] leading-relaxed text-ink-mid">
              {node.module.summary ||
                (node.module.is_test
                  ? 'Test modules are not summarised.'
                  : 'No summary was written for this module.')}
            </p>
          </>
        )}

        {node.kind === 'file' && node.path && (
          <>
            <Rows
              rows={[
                ['language', node.file?.language || 'unknown'],
                ['lines', node.file?.loc ? node.file.loc.toLocaleString() : '-'],
                ['symbols', node.file?.symbols ?? '-'],
                ...(node.file && !node.file.has_source
                  ? ([['source', 'not kept']] as [string, string][])
                  : []),
              ]}
            />
            <Link
              to={code(node.path)}
              className="mt-1.5 inline-block font-mono text-[11px] text-hot-ink hover:underline"
            >
              open in source
            </Link>
          </>
        )}

        {node.kind === 'symbol' && node.symbol && node.path && (
          <>
            <Rows
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
            <Link
              to={code(node.path, node.symbol.line)}
              className="mt-1.5 inline-block font-mono text-[11px] text-hot-ink hover:underline"
            >
              open at line {node.symbol.line}
            </Link>
          </>
        )}
      </div>
    </div>
  )
}

function Rows({ rows }: { rows: [string, string | number][] }) {
  return (
    <dl className="grid grid-cols-[66px_1fr] gap-x-2 gap-y-[2px]">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="tag text-ink-dim">{k}</dt>
          <dd className="min-w-0 truncate font-mono text-[10.5px] text-ink">{v}</dd>
        </div>
      ))}
    </dl>
  )
}
