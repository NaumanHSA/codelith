import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../lib/api'
import type { FileEntry, FileTree, ModuleEntry, Modules, SymbolEntry } from '../../lib/types'
import SourcePeek from './SourcePeek'

/* ------------------------------------------------------------------ *
 * The knowledge base as one growing graph.
 *
 * Two earlier attempts at this were radial and both failed the same
 * way. A wheel apportioned by leaf count puts a parent nowhere near its
 * children the moment one branch dominates - SERVICE holds fourteen of
 * twenty modules here - and re-centring to fix that threw the rest of
 * the graph away, so three levels in you were looking at two cards and
 * an edge with no idea where you were.
 *
 * The answer to both is to stop deciding where things go. Nodes repel,
 * edges pull, and the layout settles into whatever shape the data
 * actually has. Expanding adds nodes to the graph you are already
 * looking at; nothing is replaced, and the path back to the project is
 * always drawn on screen.
 *
 * **A level is legible before it is read.** Shape says what kind of
 * thing a node is - the project is a slab, a role is a pill, a module
 * is a card with a spine, a file is a dog-eared page - and colour says
 * which family of role it belongs to. Between them you can read the
 * structure of a screenful without reading a word of it.
 *
 * **Symbols are a table, not a cloud.** A file's functions and
 * variables cannot be expanded further, and scattering twenty
 * unopenable cards across the canvas buys nothing but distance. They
 * arrive as one block with a row each, which is also the shape they
 * have in the file.
 * ------------------------------------------------------------------ */

type Kind = 'root' | 'role' | 'module' | 'file' | 'symbols'

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
  /** Only on a `symbols` node: the rows it draws. */
  rows?: SymbolEntry[]
}

type Body = { x: number; y: number; vx: number; vy: number; pinned?: boolean }

/* ── Colour ───────────────────────────────────────────────────────── */

/**
 * A hue per family of role, in fixed order and never cycled.
 *
 * Grouped rather than one-per-role because there are thirteen roles and six
 * validated hues, and a seventh generated hue is a colour nobody can name. The
 * families are what a reader actually distinguishes: what a caller touches, what
 * does work, what holds data, what is shared, how it runs, and how it is tested.
 * Anything outside them takes the neutral ink, which is the honest "other".
 */
const FAMILY: Record<string, string> = {
  api: 'var(--cat-1)',
  ui: 'var(--cat-1)',
  service: 'var(--cat-2)',
  worker: 'var(--cat-2)',
  data_access: 'var(--cat-3)',
  model: 'var(--cat-3)',
  schema: 'var(--cat-3)',
  utility: 'var(--cat-4)',
  config: 'var(--cat-5)',
  infra: 'var(--cat-5)',
  cli: 'var(--cat-5)',
  test: 'var(--cat-6)',
}
const familyInk = (role: string) => FAMILY[role.toLowerCase()] ?? 'var(--ink-dim)'

/** What the legend lists, so the six hues are named rather than guessed at. */
const LEGEND: [string, string][] = [
  ['api, ui', 'var(--cat-1)'],
  ['service, worker', 'var(--cat-2)'],
  ['data, model, schema', 'var(--cat-3)'],
  ['utility', 'var(--cat-4)'],
  ['config, infra, cli', 'var(--cat-5)'],
  ['test', 'var(--cat-6)'],
]

/* ── Sizes ────────────────────────────────────────────────────────── */

/** Thousands as `20.9k`. A role card is 166px and a grouped six-digit count does
 *  not fit in it; a clipped number reads as a different number. */
function compact(n: number): string {
  return n >= 10_000 ? `${(n / 1000).toFixed(1)}k` : n.toLocaleString()
}

const SIZE: Record<Exclude<Kind, 'symbols'>, { w: number; h: number }> = {
  root: { w: 208, h: 50 },
  role: { w: 166, h: 38 },
  module: { w: 158, h: 40 },
  file: { w: 150, h: 40 },
}

/** A row in the symbol table, and the header above it. */
const ROW_H = 15
const TABLE_HEAD = 20
const TABLE_W = 198

/** Past this the block is taller than the graph it sits in. The rest are in the
 *  detail panel, which lists every one of them with a link into the source. */
const MAX_ROWS = 14

