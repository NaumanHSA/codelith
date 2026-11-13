import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../../lib/api'
import { BRANDS, type BrandName } from '../../lib/brands'
import { useAsync } from '../../lib/hooks'
import { Icon, type IconName } from '../../lib/icons'
import { KINDS, SYMBOL_KINDS, kindOf, lookOf, symbolKindOf } from '../../lib/kinds'
import { useReducedMotion } from '../../lib/motion'
import { shortSha } from '../../lib/format'
import type { Atlas } from '../../lib/types'
import { EmptyState, ErrorState, SkeletonPanel } from '../../components/States'
import { AtlasEngine, type Glyph, type HoverInfo } from '../../components/atlas/engine'
import { adjacency, blast } from '../../components/atlas/graph'
import { TIERS, componentEdges, componentInfo, componentTiers, requestPath, tierColumns } from '../../components/atlas/model'
import { useLayout } from '../../components/atlas/useLayout'
import Inspector from '../../components/atlas/Inspector'
import FlowPanel, { type FlowTab, type Selection } from '../../components/atlas/FlowPanel'
import FlowsView from '../../components/atlas/FlowsView'
import { Freshness } from '../../components/projects/Freshness'
import { ComponentPane, OverviewPane } from '../../components/atlas/Parts'
import TourCard from '../../components/atlas/TourCard'
import { readTourProgress, writeTourProgress } from '../../lib/tour'

/* ------------------------------------------------------------------ *
 * The knowledge graph: a codebase as the parts analysis found in it, and
 * the files inside them as the icons of their kinds.
 *
 * It opens simple: one dashed circle per part, linked by the calls between
 * them, with the same thing flattened into a left-to-right diagram below.
 * Open a part to let its files out; pick a file to see who calls into it,
 * what it calls, and the path a request takes through it. The inspector on
 * the right says in words what the map shows.
 * ------------------------------------------------------------------ */

export default function AtlasPage() {
  const { projectId } = useParams()
  const id = Number(projectId)
  const atlas = useAsync(sig => api.atlas(id, sig), [id])

  if (!Number.isFinite(id)) return <ErrorState message="Not a codebase." />

  if (atlas.loading && !atlas.data)
    return (
      <div className="w-full px-6 py-5">
        <SkeletonPanel rows={10} />
      </div>
    )

  if (atlas.error)
    return (
      <div className="w-full px-6 py-5">
        {/not been analysed/i.test(atlas.error) ? (
          <EmptyState
            title="Nothing read yet"
            body="Analyse this codebase and its map will be here."
            action={
              <Link to={`/app/projects/${id}`} className="text-hot-ink hover:underline">
                Back to the codebase
              </Link>
            }
          />
        ) : (
          <ErrorState message={atlas.error} onRetry={atlas.reload} />
        )}
      </div>
    )

  if (!atlas.data?.nodes.length)
    return (
      <div className="w-full px-6 py-5">
        <EmptyState title="No files in this reading" body="Analysis found no source files it could parse." />
      </div>
    )

  return <AtlasView projectId={id} atlas={atlas.data} />
}

/* ── glyphs: the icons the scene paints onto its sprites ─────────────── */

function tokens() {
  const css = getComputedStyle(document.documentElement)
  const t = (n: string) => css.getPropertyValue(n).trim()
  return {
    panel: t('--panel'),
    sunk: t('--sunk'),
    ink: t('--ink'),
    inkMid: t('--ink-mid'),
    inkDim: t('--ink-dim'),
    hot: t('--hot'),
    line: t('--line-2'),
  }
}

/** A CSS colour the canvas can use: `var(--x)` resolved to its value. */
function resolve(color: string): string {
  const m = /^var\((--[\w-]+)\)$/.exec(color)
  return m ? getComputedStyle(document.documentElement).getPropertyValue(m[1]).trim() : color
}

function brandSvg(name: BrandName, color: string): string {
  const b = BRANDS[name] as { path?: string; icon?: IconName }
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="${color}"><path d="${b.path}"/></svg>`
}

/* ── the view ─────────────────────────────────────────────────────────── */

type Level = 'components' | 'files' | 'functions'

const LEVELS: { level: Level; label: string; icon: IconName; hint: string }[] = [
  { level: 'components', label: 'Parts', icon: 'boxes', hint: 'Close every part: the simplest view' },
  { level: 'files', label: 'Files', icon: 'file-code', hint: 'Open every part to show all its files' },
  { level: 'functions', label: 'Functions', icon: 'square-function', hint: 'Fly in close to the selected file to see its classes and functions' },
]

const KEY_HINTS: { keys: string[]; label: string }[] = [
  { keys: ['KeyW', 'KeyA', 'KeyS', 'KeyD'], label: 'move' },
  { keys: ['KeyQ', 'KeyE'], label: 'down, up' },
]

/** Small codebases open with every part open: one or two circles say nothing. */
const OPEN_BELOW = 40

/** The share of the column the flow takes when both views show, as the reader dragged
 *  it; null until they do, when the flow takes the height it needs. */
const SPLIT_KEY = 'codelith.graph.split'
const SPLIT_MIN = 0.12
const SPLIT_MAX = 0.82

function readSplit(): number | null {
  try {
    const v = Number(localStorage.getItem(SPLIT_KEY))
    return v >= SPLIT_MIN && v <= SPLIT_MAX ? v : null
  } catch {
    return null
  }
}

function writeSplit(v: number | null) {
  try {
    if (v === null) localStorage.removeItem(SPLIT_KEY)
    else localStorage.setItem(SPLIT_KEY, v.toFixed(3))
  } catch {
    /* a convenience only */
  }
}

/**
 * The bar between the map and the flow. Dragging moves the flow's box directly and
 * commits on release, so the page does not re-render under the pointer; the map
 * follows through its own resize observer. Arrow keys move it, double-click resets.
 */
function Splitter({
  column,
  box,
  split,
  onSplit,
}: {
  column: React.RefObject<HTMLDivElement | null>
  box: React.RefObject<HTMLDivElement | null>
  split: number | null
  onSplit: (v: number | null) => void
}) {
  const clamp = (v: number) => Math.min(SPLIT_MAX, Math.max(SPLIT_MIN, v))
  const at = (y: number) => {
    const r = column.current!.getBoundingClientRect()
    return clamp((r.bottom - y) / r.height)
  }
  const shown = split ?? (box.current && column.current ? box.current.offsetHeight / column.current.offsetHeight : 0.35)

  return (
    <div
      role="separator"
      aria-orientation="horizontal"
      aria-label="Drag to share the height between the 3D map and the flow"
      aria-valuemin={Math.round(SPLIT_MIN * 100)}
      aria-valuemax={Math.round(SPLIT_MAX * 100)}
      aria-valuenow={Math.round(shown * 100)}
      title="Drag to resize · double-click to reset"
      tabIndex={0}
      onPointerDown={e => {
        if (!column.current || !box.current) return
        e.preventDefault()
        const el = e.currentTarget
        el.setPointerCapture(e.pointerId)
        el.dataset.dragging = 'true'
        let last = at(e.clientY)
        const move = (ev: PointerEvent) => {
          last = at(ev.clientY)
          box.current!.style.flex = `0 0 ${(last * 100).toFixed(2)}%`
        }
        const up = () => {
          el.removeEventListener('pointermove', move)
          el.removeEventListener('pointerup', up)
          el.removeEventListener('pointercancel', up)
          delete el.dataset.dragging
          onSplit(last)
        }
        el.addEventListener('pointermove', move)
        el.addEventListener('pointerup', up)
        el.addEventListener('pointercancel', up)
      }}
      onDoubleClick={() => onSplit(null)}
      onKeyDown={e => {
        const step = e.shiftKey ? 0.1 : 0.04
        if (e.key === 'ArrowUp') onSplit(clamp(shown + step))
        else if (e.key === 'ArrowDown') onSplit(clamp(shown - step))
        else if (e.key === 'Home') onSplit(SPLIT_MAX)
        else if (e.key === 'End') onSplit(SPLIT_MIN)
        else return
        e.preventDefault()
      }}
      className="atlas-split group relative flex h-3 shrink-0 cursor-row-resize touch-none items-center justify-center outline-none"
    >
      <span className="absolute inset-x-2 top-1/2 h-px -translate-y-1/2 bg-transparent transition-colors group-hover:bg-line-2" />
      <span className="atlas-split-grip relative h-[5px] w-12 rounded-full bg-line-2 transition-colors group-hover:bg-hot group-focus-visible:bg-hot" />
    </div>
  )
}

/** Which of the two views has the height: both, the 3D map alone, or the 2D flow alone. */
type Panes = 'both' | 'map' | 'flow'
const PANES_KEY = 'codelith.graph.panes'

function readPanes(): Panes {
  try {
    const v = localStorage.getItem(PANES_KEY)
    return v === 'map' || v === 'flow' ? v : 'both'
  } catch {
    return 'both'
  }
}

function AtlasView({ projectId, atlas }: { projectId: number; atlas: Atlas }) {
  const [params, setParams] = useSearchParams()
  const reduced = useReducedMotion()
  const layout = useLayout(projectId, atlas)
  const adj = useMemo(() => adjacency(atlas), [atlas])
  const components = useMemo(() => componentInfo(atlas), [atlas])
  const parts = useMemo(() => components.filter(c => c.members.length).map(c => c.index), [components])
  const arch = useAsync(sig => api.architecture(projectId, sig).catch(() => null), [projectId])
  const compEdges = useMemo(() => componentEdges(atlas, arch.data), [atlas, arch.data])
  const tiers = useMemo(() => tierColumns(atlas, componentTiers(atlas)), [atlas])

  const canvasRef = useRef<HTMLCanvasElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const overlayRef = useRef<HTMLDivElement>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  const glyphRef = useRef<HTMLDivElement>(null)
  const engine = useRef<AtlasEngine | null>(null)

  const index = useMemo(() => new Map(atlas.nodes.map((n, i) => [n.id, i])), [atlas])
  const byName = useMemo(() => new Map(atlas.components.map((c, i) => [c.name, i])), [atlas])

  // Where it opens: a file named in the link, a part named in the link, or the parts.
  const initial = useMemo((): Selection => {
    const f = params.get('file')
    const fi = f ? index.get(f) : undefined
    if (fi !== undefined) return { kind: 'file', i: fi }
    const c = params.get('part')
    const ci = c ? byName.get(c) : undefined
    return ci !== undefined ? { kind: 'component', c: ci } : null
    // Read once, on arrival.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const [glError, setGlError] = useState<string | null>(null)
  const [selection, setSelection] = useState<Selection>(initial)
  const [expanded, setExpanded] = useState<Set<number>>(() => {
    if (atlas.nodes.length < OPEN_BELOW || parts.length <= 2) return new Set(parts)
    if (initial?.kind === 'file') return new Set([atlas.nodes[initial.i].component])
    if (initial?.kind === 'component') return new Set([initial.c])
    return new Set()
  })
  const [hidden, setHidden] = useState<Set<string>>(() => new Set())
  const [hover, setHover] = useState<{ info: HoverInfo; x: number; y: number } | null>(null)
  const [focus, setFocus] = useState<number | null>(null)
  const [keysDown, setKeysDown] = useState<string[]>([])
  const [showKeys, setShowKeys] = useState(false)
  const [immersive, setImmersive] = useState(false)
  const [closeUp, setCloseUp] = useState(false)
  const [source, setSource] = useState<{ path: string; line: number | null } | null>(null)
  const [query, setQuery] = useState('')
  const [tab, setTab] = useState<FlowTab>(() => (params.get('flow') ? 'flows' : 'links'))
  const [flowId, setFlowIdState] = useState<string | null>(() => params.get('flow'))
  // The list is fetched the first time the Flows tab is opened, not on every visit.
  const [flowsWanted, setFlowsWanted] = useState(() => Boolean(params.get('flow')))
  const [panes, setPanesState] = useState<Panes>(readPanes)
  // The tour: on from the link (`?tour=1`, the registry's route) or the header button.
  const [touring, setTouring] = useState(() => params.get('tour') === '1')
  const [stopAt, setStopAt] = useState(() => {
    const p = readTourProgress(projectId)
    return p && p.at < p.of ? p.at : 0
  })
  // Whether the tour opened the Flows tab, so leaving its flow stop puts it back.
  const tourFlowRef = useRef(false)
  // Hotspots lit on the map: the files that change most and break widest.
  const [showHot, setShowHot] = useState(() => params.get('hot') === '1')
  const [showQa, setShowQa] = useState(() => params.get('qa') === '1' && params.get('hot') !== '1')
  const [split, setSplitState] = useState<number | null>(readSplit)
  const setSplit = useCallback((v: number | null) => {
    setSplitState(v)
    writeSplit(v)
  }, [])
  const columnRef = useRef<HTMLDivElement>(null)
  const flowBoxRef = useRef<HTMLDivElement>(null)
  const setPanes = useCallback((next: Panes | ((p: Panes) => Panes)) => {
    setPanesState(p => {
      const v = typeof next === 'function' ? next(p) : next
      try {
        localStorage.setItem(PANES_KEY, v)
      } catch {
        /* a convenience only */
      }
      return v
    })
  }, [])

  const immersiveRef = useRef(immersive)
  immersiveRef.current = immersive
  const selectionRef = useRef(selection)
  selectionRef.current = selection
  const expandedRef = useRef(expanded)
  expandedRef.current = expanded

  const selected = selection?.kind === 'file' ? selection.i : null
  const sel = selected !== null ? atlas.nodes[selected] : null
  const selBlast = useMemo(() => (selected !== null ? blast(adj, selected) : null), [adj, selected])
  const selFile = sel && !sel.fact ? sel.path : null
  const reqPath = useMemo(() => (selected !== null ? requestPath(atlas, adj, selected) : null), [atlas, adj, selected])

  const preflight = useAsync(
    sig => (selFile ? api.preflight(projectId, selFile, sig) : Promise.resolve(undefined)),
    [projectId, selFile],
  )
  const calls = useAsync(
    sig => (selFile ? api.fileCalls(projectId, selFile, sig) : Promise.resolve(undefined)),
    [projectId, selFile],
  )

  // Every icon the scene will paint, rendered once off screen by React so the scene
  // can copy real Lucide markup instead of keeping a second icon set.
  const glyphNames = useMemo(() => {
    const names = new Set<IconName>()
    for (const n of atlas.nodes) {
      const look = lookOf(n)
      if (look.icon) names.add(look.icon)
    }
    for (const k of Object.values(KINDS)) names.add(k.icon)
    for (const k of Object.values(SYMBOL_KINDS)) names.add(k.icon)
    return [...names]
  }, [atlas])

  /* ── choosing things; the URL keeps the choice so a view can be linked ── */

  const remember = useCallback(
    (s: Selection) =>
      setParams(
        p => {
          const next = new URLSearchParams(p)
          next.delete('file')
          next.delete('part')
          next.delete('line')
          if (s?.kind === 'file') next.set('file', atlas.nodes[s.i].id)
          if (s?.kind === 'component') next.set('part', atlas.components[s.c].name)
          return next
        },
        { replace: true },
      ),
    [atlas, setParams],
  )

  const applyExpanded = useCallback((next: Set<number>) => {
    setExpanded(next)
    engine.current?.setExpanded(next)
  }, [])

  const pickFile = useCallback(
    (i: number, fly = true) => {
      const c = atlas.nodes[i].component
      if (!expandedRef.current.has(c)) applyExpanded(new Set(expandedRef.current).add(c))
      setSelection({ kind: 'file', i })
      setSource(null)
      engine.current?.select(i, blast(adj, i), fly)
      remember({ kind: 'file', i })
    },
    [adj, atlas, applyExpanded, remember],
  )

  const pickComponent = useCallback(
    (c: number, fly = true) => {
      if (!expandedRef.current.has(c)) applyExpanded(new Set(expandedRef.current).add(c))
      setSelection({ kind: 'component', c })
      setSource(null)
      setTab(t => (t === 'flows' ? t : 'links'))
      engine.current?.selectComponent(c, fly)
      remember({ kind: 'component', c })
    },
    [applyExpanded, remember],
  )

  const clearSelection = useCallback(() => {
    setSelection(null)
    setSource(null)
    setTab(t => (t === 'flows' ? t : 'links'))
    engine.current?.clearSelection()
    remember(null)
  }, [remember])

  const toggle = useCallback(
    (c: number) => {
      const next = new Set(expandedRef.current)
      if (next.has(c)) {
        next.delete(c)
        // A selected file inside a part being closed would vanish with it.
        const s = selectionRef.current
        if (s?.kind === 'file' && atlas.nodes[s.i].component === c) {
          setSelection({ kind: 'component', c })
          engine.current?.selectComponent(c, false)
          remember({ kind: 'component', c })
        }
      } else next.add(c)
      applyExpanded(next)
    },
    [applyExpanded, atlas, remember],
  )

  const focusPart = useCallback((c: number | null) => {
    setFocus(c)
    engine.current?.setFocusComponent(c)
  }, [])

  /* ── the engine: built once the layout and the glyphs exist ── */
  const pickFileRef = useRef(pickFile)
  pickFileRef.current = pickFile
  const pickComponentRef = useRef(pickComponent)
  pickComponentRef.current = pickComponent

  useEffect(() => {
    if (!layout || !canvasRef.current || !stageRef.current || !glyphRef.current || !overlayRef.current) return
    const tk = tokens()
    const svgOf = new Map<string, string>()
    glyphRef.current.querySelectorAll<HTMLElement>('[data-glyph]').forEach(el => {
      svgOf.set(el.dataset.glyph!, el.innerHTML)
    })
    const iconGlyph = (name: IconName, color: string): Glyph => ({
      key: `i:${name}:${color}`,
      color,
      svg: (svgOf.get(name) ?? '').replace(/currentColor/g, color),
    })
    const glyphCache = new Map<number, Glyph>()
    const glyphOf = (i: number): Glyph => {
      const hit = glyphCache.get(i)
      if (hit) return hit
      const n = atlas.nodes[i]
      const look = lookOf(n)
      let g: Glyph
      if (look.brand) {
        const color = resolve(BRANDS[look.brand].color)
        g = { key: `b:${look.brand}`, color, svg: brandSvg(look.brand, color) }
      } else g = iconGlyph(look.icon, kindOf(n.kind).color)
      glyphCache.set(i, g)
      return g
    }
    const kindGlyph = (kind: string) => {
      const k = kindOf(kind)
      return iconGlyph(k.icon, k.color)
    }
    const symbolGlyph = (kind: string | null) => {
      const k = symbolKindOf(kind)
      return iconGlyph(k.icon, k.color)
    }

    let made: AtlasEngine
    try {
      made = new AtlasEngine({
        canvas: canvasRef.current,
        stage: stageRef.current,
        overlay: overlayRef.current,
        atlas,
        layout,
        components,
        columns: tiers.map(t => t.parts),
        glyphOf,
        kindGlyph,
        symbolGlyph,
        tokens: tk,
        reducedMotion: reduced,
        isImmersive: () => immersiveRef.current,
        onSelect: i => pickFileRef.current(i),
        onSelectComponent: c => pickComponentRef.current(c),
        onHover: (info, x, y) => setHover(info ? { info, x, y } : null),
        onHoverComponent: c => setFocus(c),
        onKeys: setKeysDown,
        onCloseUp: setCloseUp,
        onSymbol: line => {
          const s = selectionRef.current
          if (s?.kind === 'file') setSource({ path: atlas.nodes[s.i].path, line })
        },
      })
    } catch {
      setGlError('This browser could not start 3D graphics, so the map cannot be drawn here.')
      return
    }
    engine.current = made
    made.setExpanded(expandedRef.current)

    const s = selectionRef.current
    if (s?.kind === 'file') {
      made.select(s.i, blast(adj, s.i), true)
      // A citation's "open in the graph" names the line too: open the source there.
      const line = Number(params.get('line'))
      if (line && !atlas.nodes[s.i].fact) setSource({ path: atlas.nodes[s.i].path, line })
    } else if (s?.kind === 'component') made.selectComponent(s.c, true)

    return () => {
      made.dispose()
      engine.current = null
    }
    // The engine is rebuilt only for a new map; selection and filters are applied to it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layout, atlas, reduced])

  useEffect(() => {
    engine.current?.setHidden(hidden)
  }, [hidden])

  useEffect(() => {
    if (selected === null) return
    engine.current?.setInside(calls.data && calls.data.path === selFile ? calls.data : null, selected)
  }, [calls.data, selFile, selected])

  /* ── flows: every way in, and the path the chosen one takes ── */
  useEffect(() => {
    if (tab === 'flows') setFlowsWanted(true)
  }, [tab])
  const flowList = useAsync(
    sig => (flowsWanted ? api.flows(projectId, sig) : Promise.resolve(undefined)),
    [projectId, flowsWanted],
  )
  const flowDetail = useAsync(
    sig => (flowId ? api.flow(projectId, flowId, sig) : Promise.resolve(undefined)),
    [projectId, flowId],
  )
  const setFlowId = useCallback(
    (id: string | null) => {
      setFlowIdState(id)
      setParams(
        p => {
          const next = new URLSearchParams(p)
          if (id) next.set('flow', id)
          else next.delete('flow')
          return next
        },
        { replace: true },
      )
    },
    [setParams],
  )
  /** The files a flow passes through, in order, each once in a row. */
  const flowFiles = useMemo(() => {
    const f = flowDetail.data
    if (!f || f.id !== flowId) return null
    const out: number[] = []
    for (const si of f.chain_steps) {
      const at = atlas.nodes.findIndex(n => n.path === f.all_steps[si].path && !n.fact)
      if (at >= 0 && out[out.length - 1] !== at) out.push(at)
    }
    return out
  }, [flowDetail.data, flowId, atlas])
  const pickStep = useCallback(
    (path: string, line: number | null) => {
      const at = atlas.nodes.findIndex(n => n.path === path && !n.fact)
      if (at < 0) return
      pickFile(at)
      setSource({ path, line })
    },
    [atlas, pickFile],
  )

  // The request path or the chosen flow, lit in the map while its tab is open.
  useEffect(() => {
    const e = engine.current
    if (!e) return
    if (panes === 'map') e.setPath(null)
    else if (tab === 'flows') e.setPath(flowFiles && flowFiles.length > 1 ? flowFiles : null)
    else if (tab === 'path' && selected !== null && reqPath) e.setPath([...reqPath.upstream, selected, ...reqPath.downstream])
    else e.setPath(null)
  }, [tab, selected, reqPath, panes, layout, flowFiles])

  // A folded map draws nothing.
  useEffect(() => {
    engine.current?.setPaused(panes === 'flow')
  }, [panes, layout])

  /* ── hotspots: lit on the map while the switch is on and no tour is running ── */
  const hot = useAsync(
    sig => (showHot ? api.hotspots(projectId, 15, sig) : Promise.resolve(undefined)),
    [projectId, showHot],
  )
  const hotFiles = useMemo(() => {
    if (!hot.data?.available) return null
    return hot.data.hotspots.map(h => atlas.nodes.findIndex(n => n.path === h.path && !n.fact)).filter(i => i >= 0)
  }, [hot.data, atlas])
  /* ── findings: the files with open QA findings, lit the same way ── */
  const qa = useAsync(sig => (showQa ? api.findingsMap(projectId, sig) : Promise.resolve(undefined)), [projectId, showQa])
  const qaFiles = useMemo(() => {
    if (!qa.data) return null
    return qa.data.files.map(f => atlas.nodes.findIndex(n => n.path === f.path && !n.fact)).filter(i => i >= 0)
  }, [qa.data, atlas])
  const lit = showHot ? hotFiles : showQa ? qaFiles : null
  useEffect(() => {
    const e = engine.current
    if (!e || touring) return
    if (lit?.length) {
      applyExpanded(new Set([...expandedRef.current, ...lit.map(i => atlas.nodes[i].component)]))
      e.setHighlight(lit)
    } else e.setHighlight(null)
    // The parts are opened once when the files arrive, not on every change of what is open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lit, touring, layout])
  // One switch at a time: both light files, and two sets lit alike would read as one.
  const toggleLight = useCallback(
    (which: 'hot' | 'qa') => {
      const on = which === 'hot' ? !showHot : !showQa
      setShowHot(which === 'hot' && on)
      setShowQa(which === 'qa' && on)
      setParams(
        p => {
          const next = new URLSearchParams(p)
          next.delete('hot')
          next.delete('qa')
          if (on) next.set(which, '1')
          return next
        },
        { replace: true },
      )
    },
    [showHot, showQa, setParams],
  )
  const toggleHot = useCallback(() => toggleLight('hot'), [toggleLight])

  /* ── the tour: each stop opens its parts, lights its files, plays its flow ── */
  const tour = useAsync(
    sig => (touring ? api.tour(projectId, sig) : Promise.resolve(undefined)),
    [projectId, touring],
  )
  const stops = tour.data?.stops ?? []
  const at = Math.max(0, Math.min(stopAt, stops.length - 1))
  const stop = touring && stops.length ? stops[at] : null

  useEffect(() => {
    const e = engine.current
    if (!stop || !e) return
    const partIdx = stop.parts
      .map(n => byName.get(n))
      .filter((c): c is number => c !== undefined && components[c].members.length > 0)
    const fileIdx = stop.files.map(f => atlas.nodes.findIndex(n => n.path === f.path && !n.fact)).filter(i => i >= 0)
    setSelection(null)
    setSource(null)
    e.clearSelection()
    remember(null)
    if (!partIdx.length && !fileIdx.length) {
      // The whole codebase, its parts closed: what it is, how it is laid out, what next.
      applyExpanded(new Set())
      e.setHighlight(null)
      e.reset()
    } else {
      applyExpanded(new Set([...partIdx, ...fileIdx.map(i => atlas.nodes[i].component)]))
      e.setHighlight(fileIdx.length ? fileIdx : null)
      if (partIdx.length === 1) e.flyToComponent(partIdx[0])
      else e.reset()
    }
    if (stop.flow) {
      tourFlowRef.current = true
      setTab('flows')
      setFlowId(stop.flow)
      setPanes(p => (p === 'map' ? 'both' : p))
    } else if (tourFlowRef.current) {
      tourFlowRef.current = false
      setTab('links')
    }
    // A stop is applied when it changes, and once the engine exists.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stop?.id, layout])

  const goStop = useCallback(
    (k: number) => {
      if (!stops.length) return
      const next = Math.max(0, Math.min(k, stops.length - 1))
      setStopAt(next)
      writeTourProgress(projectId, next, stops.length)
    },
    [projectId, stops.length],
  )
  const setTourParam = useCallback(
    (on: boolean) =>
      setParams(
        p => {
          const next = new URLSearchParams(p)
          if (on) next.set('tour', '1')
          else next.delete('tour')
          return next
        },
        { replace: true },
      ),
    [setParams],
  )
  const startTour = useCallback(() => {
    const p = readTourProgress(projectId)
    setStopAt(p && p.at < p.of ? p.at : 0)
    setTouring(true)
    setTourParam(true)
  }, [projectId, setTourParam])
  const closeTour = useCallback(
    (finished = false) => {
      if (finished && stops.length) writeTourProgress(projectId, stops.length, stops.length)
      setTouring(false)
      engine.current?.setHighlight(null)
      if (tourFlowRef.current) {
        tourFlowRef.current = false
        setTab('links')
      }
      setTourParam(false)
    },
    [projectId, setTourParam, stops.length],
  )

  /* full screen: the API on a real click, and a fixed layer either way */
  const toggleImmersive = useCallback(async () => {
    const on = !immersiveRef.current
    setImmersive(on)
    try {
      if (on && wrapRef.current?.requestFullscreen && !document.fullscreenElement)
        await wrapRef.current.requestFullscreen()
      else if (!on && document.fullscreenElement) await document.exitFullscreen()
    } catch {
      /* refused: the fixed layer still fills the window */
    }
    if (on) engine.current?.focusCanvas()
  }, [])

  useEffect(() => {
    const onChange = () => {
      if (!document.fullscreenElement && immersiveRef.current) setImmersive(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      if (immersiveRef.current) {
        if (!document.fullscreenElement) setImmersive(false)
        return
      }
      const t = e.target as HTMLElement | null
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
      // Escape steps back out: a file to its part, a part to the whole.
      const s = selectionRef.current
      if (s?.kind === 'file') pickComponentRef.current(atlas.nodes[s.i].component, false)
      else if (s) clearSelection()
    }
    document.addEventListener('fullscreenchange', onChange)
    window.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('fullscreenchange', onChange)
      window.removeEventListener('keydown', onKey)
    }
  }, [atlas, clearSelection])

  const files = atlas.nodes.filter(n => !n.fact).length
  const facts = atlas.nodes.length - files
  const kindsPresent = (Object.keys(KINDS) as (keyof typeof KINDS)[]).filter(k => atlas.kinds[k])
  const allOpen = parts.every(c => expanded.has(c))
  const level: Level | null = closeUp ? 'functions' : expanded.size === 0 ? 'components' : allOpen ? 'files' : null

  const find = (value: string) => {
    setQuery(value)
    const i = index.get(value) ?? atlas.nodes.findIndex(n => n.path === value)
    if (i !== undefined && i >= 0) {
      pickFile(i)
      setQuery('')
    }
  }

  const goLevel = (l: Level) => {
    const e = engine.current
    if (!e) return
    if (l === 'components') {
      applyExpanded(new Set())
      clearSelection()
      e.reset()
    } else if (l === 'files') {
      applyExpanded(new Set(parts))
      if (selected !== null) e.flyTo(selected, 130)
      else e.reset()
    } else e.dive()
  }

  const crumb =
    selection?.kind === 'file'
      ? atlas.components[atlas.nodes[selection.i].component]?.name
      : selection?.kind === 'component'
        ? atlas.components[selection.c]?.name
        : null

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 px-6 py-4">
      <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <h1 className="text-[22px] leading-tight font-semibold text-ink">Knowledge graph</h1>
            {/* What the map shows is the code at one commit: say how far that is from now. */}
            <Freshness projectId={projectId} sha={atlas.commit} />
          </div>
          <p className="mt-1 text-[13px] text-ink-mid">
            {parts.length} parts, {files.toLocaleString()} files
            {facts ? `, ${facts} things it talks to` : ''}
            {atlas.commit ? ` · commit ${shortSha(atlas.commit)}` : ''}. Open a part to see its files; pick a file
            to follow its calls.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
        {!touring && (
          <button
            type="button"
            onClick={toggleHot}
            aria-pressed={showHot}
            title={
              hot.data && !hot.data.available
                ? hot.data.reason
                : 'Light the files that change most often, that much depends on, and that no test reaches'
            }
            className={`inline-flex h-[38px] items-center gap-2 rounded-lg border px-3.5 text-[12.5px] font-medium transition-colors ${
              showHot ? 'border-hot-edge bg-hot/10 text-ink' : 'border-rule bg-panel text-ink-mid hover:border-line-2 hover:bg-hover hover:text-ink'
            }`}
          >
            <Icon name={hot.loading && showHot ? 'loader' : 'flame'} size={15} className={hot.loading && showHot ? 'anim-spin' : 'text-hot'} />
            Hotspots
            {showHot && hot.data && (
              <span className="font-mono text-[11.5px] text-ink-dim">
                {hot.data.available ? hot.data.hotspots.length : 'no history'}
              </span>
            )}
          </button>
        )}
        {!touring && (
          <button
            type="button"
            onClick={() => toggleLight('qa')}
            aria-pressed={showQa}
            title={
              qa.data && !qa.data.checked.length
                ? 'QA has not been run on this codebase yet'
                : 'Light the files with open QA findings'
            }
            className={`inline-flex h-[38px] items-center gap-2 rounded-lg border px-3.5 text-[12.5px] font-medium transition-colors ${
              showQa ? 'border-hot-edge bg-hot/10 text-ink' : 'border-rule bg-panel text-ink-mid hover:border-line-2 hover:bg-hover hover:text-ink'
            }`}
          >
            <Icon name={qa.loading && showQa ? 'loader' : 'bug'} size={15} className={qa.loading && showQa ? 'anim-spin' : 'text-hot'} />
            Findings
            {showQa && qa.data && (
              <span className="font-mono text-[11.5px] text-ink-dim">{qa.data.checked.length ? qa.data.files.length : 'no QA run'}</span>
            )}
          </button>
        )}
        {!touring && (
          <button
            type="button"
            onClick={startTour}
            title="A guided walk through this codebase, stop by stop"
            className="inline-flex h-[38px] items-center gap-2 rounded-lg border border-rule bg-panel px-3.5 text-[12.5px] font-medium text-ink transition-colors hover:border-line-2 hover:bg-hover"
          >
            <Icon name="compass" size={15} className="text-hot" />
            Take the tour
          </button>
        )}
        <div className="flex rounded-lg border border-rule bg-panel p-[3px]" role="group" aria-label="Detail">
          {LEVELS.map(l => (
            <button
              key={l.level}
              type="button"
              aria-pressed={level === l.level}
              onClick={() => goLevel(l.level)}
              disabled={l.level === 'functions' && !(calls.data?.symbols.length)}
              title={l.hint}
              className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[12.5px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
                level === l.level ? 'bg-sunk text-ink shadow-[inset_0_0_0_1px_var(--line-2)]' : 'text-ink-mid hover:text-ink'
              }`}
            >
              <Icon name={l.icon} size={14} />
              {l.label}
            </button>
          ))}
        </div>
        </div>
      </header>

      <div ref={wrapRef} className={`atlas-wrap flex min-h-0 flex-1 flex-col gap-3 ${immersive ? 'immersive' : ''}`}>
        <div className="flex flex-wrap items-center gap-1.5" aria-label="Show or hide kinds of file">
          {kindsPresent.map(k => {
            const kind = KINDS[k]
            const on = !hidden.has(k)
            return (
              <button
                key={k}
                type="button"
                aria-pressed={on}
                onClick={() =>
                  setHidden(h => {
                    const next = new Set(h)
                    if (next.has(k)) next.delete(k)
                    else next.add(k)
                    return next
                  })
                }
                title={on ? `Hide ${kind.plural.toLowerCase()}` : `Show ${kind.plural.toLowerCase()}`}
                className={`inline-flex h-[30px] items-center gap-2 rounded-md border border-rule bg-panel pr-2.5 pl-2 text-[12.5px] font-medium text-ink transition-opacity ${
                  on ? '' : 'opacity-35'
                }`}
              >
                <Icon name={kind.icon} size={15} style={{ color: kind.color }} />
                {kind.plural}
                <span className="font-mono text-[11.5px] text-ink-dim">{atlas.kinds[k]}</span>
              </button>
            )
          })}
          {hidden.size > 0 && (
            <button
              type="button"
              onClick={() => setHidden(new Set())}
              className="ml-1 rounded-md px-2 py-1 text-[12.5px] text-ink-dim transition-colors hover:bg-hover hover:text-ink"
            >
              Show all
            </button>
          )}
        </div>

        <div className={`atlas-grid grid min-h-0 flex-1 gap-4 ${source ? 'atlas-grid-wide' : ''}`}>
          <div ref={columnRef} className="flex min-h-0 flex-col">
            {panes === 'flow' && (
              <button
                type="button"
                onClick={() => setPanes('both')}
                className="mb-3 flex shrink-0 items-center gap-2.5 rounded-[10px] border border-rule bg-panel px-4 py-2.5 text-left transition-colors hover:border-line-2 hover:bg-hover"
              >
                <Icon name="boxes" size={16} className="text-hot" />
                <span className="text-[13.5px] font-semibold text-ink">3D map</span>
                <span className="text-[12.5px] text-ink-dim">folded away</span>
                <span className="ml-auto flex items-center gap-1.5 text-[12.5px] text-ink-mid">
                  Show the map <Icon name="chevron-down" size={14} />
                </span>
              </button>
            )}
            <div
              ref={stageRef}
              className={`atlas-stage relative isolate min-h-[180px] flex-1 overflow-hidden rounded-[10px] border border-rule ${
                panes === 'flow' ? 'hidden' : ''
              }`}
            >
              <canvas
                ref={canvasRef}
                tabIndex={0}
                className="atlas-canvas absolute inset-0 h-full w-full"
                aria-label="3D map of the codebase. Each dashed circle is a part; open one to see its files. W A S D to move, Q and E for down and up, hold the right mouse button to look around, F to focus the selection, Escape to step back out."
              />

              {/* Each part's name and its open/close button, and each column's heading,
                  moved by the scene. */}
              <div ref={overlayRef} className="pointer-events-none absolute inset-0 overflow-hidden">
                {tiers.map((t, k) => (
                  <div
                    key={`col${k}`}
                    data-col={k}
                    className="absolute top-0 left-0 text-center whitespace-nowrap"
                    style={{ opacity: 0, visibility: 'hidden' }}
                  >
                    <div className="text-[12px] font-semibold tracking-wide text-ink-mid">{TIERS[t.tier].name}</div>
                  </div>
                ))}
                {parts.map(c => {
                  const info = components[c]
                  const open = expanded.has(c)
                  return (
                    <div
                      key={c}
                      data-comp={c}
                      className="atlas-tag pointer-events-auto absolute top-0 left-0"
                      style={{ opacity: 0, visibility: 'hidden' }}
                      onMouseEnter={() => focusPart(c)}
                      onMouseLeave={() => focusPart(null)}
                    >
                      <button
                        type="button"
                        onClick={() => pickComponent(c)}
                        title={info.description || info.name}
                        className="atlas-tag-name flex items-center gap-1.5 rounded-full py-0.5 pr-1.5 pl-2.5 text-[12.5px] font-semibold text-ink-mid transition-colors hover:text-ink"
                      >
                        <span className="max-w-[170px] truncate">{info.name}</span>
                        <span className="font-mono text-[11px] font-normal text-ink-dim">{info.members.length}</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => toggle(c)}
                        aria-label={open ? `Close ${info.name}` : `Open ${info.name}`}
                        title={open ? 'Close: fold its files away' : 'Open: show its files'}
                        className="grid size-6 place-items-center rounded-full text-ink-dim transition-colors hover:bg-hover hover:text-hot-ink"
                      >
                        <Icon name={open ? 'minus' : 'plus'} size={14} />
                      </button>
                    </div>
                  )
                })}
              </div>

              {!layout && !glError && (
                <div className="absolute inset-0 grid place-items-center text-[13px] text-ink-dim">
                  <span className="flex items-center gap-2">
                    <Icon name="loader" size={16} className="anim-spin" /> Laying out {atlas.nodes.length} nodes…
                  </span>
                </div>
              )}
              {glError && (
                <div className="absolute inset-0 grid place-items-center p-6 text-center text-[13px] text-ink-mid">
                  {glError}
                </div>
              )}

              <div className="pointer-events-none absolute inset-x-3 top-3 z-[2100] flex items-start gap-2">
                {crumb ? (
                  <button
                    type="button"
                    onClick={() =>
                      selection?.kind === 'file'
                        ? pickComponent(atlas.nodes[selection.i].component)
                        : clearSelection()
                    }
                    className="atlas-float pointer-events-auto flex h-[34px] items-center gap-1.5 rounded-lg pr-3 pl-2 text-[12.5px] text-ink-mid transition-colors hover:text-ink"
                    title="Step back out (Esc)"
                  >
                    <Icon name="arrow-left" size={14} />
                    {selection?.kind === 'file' ? crumb : 'All parts'}
                  </button>
                ) : null}
                <label className="atlas-float pointer-events-auto flex h-[34px] w-[min(300px,50%)] items-center gap-2 rounded-lg px-2.5">
                  <Icon name="file-search" size={15} className="text-ink-dim" />
                  <input
                    value={query}
                    onChange={e => find(e.target.value)}
                    list="atlas-files"
                    placeholder="Find a file"
                    aria-label="Find a file"
                    className="min-w-0 flex-1 bg-transparent text-[13px] text-ink outline-none placeholder:text-ink-dim"
                  />
                </label>
                <datalist id="atlas-files">
                  {atlas.nodes.map(n => (
                    <option key={n.id} value={n.path} />
                  ))}
                </datalist>
                <div className="pointer-events-auto ml-auto flex gap-1">
                  {(
                    [
                      ['plus', 'Zoom in', () => engine.current?.zoomBy(0.75)],
                      ['minus', 'Zoom out', () => engine.current?.zoomBy(1.33)],
                      ['compass', 'Reset the view', () => engine.current?.reset()],
                      ['chevrons-down-up', 'Fold the map away and give the flow the whole height', () => setPanes('flow')],
                      ['keyboard', showKeys ? 'Hide keyboard controls' : 'Show keyboard controls', () => setShowKeys(v => !v)],
                      [immersive ? 'minimize-2' : 'maximize-2', immersive ? 'Leave full screen (Esc)' : 'Full screen', toggleImmersive],
                    ] as [IconName, string, () => void][]
                  ).map(([icon, label, act]) => (
                    <button
                      key={label}
                      type="button"
                      onClick={act}
                      aria-label={label}
                      title={label}
                      aria-pressed={icon === 'keyboard' ? showKeys : undefined}
                      className="atlas-float grid size-[34px] place-items-center rounded-lg text-ink-mid transition-colors hover:text-ink"
                    >
                      <Icon name={icon} size={16} />
                    </button>
                  ))}
                </div>
              </div>

              {showKeys && (
                <div className="atlas-keys atlas-float absolute bottom-3 left-3 z-[2100] flex max-w-[calc(100%-24px)] flex-wrap items-center gap-x-3.5 gap-y-1.5 rounded-lg px-3 py-2 text-[12px] text-ink-mid">
                  {KEY_HINTS.map(h => (
                    <span key={h.label} className="inline-flex items-center gap-1.5 whitespace-nowrap">
                      {h.keys.map(k => (
                        <kbd key={k} className={keysDown.includes(k) ? 'on' : ''}>
                          {k.slice(3)}
                        </kbd>
                      ))}
                      {h.label}
                    </span>
                  ))}
                  <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
                    <kbd>Shift</kbd>faster
                  </span>
                  <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
                    <Icon name="mouse" size={14} />
                    right-drag to look
                  </span>
                  <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
                    <Icon name="move-3d" size={14} />
                    left-drag to orbit
                  </span>
                  <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
                    <kbd>F</kbd>focus
                  </span>
                  <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
                    <kbd>Esc</kbd>
                    {immersive ? 'leave full screen' : 'step back'}
                  </span>
                </div>
              )}

              {hover && (
                <div
                  className="atlas-float pointer-events-none absolute z-[2200] flex max-w-[320px] items-start gap-2 rounded-md px-2.5 py-1.5 text-[12px] text-ink"
                  style={{
                    left: Math.min(hover.x + 14, (stageRef.current?.clientWidth ?? 600) - 330),
                    top: hover.y + 14,
                  }}
                >
                  {hover.info.glyph && (
                    <span
                      className="mt-px size-4 shrink-0 [&>svg]:size-4"
                      // The glyph is the studio's own icon markup, already in the page.
                      dangerouslySetInnerHTML={{ __html: hover.info.glyph.svg }}
                    />
                  )}
                  <span className="min-w-0">
                    <span className={hover.info.component !== undefined ? 'font-semibold' : 'font-mono break-all'}>
                      {hover.info.text}
                    </span>
                    {hover.info.sub && <span className="mt-0.5 block text-ink-mid">{hover.info.sub}</span>}
                  </span>
                </div>
              )}
            </div>

            {/* Under the map, in full screen too, with a bar between them to drag. */}
            {panes === 'both' ? (
              <Splitter column={columnRef} box={flowBoxRef} split={split} onSplit={setSplit} />
            ) : panes === 'map' ? (
              <div className="h-3 shrink-0" />
            ) : null}
            <div
              ref={flowBoxRef}
              className={`flex min-h-0 flex-col ${panes === 'flow' ? 'flex-1' : ''}`}
              style={panes === 'both' && split !== null ? { flex: `0 0 ${(split * 100).toFixed(2)}%` } : undefined}
            >
              <FlowPanel
                atlas={atlas}
                adj={adj}
                components={components}
                edges={compEdges}
                tiers={tiers}
                selection={selection}
                calls={calls.data}
                path={reqPath}
                tab={tab}
                onTab={setTab}
                onPickFile={i => pickFile(i)}
                onPickComponent={c => pickComponent(c)}
                onFocusComponent={focusPart}
                reduced={reduced}
                open={panes !== 'map'}
                onToggle={() => setPanes(p => (p === 'map' ? 'both' : 'map'))}
                fill={panes === 'flow'}
                onExpand={() => setPanes(p => (p === 'flow' ? 'both' : 'flow'))}
                stretch={panes === 'both' && split !== null}
              flowsView={
                <FlowsView
                  atlas={atlas}
                  flows={flowList.data?.flows}
                  loading={flowList.loading}
                  flow={flowDetail.data && flowDetail.data.id === flowId ? flowDetail.data : undefined}
                  flowLoading={flowDetail.loading}
                  selected={flowId}
                  onPick={id => setFlowId(id)}
                  onStep={pickStep}
                  reduced={reduced}
                />
              }
              />
            </div>
          </div>

          <aside className="min-h-0 overflow-y-auto rounded-[10px] border border-rule bg-panel">
            {touring &&
              (tour.data && stop ? (
                <TourCard
                  projectId={projectId}
                  tour={tour.data}
                  at={at}
                  onGo={goStop}
                  onClose={() => closeTour(at === stops.length - 1)}
                  onFile={path => {
                    const i = atlas.nodes.findIndex(n => n.path === path && !n.fact)
                    if (i >= 0) pickFile(i)
                  }}
                />
              ) : (
                <div className="flex items-center gap-2 border-b border-rule px-4 py-3.5 text-[12.5px] text-ink-mid">
                  {tour.error ? (
                    <>
                      <Icon name="triangle-alert" size={15} className="text-bad" /> The tour could not be built: {tour.error}
                      <button type="button" onClick={() => closeTour()} className="ml-auto text-ink-dim hover:text-ink">
                        Close
                      </button>
                    </>
                  ) : (
                    <>
                      <Icon name="loader" size={15} className="anim-spin" /> Building the tour from the reading…
                    </>
                  )}
                </div>
              ))}
            {selection?.kind === 'file' && selBlast ? (
              <Inspector
                projectId={projectId}
                atlas={atlas}
                adj={adj}
                selected={selection.i}
                blast={selBlast}
                preflight={preflight}
                calls={calls}
                source={source}
                onPick={i => pickFile(i)}
                onOpenSource={(path, line) => setSource({ path, line })}
                onCloseSource={() => setSource(null)}
                onDive={() => engine.current?.dive()}
                onComponent={c => pickComponent(c)}
              />
            ) : selection?.kind === 'component' ? (
              <ComponentPane
                projectId={projectId}
                atlas={atlas}
                adj={adj}
                components={components}
                edges={compEdges}
                c={selection.c}
                expanded={expanded.has(selection.c)}
                onToggle={() => toggle(selection.c)}
                onBack={clearSelection}
                onPickComponent={c => pickComponent(c)}
                onPickFile={i => pickFile(i)}
                onFocus={focusPart}
              />
            ) : touring ? null : (
              <OverviewPane
                atlas={atlas}
                components={components}
                expanded={expanded}
                focus={focus}
                onToggle={toggle}
                onPick={c => pickComponent(c)}
                onFocus={focusPart}
                onAll={open => applyExpanded(open ? new Set(parts) : new Set())}
              />
            )}
          </aside>
        </div>
      </div>

      <div ref={glyphRef} hidden aria-hidden>
        {glyphNames.map(n => (
          <span key={n} data-glyph={n}>
            <Icon name={n} size={24} />
          </span>
        ))}
      </div>
    </div>
  )
}