function sizeOf(node: Node) {
  if (node.kind !== 'symbols') return SIZE[node.kind]
  const rows = Math.min(node.rows?.length ?? 0, MAX_ROWS)
  return { w: TABLE_W, h: TABLE_HEAD + rows * ROW_H + 6 }
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
 * meant clicking a card you could see was clicking where it used to be.
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

/** How many monospace characters fit on a card's second line. The inset differs by
 *  kind (a role pill leaves room for its dot) and the right edge has to clear the
 *  "+" that says a node can be opened. */
function metaChars(kind: Kind, w: number): number {
  const inset = kind === 'role' ? 26 : 14
  return Math.max(8, Math.floor((w - inset - 14) / 5.1))
}

const trim = (text: string, n: number) => (text.length > n ? `${text.slice(0, n - 1)}…` : text)

/** A card's second line has about twenty-three characters. "javascript" spends
 *  eight of them saying what "js" says, and the counts it crowds out are the
 *  part nobody can infer from the name. */
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
      meta: `${entries.length} modules · ${compact(lines)} lines`,
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
        ].join(' · '),
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
        // One table rather than a symbol per card. Nothing under a symbol can be
        // opened, so scattering twenty of them buys distance and no information.
        const rows = symbols.get(path)
        if (rows?.length) {
          fileNode.children.push({
            id: `syms:${path}`,
            kind: 'symbols',
            label: `${rows.length} symbols`,
            meta: path,
            full: path,
            parent: fileNode.id,
            children: [],
            role,
            path,
            rows,
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
  fullscreen = false,
}: {
  title: string
  modules: Modules
  files: FileTree | undefined
  projectId: number
  /** On its own page the canvas takes the viewport instead of a panel's worth. */
  fullscreen?: boolean
}) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(['root']))
  const [selected, setSelected] = useState<string | null>(null)
  const [hovered, setHovered] = useState<string | null>(null)
  const [symbols, setSymbols] = useState<Map<string, SymbolEntry[]>>(new Map())
  const [loading, setLoading] = useState<Set<string>>(new Set())
  const [view, setView] = useState({ k: 1, x: 0, y: 0 })
  const [steered, setSteered] = useState(false)
  const [showLegend, setShowLegend] = useState(true)
  /** The file being read over the top of the graph, if any. */
  const [peek, setPeek] = useState<{ path: string; line?: number; origin?: string } | null>(
    null,
  )
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

  const focus = byId.get(hovered ?? selected ?? '') ?? null

  /**
   * The chain from the project down to whatever is in focus.
   *
   * Everything off it is dimmed rather than hidden. A graph of forty cards can
   * show you where something sits or how much there is, and dimming lets it do
   * both: the path reads at a glance and the rest stays as context.
   */
  const litPath = useMemo(() => {
    if (!focus) return null
    const chain = new Set<string>()
    let node: Node | undefined = focus
    while (node) {
      chain.add(node.id)
      node = node.parent ? byId.get(node.parent) : undefined
    }
    // The focused node's own children too, so opening something shows what came
    // out of it rather than dimming it.
    for (const child of focus.children) chain.add(child.id)
    return chain
  }, [focus, byId])

  /* ── Simulation ─────────────────────────────────────────────── */

  const bodies = useRef(new Map<string, Body>())
  const alpha = useRef(1)
  const frame = useRef(0)
  /** Whether the animation loop is currently scheduled. */
  const running = useRef(false)
  /** The latest tick, so a gesture can restart a loop that has stopped itself. */
  const tick = useRef<() => void>(() => {})
  const [, redraw] = useState(0)

  /**
   * Wake the simulation.
   *
   * Raising alpha is not enough on its own: the loop stops scheduling itself
   * once the layout is cold, so nothing is left to read the new value. That is
   * why dragging a card worked for the first second after an expansion and did
   * nothing at all once things had settled.
   */
  const kick = useCallback((heat = 0.5) => {
    alpha.current = Math.max(alpha.current, heat)
    if (!running.current) {
      running.current = true
      frame.current = requestAnimationFrame(() => tick.current())
    }
  }, [])

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
      // New nodes start on their parent, offset away from the centre, so a fan
      // opens outward instead of unfolding back through the graph it came from.
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
        .map(n => ({ node: n, body: map.get(n.id)!, size: sizeOf(n) }))
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

      for (const { node, body, size } of list) {
        if (!node.parent) continue
        const parent = map.get(node.parent)
        if (!parent) continue
        const rest = restLength(byId.get(node.parent)?.children.length ?? 1, size.w)
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
            const minX = (a.size.w + b.size.w) / 2 + 14
            const minY = (a.size.h + b.size.h) / 2 + 12
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
      // view. A settling simulation grows past any fixed viewBox, and asking
      // somebody to hunt for what they just opened is its own failure.
      if (!steeredRef.current && list.length) {
        let minX = Infinity
        let minY = Infinity
        let maxX = -Infinity
        let maxY = -Infinity
        for (const { body, size } of list) {
          minX = Math.min(minX, body.x - size.w / 2)
          maxX = Math.max(maxX, body.x + size.w / 2)
          minY = Math.min(minY, body.y - size.h / 2)
          maxY = Math.max(maxY, body.y + size.h / 2)
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
        setView(v => ({
          k: v.k + (k - v.k) * 0.14,
          x: v.x + (-cx * k - v.x) * 0.14,
          y: v.y + (-cy * k - v.y) * 0.14,
        }))
      }

      alpha.current *= ALPHA_DECAY
      redraw(t => t + 1)
      if (alpha.current > ALPHA_MIN) {
        frame.current = requestAnimationFrame(step)
      } else {
        running.current = false
      }
    }

    tick.current = step
    running.current = true
    frame.current = requestAnimationFrame(step)
    return () => {
      cancelAnimationFrame(frame.current)
      running.current = false
    }
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
      if (node.kind === 'symbols') return
      if (node.path) void loadSymbols(node.path)
      setExpanded(current => {
        const next = new Set(current)
        if (next.has(node.id)) {
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
  /** Whether the card being dragged was already pinned before the press. */
  const wasPinned = useRef(false)
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
        // Reheat so the neighbours move out of the way of where you are putting
        // it, and wake the loop if it had already gone cold.
        kick()
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
      const body = bodies.current.get(dragged.current)
      // Dropped where you put it; a card that springs back the moment you let go
      // makes the layout feel like it is arguing with you. A click that never
      // moved leaves the card exactly as pinned as it already was.
      if (body && !moved.current) body.pinned = wasPinned.current
      dragged.current = null
      kick(0.35)
    }
    pan.current = null
    setPanning(false)
  }

  const zoom = (factor: number) => {
    setSteered(true)
    setView(v => ({ ...v, k: Math.min(2.6, Math.max(0.22, v.k * factor)) }))
  }
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
    kick(1)
  }

  /**
   * Open a file beside the graph rather than navigating to it.
   *
   * The code page is a different route, so following a reference used to cost
   * every branch you had opened. The origin travels with it because the graph
   * already knew the answer to "where is this from" and the panel should not
   * make you go back and look.
   */
  const openCode = useCallback(
    (path: string, line?: number) => {
      const owner = byId.get(`file:${path}`)
      const module = owner?.parent ? byId.get(owner.parent) : undefined
      setPeek({
        path,
        line,
        origin: module ? `${module.label}${owner?.role ? ` · ${owner.role}` : ''}` : undefined,
      })
    },
    [byId],
  )

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
        <button
          type="button"
          onClick={() => setShowLegend(v => !v)}
          className="tag text-ink-dim hover:text-ink"
        >
          {showLegend ? 'hide key' : 'show key'}
        </button>
        {!fullscreen && (
          <Link
            to={`/app/projects/${projectId}/graph`}
            className="tag text-hot-ink hover:underline"
          >
            full screen ⤢
          </Link>
        )}
        <span className="ml-auto font-sans text-[10.5px] text-ink-dim">
          Click a card to open it · drag a card to place it · drag the canvas to move
        </span>
      </div>

      <div className="relative">
        <svg
          ref={svgRef}
          viewBox="-420 -320 840 640"
          className={`kb-canvas w-full ${
            fullscreen ? 'h-[calc(100vh-190px)]' : 'h-[520px] lg:h-[640px]'
          } ${panning ? 'dragging' : ''}`}
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
              const sa = sizeOf(pa)
              const sb = sizeOf(node)
              const from = border(a.x, a.y, sa.w, sa.h, b.x, b.y)
              const to = border(b.x, b.y, sb.w, sb.h, a.x, a.y)
              const onPath = !litPath || (litPath.has(node.id) && litPath.has(node.parent))
              return (
                <line
                  key={`e-${node.id}`}
                  x1={from.x}
                  y1={from.y}
                  x2={to.x}
                  y2={to.y}
                  stroke={litPath && onPath ? 'var(--hot)' : 'var(--rule)'}
                  strokeWidth={litPath && onPath ? 1.8 : 1}
                  opacity={onPath ? 1 : 0.25}
                />
              )
            })}

            {visible.map(node => {
              const body = bodies.current.get(node.id)
              if (!body) return null
              const size = sizeOf(node)
              const dim = !!litPath && !litPath.has(node.id)
              return (
                <g
                  key={node.id}
                  className="kb-node"
                  transform={`translate(${body.x - size.w / 2} ${body.y - size.h / 2})`}
                  opacity={dim ? 0.28 : 1}
                  onPointerDown={e => {
                    e.stopPropagation()
                    dragged.current = node.id
                    moved.current = false
                    pan.current = null
                    // Held still by the physics for as long as the pointer holds
                    // it, so the card sits under the cursor instead of being
                    // pulled off it by its own springs.
                    const held = bodies.current.get(node.id)
                    if (held) {
                      wasPinned.current = !!held.pinned
                      held.pinned = true
                    }
                  }}
                  onPointerUp={() => {
                    if (!moved.current) toggle(node)
                  }}
                  onPointerEnter={() => setHovered(node.id)}
                  onPointerLeave={() => setHovered(null)}
                >
                  <title>{node.full}</title>
                  {node.kind === 'symbols' ? (
                    <SymbolTable
                      node={node}
                      size={size}
                      on={focus?.id === node.id}
                      onOpen={openCode}
                    />
                  ) : (
                    <Card
                      node={node}
                      size={size}
                      on={focus?.id === node.id}
                      open={expanded.has(node.id)}
                      busy={node.path ? loading.has(node.path) : false}
                      pinned={!!body.pinned}
                      hasMore={
                        node.children.length > 0 ||
                        (node.kind === 'file' && !!node.path && !symbols.has(node.path))
                      }
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

        {showLegend && <Key />}
      </div>

      {/* Under the canvas rather than floating over it. As a card in the corner
          it covered a third of the graph it was describing, and a module summary
          in a 310px column is six lines of two-inch prose. Full width, fixed
          height, so opening a node never moves the drawing. */}
      <Detail node={focus} selected={focus?.id === selected} onOpen={openCode} />

      {peek && (
        <SourcePeek
          projectId={projectId}
          path={peek.path}
          line={peek.line}
          origin={peek.origin}
          onClose={() => setPeek(null)}
        />
      )}
    </div>
  )
}

/* ── Marks ────────────────────────────────────────────────────────── */

/**
 * One card, shaped by what it is.
 *
 * The shape is the point. Colour alone would put the whole burden of "what am I
 * looking at" on six hues that also have to say which family a role belongs to,
 * and a reader scanning forty cards should not have to read one to know whether
 * it is a module or a file.
 */
function Card({
  node,
  size,
  on,
  open,
  busy,
  pinned,
  hasMore,
}: {
  node: Node
  size: { w: number; h: number }
  on: boolean
  open: boolean
  busy: boolean
  pinned: boolean
  hasMore: boolean
}) {
  const { w, h } = size
  const ink = node.kind === 'root' ? 'var(--hot)' : familyInk(node.role ?? '')
  const fill = on ? 'var(--hot-wash)' : 'var(--panel)'
  const stroke = on ? 'var(--hot)' : pinned ? 'var(--ink-dim)' : 'var(--rule)'
  const strokeWidth = on ? 1.8 : 1.1

  return (
    <>
      {node.kind === 'root' && (
        // A slab: squared off, and the only node drawn on the ink rather than
        // beside it. There is exactly one project and it should look like it.
        <>
          <rect
            width={w}
            height={h}
            rx="4"
            fill={on ? 'var(--hot-wash)' : 'var(--ink)'}
            stroke={on ? 'var(--hot)' : 'var(--ink)'}
            strokeWidth="1.5"
          />
          <rect x="0" y="0" width="4" height={h} fill="var(--hot)" />
        </>
      )}

      {node.kind === 'role' && (
        // A pill, filled with its family's hue at a wash. Roles are the one
        // level where colour carries meaning on its own.
        <>
          <rect
            width={w}
            height={h}
            rx={h / 2}
            fill={fill}
            stroke={on ? 'var(--hot)' : ink}
            strokeWidth={on ? 1.8 : 1.4}
          />
          <circle cx={15} cy={h / 2} r="4.5" fill={ink} />
        </>
      )}

      {node.kind === 'module' && (
        // A card with a spine down its left edge, in the family hue.
        <>
          <rect
            width={w}
            height={h}
            rx="3"
            fill={fill}
            stroke={stroke}
            strokeWidth={strokeWidth}
          />
          <rect className={busy ? 'kb-loading' : undefined} width="5" height={h} fill={ink} />
        </>
      )}

      {node.kind === 'file' && (
        // A dog-eared page. The corner is the whole tell, and it costs one path.
        <>
          <path
            d={`M0 3 A3 3 0 0 1 3 0 H${w - 11} L${w} 11 V${h - 3} A3 3 0 0 1 ${w - 3} ${h} H3 A3 3 0 0 1 0 ${h - 3} Z`}
            fill={fill}
            stroke={stroke}
            strokeWidth={strokeWidth}
          />
          <path
            d={`M${w - 11} 0 L${w} 11 H${w - 11} Z`}
            fill="var(--sunk)"
            stroke={stroke}
            strokeWidth={strokeWidth}
          />
          <rect
            className={busy ? 'kb-loading' : undefined}
            x="5"
            y="8"
            width="3"
            height={h - 16}
            rx="1.5"
            fill={ink}
          />
        </>
      )}

      <text
        x={node.kind === 'module' ? 14 : node.kind === 'role' ? 26 : 14}
        y={h / 2 - 2}
        fontSize={node.kind === 'root' ? 12.5 : 10.5}
        fontWeight={node.kind === 'root' || node.kind === 'role' ? 700 : 500}
        letterSpacing={node.kind === 'role' ? '0.06em' : '0'}
        fontFamily="var(--font-mono)"
        fill={node.kind === 'root' && !on ? 'var(--on-ink)' : 'var(--ink)'}
      >
        {trim(node.label, node.kind === 'root' ? 21 : 17)}
      </text>
      <text
        x={node.kind === 'module' ? 14 : node.kind === 'role' ? 26 : 14}
        y={h / 2 + 11}
        fontSize="8.5"
        fontFamily="var(--font-mono)"
        fill={node.kind === 'root' && !on ? 'var(--term-dim)' : 'var(--ink-dim)'}
      >
        {trim(node.meta, metaChars(node.kind, w))}
      </text>
      {hasMore && (
        <text
          x={w - 9}
          y={h / 2 + 4}
          textAnchor="end"
          fontSize="13"
          fontFamily="var(--font-mono)"
          fill={open ? 'var(--hot-ink)' : node.kind === 'root' ? 'var(--term-dim)' : 'var(--ink-dim)'}
        >
          {open ? '−' : '+'}
        </text>
      )}
    </>
  )
}

/**
 * A file's symbols, as a table.
 *
 * Every other node on the canvas is something you can open. These are not, and a
 * cloud of twenty unopenable cards is twenty times the space for none of the
 * information. A row is still a destination: it goes to the line.
 */
function SymbolTable({
  node,
  size,
  on,
  onOpen,
}: {
  node: Node
  size: { w: number; h: number }
  on: boolean
  onOpen: (path: string, line?: number) => void
}) {
  const rows = node.rows ?? []
  const shown = rows.slice(0, MAX_ROWS)
  const ink = familyInk(node.role ?? '')

  return (
    <>
      <rect
        width={size.w}
        height={size.h}
        rx="3"
        fill="var(--panel)"
        stroke={on ? 'var(--hot)' : 'var(--rule)'}
        strokeWidth={on ? 1.8 : 1.1}
      />
      <rect width={size.w} height={TABLE_HEAD} fill="var(--sunk)" />
      <rect width="4" height={size.h} fill={ink} />
      <text
        x="12"
        y={TABLE_HEAD / 2 + 3.5}
        fontSize="9"
        fontWeight="700"
        letterSpacing="0.06em"
        fontFamily="var(--font-mono)"
        fill="var(--ink)"
      >
        {rows.length} SYMBOLS
      </text>

      {shown.map((symbol, i) => {
        const y = TABLE_HEAD + i * ROW_H
        return (
          <g
            key={`${symbol.qname || symbol.name}:${symbol.line}`}
            className="kb-row"
            // Deliberately not stopping propagation: this event still has to
            // reach the canvas to end the drag gesture, and the card's own
            // handler above does nothing for a symbols node anyway.
            onPointerUp={() => {
              if (node.path) onOpen(node.path, symbol.line)
            }}
          >
            <title>{`${symbol.qname || symbol.name} · ${symbol.kind || 'symbol'} · line ${symbol.line}`}</title>
            <rect x="4" y={y} width={size.w - 4} height={ROW_H} fill="transparent" />
            <text
              x="12"
              y={y + 11}
              fontSize="9"
              fontFamily="var(--font-mono)"
              fill="var(--ink-mid)"
            >
              {trim(symbol.name, 16)}
            </text>
            <text
              x={size.w - 38}
              y={y + 11}
              textAnchor="end"
              fontSize="7.5"
              fontFamily="var(--font-mono)"
              fill="var(--ink-dim)"
            >
              {trim(symbol.kind || 'symbol', 9)}
            </text>
            <text
              x={size.w - 8}
              y={y + 11}
              textAnchor="end"
              fontSize="7.5"
              fontFamily="var(--font-mono)"
              fill="var(--ink-dim)"
            >
              L{symbol.line}
            </text>
          </g>
        )
      })}

      {rows.length > MAX_ROWS && (
        <text
          x={size.w / 2}
          y={size.h - 2}
          textAnchor="middle"
          fontSize="7.5"
          fontFamily="var(--font-mono)"
          fill="var(--ink-dim)"
        >
          +{rows.length - MAX_ROWS} more in the panel
        </text>
      )}
    </>
  )
}

/** What a shape and a colour mean, so neither has to be guessed at. */
function Key() {
  return (
    <div className="absolute bottom-2 right-2 border border-rule bg-panel/95 px-2.5 py-2 backdrop-blur">
      <div className="flex flex-col gap-[3px]">
        {(
          [
            ['project', <rect key="s" width="16" height="9" y="2" rx="1.5" fill="var(--ink)" />],
            [
              'role',
              <rect
                key="s"
                width="16"
                height="9"
                y="2"
                rx="4.5"
                fill="var(--panel)"
                stroke="var(--ink-mid)"
              />,
            ],
            [
              'module',
              <g key="s">
                <rect
                  width="16"
                  height="9"
                  y="2"
                  rx="1"
                  fill="var(--panel)"
                  stroke="var(--rule)"
                />
                <rect width="2.5" height="9" y="2" fill="var(--ink-mid)" />
              </g>,
            ],
            [
              'file',
              <path
                key="s"
                d="M0 2 H11 L16 6 V11 H0 Z"
                fill="var(--panel)"
                stroke="var(--rule)"
              />,
            ],
          ] as [string, React.ReactNode][]
        ).map(([label, mark]) => (
          <div key={label} className="flex items-center gap-1.5">
            <svg width="16" height="13" className="shrink-0">
              {mark}
            </svg>
            <span className="tag text-ink-dim">{label}</span>
          </div>
        ))}
      </div>

      <div className="mt-1.5 flex flex-col gap-[2px] border-t border-rule pt-1.5">
        {LEGEND.map(([label, ink]) => (
          <div key={label} className="flex items-center gap-1.5">
            <span
              className="h-[7px] w-[7px] shrink-0 rounded-full"
              style={{ background: ink }}
            />
            <span className="tag text-ink-dim">{label}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

/**
 * What is on the card you are pointing at.
 *
 * A strip rather than a panel: the thing it describes is on the canvas above it,
 * so anything that overlaps the canvas hides the answer to the question it was
 * opened to answer. Fixed height, so the graph does not jump every time the
 * pointer crosses a card.
 *
 * Hovering peeks; clicking pins, and clicking also opens the node, so the strip
 * outlives the hover that summoned it.
 */
function Detail({
  node,
  selected,
  onOpen,
}: {
  node: Node | null
  selected: boolean
  onOpen: (path: string, line?: number) => void
}) {
  if (!node) {
    return (
      <div className="flex h-[92px] items-center border-t border-rule bg-sunk/30 px-3">
        <p className="font-sans text-[11.5px] text-ink-dim">
          Point at a card to see what it is. Click it to open what is inside.
        </p>
      </div>
    )
  }

  const ink = node.kind === 'root' ? 'var(--hot)' : familyInk(node.role ?? '')
  const facts: [string, string | number][] =
    node.kind === 'module' && node.module
      ? [
          ['language', node.module.language || 'mixed'],
          ['lines', node.module.loc.toLocaleString()],
          ['files', node.module.file_count],
          ['symbols', node.module.symbols],
          ['role', node.module.role],
        ]
      : node.kind === 'file'
        ? [
            ['language', node.file?.language || 'unknown'],
            ['lines', node.file?.loc ? node.file.loc.toLocaleString() : '-'],
            ['symbols', node.file?.symbols ?? '-'],
            ...(node.file && !node.file.has_source
              ? ([['source', 'not kept']] as [string, string][])
              : []),
          ]
        : node.kind === 'symbols'
          ? [
              ['symbols', node.rows?.length ?? 0],
              [
                'functions',
                (node.rows ?? []).filter(r => (r.kind ?? '').includes('function')).length,
              ],
              [
                'classes',
                (node.rows ?? []).filter(r => (r.kind ?? '').includes('class')).length,
              ],
            ]
          : node.meta.split(' · ').map(part => {
              const [count, ...rest] = part.split(' ')
              return [rest.join(' '), count] as [string, string]
            })

  const prose =
    node.kind === 'module' && node.module
      ? node.module.summary ||
        (node.module.is_test
          ? 'Test modules are not summarised.'
          : 'No summary was written for this module.')
      : node.kind === 'root'
        ? 'Every module analysis found, grouped by what it is for. Open a role for its modules, a module for its files, a file for its symbols.'
        : node.kind === 'role'
          ? 'What analysis decided these modules are for, read from how they are written rather than from where they sit.'
          : node.kind === 'symbols'
            ? 'Every function, class and variable the parser found in this file. A row goes to its line.'
            : 'One file, as the knowledge base retained it. The viewer shows the lines it kept and names the ones it did not.'

  return (
    <div className="h-[92px] border-t border-rule bg-sunk/30">
      <div className="flex h-full items-start gap-4 px-3 py-2">
        <div className="flex min-w-0 shrink-0 flex-col gap-1.5" style={{ width: 300 }}>
          <div className="flex items-baseline gap-2">
            <span
              className="shrink-0 rounded-sm px-1.5 py-[1px] text-[9px] font-semibold tracking-wide uppercase"
              style={{ background: ink, color: 'var(--on-hot)' }}
            >
              {node.kind}
            </span>
            <span className="min-w-0 flex-1 truncate font-mono text-[12px] font-semibold text-ink">
              {node.label}
            </span>
            {selected && <span className="tag shrink-0 text-hot-ink">selected</span>}
          </div>
          <div className="flex flex-wrap gap-1">
            {facts.slice(0, 5).map(([k, v]) => (
              <Badge key={k} label={k} value={v} ink={ink} />
            ))}
          </div>
        </div>

        <div className="min-w-0 flex-1">
          <p className="line-clamp-3 font-sans text-[11.5px] leading-relaxed text-ink-mid">
            {prose}
          </p>
          {node.full !== node.label && (
            <p className="mt-1 truncate font-mono text-[10px] text-ink-dim">{node.full}</p>
          )}
        </div>

        {node.kind === 'module' && node.module && node.module.files.length > 0 && (
          <div className="hidden max-h-[76px] shrink-0 overflow-y-auto md:block" style={{ width: 210 }}>
            <span className="tag text-ink-dim">open in source</span>
            {node.module.files.slice(0, 6).map(path => (
              <button
                key={path}
                type="button"
                onClick={() => onOpen(path)}
                className="block w-full truncate text-left font-mono text-[10.5px] text-hot-ink hover:underline"
              >
                {path}
              </button>
            ))}
          </div>
        )}

        {(node.kind === 'file' || node.kind === 'symbols') && node.path && (
          <button
            type="button"
            onClick={() => onOpen(node.path!)}
            className="shrink-0 self-center border border-hot-edge bg-hot-wash px-2.5 py-1.5 font-mono text-[11px] text-hot-ink hover:bg-hot hover:text-[var(--on-hot)]"
          >
            open in source →
          </button>
        )}
      </div>
    </div>
  )
}

/** A fact, as a tag. The value leads because that is what is being read. */
function Badge({
  label,
  value,
  ink,
}: {
  label: string
  value: string | number
  ink: string
}) {
  return (
    <span
      className="inline-flex items-baseline gap-1 rounded-sm border px-1.5 py-[1px]"
      style={{
        borderColor: `color-mix(in srgb, ${ink} 35%, transparent)`,
        background: `color-mix(in srgb, ${ink} 7%, transparent)`,
      }}
    >
      <span className="font-mono text-[10.5px] font-semibold text-ink">{value}</span>
      <span className="text-[9px] tracking-wide text-ink-dim uppercase">{label}</span>
    </span>
  )
}
