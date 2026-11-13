import * as THREE from 'three'
import type { Atlas, FileCalls } from '../../lib/types'
import { shortName, type Blast } from './graph'
import { columnCentres, type LayoutResult } from './layout'
import type { ComponentInfo } from './model'

/* ------------------------------------------------------------------ *
 * The knowledge graph's 3D scene. Imperative on purpose: React owns the
 * page, the inspector and the 2D flow panel; this owns a canvas, and
 * they talk through a handful of methods and callbacks.
 *
 * What it draws, and why:
 *
 *   Components first. Each is a dashed boundary with its name, collapsed
 *   to a small sphere holding the icons of what it is mostly made of.
 *   Opening one lets its files out inside the boundary, so it is always
 *   clear which files belong to what. Opening everything at once is the
 *   unreadable view the first version opened on; now it is a choice.
 *
 *   Flows between them. Links are drawn at whatever level is open: file
 *   to file inside open components, component to component otherwise,
 *   and dots travel along them from the code that calls to the code it
 *   calls, so direction reads without arrowheads.
 *
 *   Files as pure icons, no badge, fading with distance from the camera
 *   so what is near reads first.
 *
 * The camera is prototype v3.1's, which the user approved: left-drag
 * orbits, holding the right button turns in place, W A S D and Q E fly,
 * the wheel zooms, F flies to the selection.
 * ------------------------------------------------------------------ */

export interface Glyph {
  key: string
  /** Complete SVG markup, already coloured. */
  svg: string
  color: string
}

export interface EngineTokens {
  panel: string
  sunk: string
  ink: string
  inkMid: string
  inkDim: string
  hot: string
  line: string
}

export interface HoverInfo {
  node?: number
  component?: number
  text: string
  sub?: string
  glyph?: Glyph
}

export interface EngineInit {
  canvas: HTMLCanvasElement
  stage: HTMLElement
  /** Holds one element per component, `data-comp="<index>"`: its name and its open and
   *  close button, rendered by React. The scene only moves them to where the
   *  component's boundary is on screen, so they stay real, crisp, clickable HTML. */
  overlay: HTMLElement
  atlas: Atlas
  layout: LayoutResult
  components: ComponentInfo[]
  /** The parts by column, left to right, as the layout placed them. Links between two
   *  closed parts that run back against the columns are drawn only on a closer look. */
  columns: number[][]
  glyphOf: (i: number) => Glyph
  kindGlyph: (kind: string) => Glyph
  symbolGlyph: (kind: string | null) => Glyph
  tokens: EngineTokens
  reducedMotion: boolean
  isImmersive: () => boolean
  onSelect: (i: number) => void
  onSelectComponent: (c: number) => void
  onHover: (hover: HoverInfo | null, x: number, y: number) => void
  onHoverComponent: (c: number | null) => void
  onKeys: (down: string[]) => void
  /** True while the camera is close enough to read the selected file's functions. */
  onCloseUp: (close: boolean) => void
  onSymbol: (line: number | null) => void
}

const MOVE = ['KeyW', 'KeyA', 'KeyS', 'KeyD', 'KeyQ', 'KeyE']
const CLOSE = 72
const R_MIN = 18
const R_MAX = 700
const MAX_PARTICLES = 520

interface Cam {
  th: number
  ph: number
  r: number
  tx: number
  ty: number
  tz: number
}

const dirOf = (th: number, ph: number) =>
  new THREE.Vector3(Math.sin(ph) * Math.sin(th), Math.cos(ph), Math.sin(ph) * Math.cos(th))

const ease = (t: number) => 1 - (1 - t) ** 3

function roundRect(g: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  g.beginPath()
  g.roundRect(x, y, w, h, r)
}

function withXmlns(svg: string): string {
  return svg.includes('xmlns=') ? svg : svg.replace('<svg', '<svg xmlns="http://www.w3.org/2000/svg"')
}

function loadSvg(svg: string, done: (img: HTMLImageElement) => void) {
  const img = new Image()
  img.onload = () => done(img)
  img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(withXmlns(svg))
}

type Lines = THREE.LineSegments<THREE.BufferGeometry, THREE.LineBasicMaterial>

type Ring = THREE.LineLoop<THREE.BufferGeometry, THREE.LineDashedMaterial>

interface ComponentVisual {
  boundary: Ring
  core: THREE.Sprite
  coreR: number
  expR: number
}

export class AtlasEngine {
  private renderer: THREE.WebGLRenderer
  private scene = new THREE.Scene()
  private cam = new THREE.PerspectiveCamera(48, 1, 0.1, 5000)
  private group = new THREE.Group()
  private N: number
  private comp: Int32Array
  private home: THREE.Vector3[] = []
  private cur: THREE.Vector3[] = []
  private centre: THREE.Vector3[] = []
  private sprites: THREE.Sprite[] = []
  private scale: number[] = []
  private visuals: (ComponentVisual | null)[] = []
  private tags = new Map<number, HTMLElement>()
  private heads = new Map<number, HTMLElement>()
  private curR: Float32Array
  private uses: number[][]
  private textures = new Map<string, THREE.Texture>()
  private labelTextures = new Map<string, { tex: THREE.Texture; aspect: number }>()
  /** One dashed unit circle, shared by every boundary and scaled to it. */
  private ringGeo: THREE.BufferGeometry
  /** Where each part stands with every part closed, and with any open. */
  private closedC: THREE.Vector3[] = []
  private openC: THREE.Vector3[] = []
  private spreadT = 0
  private tmp2 = new THREE.Vector3()
  private dotTex: THREE.Texture

  private buckets: Lines[] = []
  private bucketEdges: [number, number][][] = [[], [], []]
  private quietEdges: [number, number][] = []
  private colOf: Int32Array
  private focusLines: Lines
  private focusEdges: [number, number][] = []
  private tree: Lines
  private treeEdges: [number, number][] = []
  private pathLine: Lines
  private particles: THREE.Points<THREE.BufferGeometry, THREE.PointsMaterial>
  private particleEdges: { a: number; b: number; phase: number }[] = []
  private ring: THREE.Sprite

  private fileLabels = new Map<number, THREE.Sprite>()
  private labelShown = new Set<number>()
  private inside = new THREE.Group()
  private insideFor: number | null = null
  private insideSprites: THREE.Sprite[] = []

  private expanded = new Set<number>()
  private expandT: Float32Array
  private hidden = new Set<string>()
  private sel: number | null = null
  private selComp: number | null = null
  private hoverComp: number | null = null
  private listComp: number | null = null
  private path: number[] | null = null
  private pathSet: Set<number> | null = null
  /** Files lit with no line between them: a tour stop's files, the hotspots. */
  private highlight: Set<number> | null = null
  private reach = new Map<number, number>()
  private selT = 0
  private hover: number | null = null

  private O: Cam
  private G: Cam
  private homeCam: Cam
  private closedCam: Cam
  private openCam: Cam
  private keys = new Set<string>()
  private fast = false
  private overStage = false
  private down: { x: number; y: number; th: number; ph: number; moved: boolean; look: boolean } | null = null
  private last = 0
  private frameId = 0
  private closeUp = false
  private labelAt = 0
  private ray = new THREE.Raycaster()
  private ptr = new THREE.Vector2()
  private tmp = new THREE.Vector3()
  private resizer: ResizeObserver
  private off: (() => void)[] = []
  private disposed = false
  private paused = false

  constructor(private init: EngineInit) {
    const { canvas, atlas, layout, tokens, components } = init
    // Throws where WebGL is unavailable; the page catches it and says so.
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
    this.renderer.setClearColor(0x000000, 0)
    this.scene.add(this.group)
    this.group.add(this.inside)

    this.N = atlas.nodes.length
    this.uses = Array.from({ length: this.N }, () => [])
    this.comp = Int32Array.from(atlas.nodes, n => n.component)
    this.expandT = new Float32Array(atlas.components.length)
    this.colOf = new Int32Array(atlas.components.length).fill(-1)
    this.curR = new Float32Array(atlas.components.length)
    init.columns.forEach((col, k) => col.forEach(c => (this.colOf[c] = k)))
    this.dotTex = this.makeDotTexture()
    const pts: THREE.Vector3[] = []
    for (let k = 0; k < 96; k++) {
      const a = (k / 96) * Math.PI * 2
      pts.push(new THREE.Vector3(Math.cos(a), Math.sin(a), 0))
    }
    this.ringGeo = new THREE.BufferGeometry().setFromPoints(pts)

    // Closed, the parts pack into the same columns at their closed size, so the first
    // view is the whole codebase at a readable size; opening any spreads them out.
    const closedR = components.map(info => 8 + Math.cbrt(Math.max(1, info.members.length)) * 2.4)
    const closed = new Float32Array(atlas.components.length * 3)
    columnCentres(init.columns, closedR, closed, 104, 46)
    // Then widen the gaps between columns to the stage's shape, so a wide stage is
    // used across its width and the names over neighbouring columns do not collide.
    if (init.columns.length > 1) {
      let y0 = Infinity
      let y1 = -Infinity
      init.columns.flat().forEach(c => {
        y0 = Math.min(y0, closed[c * 3 + 1] - closedR[c])
        y1 = Math.max(y1, closed[c * 3 + 1] + closedR[c])
      })
      const aspect = init.canvas.clientWidth / Math.max(1, init.canvas.clientHeight) || 1.6
      const widths = init.columns.reduce((s, col) => s + 2 * Math.max(...col.map(c => closedR[c])), 0)
      const gap = ((y1 - y0 + 60) * aspect * 0.8 - widths) / (init.columns.length - 1)
      if (gap > 104) columnCentres(init.columns, closedR, closed, Math.min(gap, 300), 46)
    }
    for (let c = 0; c < atlas.components.length; c++) {
      this.openC.push(new THREE.Vector3(layout.centres[c * 3], layout.centres[c * 3 + 1], layout.centres[c * 3 + 2]))
      this.closedC.push(new THREE.Vector3(closed[c * 3], closed[c * 3 + 1], closed[c * 3 + 2]))
      this.centre.push(this.closedC[c].clone())
    }

    for (let i = 0; i < this.N; i++) {
      const p = new THREE.Vector3(layout.positions[i * 3], layout.positions[i * 3 + 1], layout.positions[i * 3 + 2])
      this.home.push(p)
      this.cur.push(this.centre[this.comp[i]].clone())
      const node = atlas.nodes[i]
      const sprite = new THREE.Sprite(
        new THREE.SpriteMaterial({ map: this.iconTexture(init.glyphOf(i)), transparent: true, depthWrite: false, opacity: 0 }),
      )
      const s = 4.6 + (Math.min(node.loc, 700) / 700) * 2.4 + (node.fact ? 1.8 : 0)
      this.scale.push(s)
      sprite.scale.setScalar(0.01)
      sprite.position.copy(this.cur[i])
      sprite.userData = { node: i }
      sprite.visible = false
      this.sprites.push(sprite)
      this.group.add(sprite)
    }

    components.forEach((info, c) => {
      if (!info.members.length) {
        this.visuals.push(null)
        return
      }
      // Open, a part is centred on its files, which the relaxation may have drawn a
      // little off the point the layout gave it.
      const mid = new THREE.Vector3()
      for (const i of info.members) mid.add(this.home[i])
      this.openC[c].copy(mid.divideScalar(info.members.length))
      // Open, the boundary fits the files it holds, with room for their icons.
      let far = 0
      for (const i of info.members) far = Math.max(far, this.home[i].distanceTo(this.openC[c]))
      const coreR = closedR[c]
      const expR = Math.max(coreR + 4, Math.min(layout.radii[c] + 5, far + 7))
      const boundary: Ring = new THREE.LineLoop(
        this.ringGeo,
        new THREE.LineDashedMaterial({
          color: new THREE.Color(tokens.inkDim),
          dashSize: 0.085,
          gapSize: 0.06,
          transparent: true,
          depthWrite: false,
        }),
      )
      boundary.computeLineDistances()
      boundary.position.copy(this.centre[c])
      boundary.userData = { comp: c }
      const core = new THREE.Sprite(
        new THREE.SpriteMaterial({ map: this.coreTexture(info), transparent: true, depthWrite: false }),
      )
      core.position.copy(this.centre[c])
      core.userData = { comp: c }
      this.group.add(boundary, core)
      this.visuals.push({ boundary, core, coreR, expR })
    })

    for (const [a, b] of atlas.edges) this.uses[a].push(b)

    const lines = (color: string, opacity: number): Lines =>
      new THREE.LineSegments(
        new THREE.BufferGeometry(),
        new THREE.LineBasicMaterial({ color: new THREE.Color(color), transparent: true, opacity, depthWrite: false }),
      )
    this.buckets = [lines(tokens.inkMid, 0.1), lines(tokens.inkMid, 0.2), lines(tokens.inkMid, 0.34)]
    this.focusLines = lines(tokens.hot, 0)
    this.tree = lines(tokens.hot, 0)
    this.pathLine = lines(tokens.hot, 0)
    this.group.add(...this.buckets, this.focusLines, this.tree, this.pathLine)
    this.allocate(this.tree, 0)
    this.allocate(this.pathLine, 0)

    this.particles = new THREE.Points(
      new THREE.BufferGeometry(),
      new THREE.PointsMaterial({
        map: this.dotTex,
        color: new THREE.Color(tokens.hot),
        size: 2.6,
        transparent: true,
        opacity: 0.9,
        depthWrite: false,
        sizeAttenuation: true,
      }),
    )
    this.group.add(this.particles)

    const rc = document.createElement('canvas')
    rc.width = rc.height = 128
    const rg = rc.getContext('2d')!
    rg.strokeStyle = tokens.hot
    rg.lineWidth = 7
    rg.beginPath()
    rg.arc(64, 64, 54, 0, Math.PI * 2)
    rg.stroke()
    this.ring = new THREE.Sprite(
      new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(rc), transparent: true, depthWrite: false, opacity: 0 }),
    )
    this.group.add(this.ring)

    // Room above the top row for its name and its column's heading.
    this.closedCam = this.frameFor(this.closedC, v => v.coreR * 1.5, 40)
    this.openCam = this.frameFor(this.openC, v => v.expR, 30)
    this.homeCam = this.closedCam
    this.O = { ...this.homeCam }
    this.G = { ...this.homeCam }

    this.rebuildEdges()
    this.bind()
    this.resizer = new ResizeObserver(() => this.resize())
    this.resizer.observe(init.stage)
    this.resize()
    this.frameId = requestAnimationFrame(this.frame)
  }

  /* ── textures ─────────────────────────────────────────────────────── */

  /** A file's icon, nothing round it: the kind's glyph in the kind's colour, with a
   *  soft dark halo so it reads over lines and other icons. */
  private iconTexture(glyph: Glyph): THREE.Texture {
    const cached = this.textures.get(glyph.key)
    if (cached) return cached
    const c = document.createElement('canvas')
    c.width = c.height = 128
    const g = c.getContext('2d')!
    const tex = new THREE.CanvasTexture(c)
    tex.colorSpace = THREE.SRGBColorSpace
    tex.anisotropy = 4
    this.textures.set(glyph.key, tex)
    loadSvg(glyph.svg, img => {
      g.shadowColor = 'rgba(0,0,0,0.85)'
      g.shadowBlur = 10
      g.drawImage(img, 18, 18, 92, 92)
      g.shadowBlur = 0
      g.drawImage(img, 18, 18, 92, 92)
      tex.needsUpdate = true
    })
    return tex
  }

  /** A collapsed component: the icons of the kinds it is mostly made of. */
  private coreTexture(info: ComponentInfo): THREE.Texture {
    const c = document.createElement('canvas')
    c.width = c.height = 256
    const g = c.getContext('2d')!
    const tex = new THREE.CanvasTexture(c)
    tex.colorSpace = THREE.SRGBColorSpace
    const kinds = info.dominant.slice(0, 3)
    const spots: [number, number, number][] =
      kinds.length === 1
        ? [[128, 128, 120]]
        : kinds.length === 2
          ? [[86, 128, 88], [170, 128, 88]]
          : [[128, 84, 78], [84, 160, 78], [172, 160, 78]]
    kinds.forEach((k, i) => {
      const [x, y, s] = spots[i]
      loadSvg(this.init.kindGlyph(k).svg, img => {
        g.shadowColor = 'rgba(0,0,0,0.85)'
        g.shadowBlur = 12
        g.drawImage(img, x - s / 2, y - s / 2, s, s)
        g.shadowBlur = 0
        g.drawImage(img, x - s / 2, y - s / 2, s, s)
        tex.needsUpdate = true
      })
    })
    return tex
  }

  private makeDotTexture(): THREE.Texture {
    const c = document.createElement('canvas')
    c.width = c.height = 64
    const g = c.getContext('2d')!
    const grad = g.createRadialGradient(32, 32, 0, 32, 32, 30)
    grad.addColorStop(0, 'rgba(255,255,255,1)')
    grad.addColorStop(0.45, 'rgba(255,255,255,0.9)')
    grad.addColorStop(1, 'rgba(255,255,255,0)')
    g.fillStyle = grad
    g.fillRect(0, 0, 64, 64)
    return new THREE.CanvasTexture(c)
  }

  private label(text: string, kind: 'component' | 'file' | 'symbol'): THREE.Sprite {
    const key = `${kind}:${text}`
    let entry = this.labelTextures.get(key)
    if (!entry) {
      const big = kind === 'component'
      const font = big ? '600 34px Geist, Inter, system-ui, sans-serif' : '500 26px Inter, system-ui, sans-serif'
      const c = document.createElement('canvas')
      const g = c.getContext('2d')!
      g.font = font
      const w = Math.min(900, Math.ceil(g.measureText(text).width) + (big ? 48 : 30))
      const h = big ? 64 : 48
      c.width = w + 8
      c.height = h + 8
      g.font = font
      g.fillStyle = this.init.tokens.sunk
      g.globalAlpha = 0.92
      roundRect(g, 4, 4, w, h, big ? 16 : 12)
      g.fill()
      g.globalAlpha = 1
      g.strokeStyle = this.init.tokens.line
      g.lineWidth = 2
      g.stroke()
      g.fillStyle = kind === 'symbol' ? this.init.tokens.inkMid : this.init.tokens.ink
      g.textAlign = 'center'
      g.textBaseline = 'middle'
      g.fillText(text, 4 + w / 2, 4 + h / 2 + 1)
      const tex = new THREE.CanvasTexture(c)
      tex.colorSpace = THREE.SRGBColorSpace
      entry = { tex, aspect: c.width / c.height }
      this.labelTextures.set(key, entry)
    }
    const sprite = new THREE.Sprite(
      new THREE.SpriteMaterial({ map: entry.tex, transparent: true, depthWrite: false, depthTest: false, opacity: 0 }),
    )
    // Sized on screen, not in the world (see `fit`).
    const px = kind === 'component' ? 38 : kind === 'file' ? 28 : 25
    sprite.userData = { px, aspect: entry.aspect }
    sprite.scale.set(entry.aspect, 1, 1)
    sprite.renderOrder = 10
    return sprite
  }

  /** Scale a label so it stays the same height on screen at any distance. */
  private fit(sprite: THREE.Sprite) {
    const { px, aspect } = sprite.userData as { px: number; aspect: number }
    const viewH = this.init.canvas.clientHeight || 600
    const d = this.cam.position.distanceTo(sprite.getWorldPosition(this.tmp))
    const h = (px / viewH) * 2 * Math.tan(THREE.MathUtils.degToRad(this.cam.fov / 2)) * d
    sprite.scale.set(h * aspect, h, 1)
    return h
  }

  /* ── which links are drawn, at the level that is open ────────────── */

  /** A node's anchor: itself if its component is open, else its component. */
  private anchor(i: number): number {
    const c = this.comp[i]
    if (!this.expanded.has(c)) return this.N + c
    return this.hidden.has(this.init.atlas.nodes[i].kind) && i !== this.sel ? -1 : i
  }

  private anchorPos(a: number): THREE.Vector3 {
    return a < this.N ? this.cur[a] : this.centre[a - this.N]
  }

  private rebuildEdges() {
    const counts = new Map<number, number>()
    const key = (a: number, b: number) => a * 100003 + b
    const pairs = new Map<number, [number, number]>()
    for (const [x, y] of this.init.atlas.edges) {
      const a = this.anchor(x)
      const b = this.anchor(y)
      if (a < 0 || b < 0 || a === b) continue
      const k = key(a, b)
      counts.set(k, (counts.get(k) ?? 0) + 1)
      pairs.set(k, [a, b])
    }
    this.bucketEdges = [[], [], []]
    this.quietEdges = []
    for (const [k, n] of counts) {
      const [a, b] = pairs.get(k)!
      const back = a >= this.N && b >= this.N && this.colOf[a - this.N] >= this.colOf[b - this.N]
      if (back) this.quietEdges.push([a, b])
      else this.bucketEdges[n >= 5 ? 2 : n >= 2 ? 1 : 0].push([a, b])
    }
    this.buckets.forEach((l, i) => this.allocate(l, this.bucketEdges[i].length))
    this.rebuildFocus()
  }

  private allocate(l: Lines, segments: number) {
    l.geometry.dispose()
    l.geometry = new THREE.BufferGeometry()
    l.geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(Math.max(1, segments) * 6), 3))
    l.geometry.setDrawRange(0, segments * 2)
  }

  private fill(l: Lines, edges: [number, number][], pos: (a: number) => THREE.Vector3) {
    const attr = l.geometry.getAttribute('position') as THREE.BufferAttribute | undefined
    if (!attr || !edges.length) return
    const arr = attr.array as Float32Array
    edges.forEach(([a, b], k) => {
      const p = pos(a)
      const q = pos(b)
      arr[k * 6] = p.x
      arr[k * 6 + 1] = p.y
      arr[k * 6 + 2] = p.z
      arr[k * 6 + 3] = q.x
      arr[k * 6 + 4] = q.y
      arr[k * 6 + 5] = q.z
    })
    attr.needsUpdate = true
  }

  /** Drawn over the rest: with a file selected, what it calls out to (what calls into
   *  it is the blast tree); otherwise the links touching the component being looked
   *  at, hovered, chosen in a list or selected. */
  private rebuildFocus() {
    const c = this.focusComp()
    this.focusEdges = []
    if (this.sel !== null) {
      const from = this.sel
      const seen = new Set<number>()
      for (const u of this.uses[from]) {
        const b = this.anchor(u)
        if (b < 0 || b === from || seen.has(b)) continue
        seen.add(b)
        this.focusEdges.push([from, b])
      }
    } else if (c !== null) {
      // One line to each part it talks to, from the part as a whole: what it is linked
      // with reads at a glance, where a line from every file is a fan of noise.
      const seen = new Set<number>()
      for (const bucket of [...this.bucketEdges, this.quietEdges])
        for (const [a, b] of bucket) {
          const ca = a < this.N ? this.comp[a] : a - this.N
          const cb = b < this.N ? this.comp[b] : b - this.N
          if (ca === cb || (ca !== c && cb !== c)) continue
          const from = this.N + ca
          const to = this.N + cb
          const k = from * 100003 + to
          if (seen.has(k)) continue
          seen.add(k)
          this.focusEdges.push([from, to])
        }
    }
    this.allocate(this.focusLines, this.focusEdges.length)
    this.rebuildParticles()
  }

  private focusComp(): number | null {
    return this.hoverComp ?? this.listComp ?? this.selComp
  }

  /** Dots that travel the links in the direction of the call: along the request path
   *  when there is one, into the selected file along its dependants, or between
   *  components otherwise. */
  private rebuildParticles() {
    const edges: { a: number; b: number; phase: number }[] = []
    const add = (a: number, b: number, n: number) => {
      for (let k = 0; k < n && edges.length < MAX_PARTICLES; k++) edges.push({ a, b, phase: (k / n + (a * 0.618 + b * 0.31)) % 1 })
    }
    if (this.path && this.path.length > 1) {
      for (let k = 0; k + 1 < this.path.length; k++) add(this.path[k], this.path[k + 1], 3)
    } else if (this.sel !== null) {
      // In along the files that call it, out along what it calls.
      for (const [child, parent] of this.treeEdges) add(child, parent, 1)
      for (const [a, b] of this.focusEdges) add(a, b, 2)
    } else if (this.focusComp() !== null) {
      for (const [a, b] of this.focusEdges) add(a, b, a >= this.N && b >= this.N ? 3 : 1)
    } else {
      this.bucketEdges.forEach((bucket, w) => {
        // A single import between two parts is drawn but not travelled: the dots are
        // for the links that carry the weight.
        for (const [a, b] of bucket) if (a >= this.N || b >= this.N) add(a, b, w * 2)
      })
    }
    this.particleEdges = edges
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(Math.max(1, edges.length) * 3), 3))
    geo.setDrawRange(0, edges.length)
    this.particles.geometry.dispose()
    this.particles.geometry = geo
  }

  /* ── input ────────────────────────────────────────────────────────── */

  private on<K extends keyof WindowEventMap>(
    target: Window | HTMLElement,
    type: K,
    fn: (e: WindowEventMap[K]) => void,
    opts?: AddEventListenerOptions,
  ) {
    target.addEventListener(type, fn as EventListener, opts)
    this.off.push(() => target.removeEventListener(type, fn as EventListener, opts))
  }

  private camPos(): THREE.Vector3 {
    const G = this.G
    return dirOf(G.th, G.ph).multiplyScalar(G.r).add(new THREE.Vector3(G.tx, G.ty, G.tz))
  }

  private hit(e: { clientX: number; clientY: number }): { node?: number; comp?: number; symbol?: number } | null {
    const r = this.init.canvas.getBoundingClientRect()
    this.ptr.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1)
    this.ray.setFromCamera(this.ptr, this.cam)
    const targets: THREE.Object3D[] = [
      ...this.insideSprites.filter(s => s.visible && s.material.opacity > 0.3),
      ...this.sprites.filter(s => s.visible && s.material.opacity > 0.12),
    ]
    for (const v of this.visuals) if (v && v.core.visible && v.core.material.opacity > 0.3) targets.push(v.core)
    const h = this.ray.intersectObjects(targets)[0]
    return h ? (h.object.userData as { node?: number; comp?: number; symbol?: number }) : null
  }

  private bind() {
    const { canvas, stage, atlas, components } = this.init
    const typing = (t: EventTarget | null) =>
      t instanceof HTMLElement && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)
    const live = () => this.overStage || document.activeElement === canvas || this.init.isImmersive()

    this.on(canvas, 'contextmenu', e => e.preventDefault())
    this.on(stage, 'pointerenter', () => (this.overStage = true))
    this.on(stage, 'pointerleave', () => (this.overStage = false))

    this.on(canvas, 'pointerdown', e => {
      canvas.focus({ preventScroll: true })
      const look = e.button === 2
      this.down = { x: e.clientX, y: e.clientY, th: this.G.th, ph: this.G.ph, moved: look, look }
      if (look) {
        canvas.classList.add('looking')
        this.init.onHover(null, 0, 0)
      }
      canvas.setPointerCapture(e.pointerId)
    })

    this.on(canvas, 'pointermove', e => {
      const d = this.down
      if (d && d.look) {
        // Look: turn where the camera stands, so the target moves instead.
        const P = this.camPos()
        this.G.th -= e.movementX * 0.0035
        this.G.ph = Math.max(0.15, Math.min(3, this.G.ph - e.movementY * 0.0035))
        const v = dirOf(this.G.th, this.G.ph).multiplyScalar(this.G.r)
        this.G.tx = P.x - v.x
        this.G.ty = P.y - v.y
        this.G.tz = P.z - v.z
        return
      }
      if (d) {
        const dx = e.clientX - d.x
        const dy = e.clientY - d.y
        if (Math.abs(dx) + Math.abs(dy) > 4) d.moved = true
        this.G.th = d.th - dx * 0.006
        this.G.ph = Math.max(0.3, Math.min(2.85, d.ph - dy * 0.006))
        return
      }
      const h = this.hit(e)
      const r = stage.getBoundingClientRect()
      const x = e.clientX - r.left
      const y = e.clientY - r.top
      let hoverComp: number | null = null
      if (h?.node !== undefined) {
        this.hover = h.node
        const node = atlas.nodes[h.node]
        this.init.onHover({ node: h.node, text: node.path, glyph: this.init.glyphOf(h.node) }, x, y)
        canvas.style.cursor = 'pointer'
      } else if (h?.comp !== undefined) {
        this.hover = null
        hoverComp = h.comp
        const info = components[h.comp]
        this.init.onHover(
          {
            component: h.comp,
            text: info.name,
            sub: `${info.members.length} files${info.description ? ` · ${info.description}` : ''}${this.expanded.has(h.comp) ? '' : ' · click to open'}`,
          },
          x,
          y,
        )
        canvas.style.cursor = 'pointer'
      } else if (h?.symbol !== undefined) {
        this.hover = null
        const s = this.insideSprites[h.symbol].userData as { text: string; kind: string | null }
        this.init.onHover({ text: s.text, glyph: this.init.symbolGlyph(s.kind) }, x, y)
        canvas.style.cursor = 'pointer'
      } else {
        this.hover = null
        this.init.onHover(null, 0, 0)
        canvas.style.cursor = ''
      }
      if (hoverComp !== this.hoverComp) {
        this.hoverComp = hoverComp
        this.init.onHoverComponent(hoverComp)
        this.rebuildFocus()
      }
    })

    this.on(canvas, 'pointerup', e => {
      const d = this.down
      if (d && !d.moved) {
        const h = this.hit(e)
        if (h?.node !== undefined) this.init.onSelect(h.node)
        else if (h?.comp !== undefined) this.init.onSelectComponent(h.comp)
        else if (h?.symbol !== undefined) {
          const s = this.insideSprites[h.symbol].userData as { line: number | null }
          this.init.onSymbol(s.line)
        }
      }
      if (d?.look) canvas.classList.remove('looking')
      this.down = null
    })

    this.on(canvas, 'pointerleave', () => {
      this.hover = null
      this.init.onHover(null, 0, 0)
      if (this.hoverComp !== null) {
        this.hoverComp = null
        this.init.onHoverComponent(null)
        this.rebuildFocus()
      }
    })

    this.on(
      canvas,
      'wheel',
      e => {
        e.preventDefault()
        this.G.r = Math.max(R_MIN, Math.min(R_MAX, this.G.r * (e.deltaY > 0 ? 1.12 : 0.89)))
      },
      { passive: false },
    )

    this.on(window, 'keydown', e => {
      if (!live() || typing(e.target) || e.ctrlKey || e.metaKey || e.altKey) return
      this.fast = e.shiftKey
      if (MOVE.includes(e.code)) {
        if (!this.keys.has(e.code)) {
          this.keys.add(e.code)
          this.init.onKeys([...this.keys])
        }
        e.preventDefault()
      } else if (e.code === 'KeyF') {
        const f = this.sel ?? this.hover
        if (f !== null) {
          this.flyTo(f, 70)
          e.preventDefault()
        } else if (this.selComp !== null) {
          this.flyToComponent(this.selComp)
          e.preventDefault()
        }
      }
    })
    this.on(window, 'keyup', e => {
      this.fast = e.shiftKey
      if (this.keys.delete(e.code)) this.init.onKeys([...this.keys])
    })
    this.on(window, 'blur', () => {
      if (this.keys.size) {
        this.keys.clear()
        this.init.onKeys([])
      }
    })
  }

  /* ── what React asks for ─────────────────────────────────────────── */

  setExpanded(set: Set<number>) {
    this.expanded = new Set(set)
    if (this.init.reducedMotion) for (let c = 0; c < this.expandT.length; c++) this.expandT[c] = set.has(c) ? 1 : 0
    this.rebuildEdges()
  }

  setHidden(kinds: Set<string>) {
    this.hidden = kinds
    this.rebuildEdges()
  }

  /** A file, with the shortest-path tree to everything that would break. */
  select(i: number, b: Blast, fly = true) {
    this.sel = i
    this.selComp = null
    this.selT = performance.now()
    this.reach = b.distance
    // child → parent: the child imports the parent, so the call goes that way.
    this.treeEdges = [...b.parent].map(([child, parent]) => [child, parent])
    this.allocate(this.tree, this.treeEdges.length)
    if (fly) this.flyTo(i, Math.min(this.G.r, 160))
    if (this.insideFor !== i) this.setInside(null)
    this.rebuildFocus()
  }

  selectComponent(c: number | null, fly = true) {
    this.selComp = c
    this.sel = null
    this.reach = new Map()
    this.treeEdges = []
    this.allocate(this.tree, 0)
    this.setInside(null)
    if (c !== null && fly) this.flyToComponent(c)
    this.rebuildFocus()
  }

  clearSelection() {
    this.selectComponent(null, false)
  }

  /** A component pointed at from outside the canvas: a list row, a box in the 2D flow. */
  setFocusComponent(c: number | null) {
    if (c === this.listComp) return
    this.listComp = c
    this.rebuildFocus()
  }

  /** A chain of files to light, in order of the call: the request path. */
  setPath(nodes: number[] | null) {
    this.path = nodes && nodes.length > 1 ? nodes : null
    this.pathSet = this.path ? new Set(this.path) : null
    const edges: [number, number][] = []
    if (this.path) for (let k = 0; k + 1 < this.path.length; k++) edges.push([this.path[k], this.path[k + 1]])
    this.pathEdges = edges
    this.allocate(this.pathLine, edges.length)
    this.rebuildParticles()
  }
  private pathEdges: [number, number][] = []

  /** A set of files to light, the rest dimmed. Under a selection and a path: picking a
   *  file still shows what it reaches. */
  setHighlight(nodes: number[] | null) {
    this.highlight = nodes && nodes.length ? new Set(nodes) : null
  }

  /** Where a part will stand once the parts now open or closed have moved. */
  private centreTarget(c: number): THREE.Vector3 {
    return this.expanded.size ? this.openC[c] : this.closedC[c]
  }

  flyTo(i: number, r?: number) {
    const p = this.expanded.has(this.comp[i]) ? this.home[i] : this.centreTarget(this.comp[i])
    this.G.tx = p.x
    this.G.ty = p.y
    this.G.tz = p.z
    if (r !== undefined) this.G.r = r
  }

  flyToComponent(c: number) {
    const p = this.centreTarget(c)
    const v = this.visuals[c]
    this.G.tx = p.x
    this.G.ty = p.y
    this.G.tz = p.z
    this.G.r = Math.max(60, Math.min(260, this.expanded.has(c) ? (v?.expR ?? 30) * 3.4 : (v?.coreR ?? 12) * 6))
  }

  /** Close enough to read the selected file's functions. */
  dive() {
    if (this.sel !== null) this.flyTo(this.sel, 46)
  }

  zoomBy(f: number) {
    this.G.r = Math.max(R_MIN, Math.min(R_MAX, this.G.r * f))
  }

  /** Back to the whole codebase, framed for what is open: the parts closed fit in a
   *  closer view than the same parts with every file out. */
  reset() {
    const open = this.visuals.filter((v, c) => v && this.expanded.has(c)).length
    const all = this.visuals.filter(Boolean).length
    Object.assign(this.G, open * 2 > all ? this.openCam : this.closedCam)
  }

  /** A camera that sees every part, each counted at the radius given: nearly straight
   *  on, so the columns read left to right, turned a little to show the depth. */
  private frameFor(at: THREE.Vector3[], radius: (v: ComponentVisual) => number, headroom: number): Cam {
    let x0 = Infinity
    let x1 = -Infinity
    let y0 = Infinity
    let y1 = -Infinity
    this.visuals.forEach((v, c) => {
      if (!v) return
      const p = at[c]
      const r = radius(v)
      x0 = Math.min(x0, p.x - r)
      x1 = Math.max(x1, p.x + r)
      y0 = Math.min(y0, p.y - r)
      y1 = Math.max(y1, p.y + r + headroom)
    })
    if (!Number.isFinite(x0)) return { th: 0.2, ph: 1.34, r: 240, tx: 0, ty: 0, tz: 0 }
    const t = Math.tan(THREE.MathUtils.degToRad(this.cam.fov / 2))
    const aspect = Math.max(1, this.init.canvas.clientWidth / Math.max(1, this.init.canvas.clientHeight)) || 1.6
    const r = Math.max((x1 - x0) / (2 * t * aspect), (y1 - y0) / (2 * t)) * 1.12 + 20
    return { th: 0.2, ph: 1.34, r: Math.max(R_MIN * 4, Math.min(R_MAX, r)), tx: (x0 + x1) / 2, ty: (y0 + y1) / 2, tz: 0 }
  }

  focusCanvas() {
    this.init.canvas.focus({ preventScroll: true })
  }

  /** The selected file's classes and functions, in a ring round it, with lines to
   *  the files they call into and are called from. */
  setInside(calls: FileCalls | null, i: number | null = this.sel) {
    for (const s of this.inside.children) ((s as THREE.Sprite).material as THREE.Material)?.dispose?.()
    this.inside.clear()
    this.insideSprites = []
    this.insideFor = null
    if (!calls || i === null) return
    const { atlas, tokens } = this.init
    const index = new Map(atlas.nodes.map((n, k) => [n.path, k]))
    const centre = this.home[i]
    const symbols = calls.symbols.slice(0, 36)
    const radius = 10 + symbols.length * 0.6
    const at = new Map<string, THREE.Vector3>()
    const tilt = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), 0.35)

    symbols.forEach((s, k) => {
      const a = (k / Math.max(1, symbols.length)) * Math.PI * 2
      const p = new THREE.Vector3(Math.cos(a) * radius, 0, Math.sin(a) * radius).applyQuaternion(tilt).add(centre)
      at.set(s.qname, p)
      const incoming = calls.incoming.filter(c => c.callee === s.qname).length
      const sprite = new THREE.Sprite(
        new THREE.SpriteMaterial({ map: this.iconTexture(this.init.symbolGlyph(s.kind)), transparent: true, depthWrite: false, opacity: 0 }),
      )
      sprite.scale.setScalar(3.6)
      sprite.position.copy(p)
      sprite.userData = {
        symbol: this.insideSprites.length,
        line: s.line,
        kind: s.kind,
        text: `${s.qname}${incoming ? ` · called from ${incoming} place${incoming === 1 ? '' : 's'} elsewhere` : ''}`,
      }
      this.insideSprites.push(sprite)
      this.inside.add(sprite)
      const label = this.label(s.name || s.qname, 'symbol')
      label.position.copy(p).add(new THREE.Vector3(0, 3.2, 0))
      label.userData.label = true
      this.inside.add(label)
    })

    const out: number[] = []
    const inc: number[] = []
    for (const c of calls.outgoing) {
      const from = at.get(c.caller)
      const to = index.get(c.path)
      if (from && to !== undefined) out.push(...from.toArray(), ...this.home[to].toArray())
    }
    for (const c of calls.incoming) {
      const to = at.get(c.callee)
      const from = index.get(c.path)
      if (to && from !== undefined) inc.push(...this.home[from].toArray(), ...to.toArray())
    }
    const segs = (pts: number[], color: string) => {
      const geo = new THREE.BufferGeometry()
      geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(pts), 3))
      const l = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ color: new THREE.Color(color), transparent: true, opacity: 0 }))
      l.userData = { calls: true }
      this.inside.add(l)
    }
    segs(out, tokens.hot)
    segs(inc, tokens.ink)
    this.insideFor = i
  }

  resize() {
    const { canvas } = this.init
    const w = canvas.clientWidth
    const h = canvas.clientHeight
    if (!w || !h) return
    this.renderer.setSize(w, h, false)
    this.cam.aspect = w / h
    this.cam.updateProjectionMatrix()
  }

  dispose() {
    this.disposed = true
    cancelAnimationFrame(this.frameId)
    this.resizer.disconnect()
    this.off.forEach(f => f())
    this.scene.traverse(o => {
      const m = o as THREE.Mesh
      m.geometry?.dispose?.()
      const mat = m.material as THREE.Material | undefined
      mat?.dispose?.()
    })
    this.textures.forEach(t => t.dispose())
    this.labelTextures.forEach(t => t.tex.dispose())
    this.ringGeo.dispose()
    this.dotTex.dispose()
    this.renderer.dispose()
  }

  /* ── the frame ────────────────────────────────────────────────────── */

  /** Stop drawing while the map is folded away; the scene keeps its state. */
  setPaused(paused: boolean) {
    if (paused === this.paused) return
    this.paused = paused
    if (!paused) {
      this.last = 0
      this.resize()
    }
  }

  private frame = (t: number) => {
    if (this.disposed) return
    this.frameId = requestAnimationFrame(this.frame)
    if (this.paused) return
    const RM = this.init.reducedMotion
    const dt = Math.min(0.05, this.last ? (t - this.last) / 1000 : 0)
    this.last = t
    const { O, G } = this

    // Fly.
    if (this.keys.size) {
      const f = dirOf(G.th, G.ph).multiplyScalar(-1)
      const rt = new THREE.Vector3().crossVectors(f, new THREE.Vector3(0, 1, 0)).normalize()
      const v = new THREE.Vector3()
      if (this.keys.has('KeyW')) v.add(f)
      if (this.keys.has('KeyS')) v.sub(f)
      if (this.keys.has('KeyD')) v.add(rt)
      if (this.keys.has('KeyA')) v.sub(rt)
      if (this.keys.has('KeyE')) v.y += 1
      if (this.keys.has('KeyQ')) v.y -= 1
      if (v.lengthSq()) {
        v.normalize().multiplyScalar((40 + G.r * 0.4) * (this.fast ? 3 : 1) * dt)
        G.tx += v.x
        G.ty += v.y
        G.tz += v.z
      }
    }
    const camEase = RM ? 1 : 0.08
    for (const k of Object.keys(O) as (keyof Cam)[]) O[k] += (G[k] - O[k]) * camEase
    const sp = Math.sin(O.ph)
    this.cam.position.set(O.tx + O.r * sp * Math.sin(O.th), O.ty + O.r * Math.cos(O.ph), O.tz + O.r * sp * Math.cos(O.th))
    this.cam.lookAt(O.tx, O.ty, O.tz)

    const close = O.r < CLOSE && this.insideFor !== null
    if (close !== this.closeUp) {
      this.closeUp = close
      this.init.onCloseUp(close)
    }

    // Open and close components.
    let moving = false
    for (let c = 0; c < this.expandT.length; c++) {
      const want = this.expanded.has(c) ? 1 : 0
      const d = want - this.expandT[c]
      if (Math.abs(d) > 0.001) {
        this.expandT[c] = RM ? want : this.expandT[c] + Math.sign(d) * Math.min(Math.abs(d), dt * 2.6)
        moving = true
      }
    }
    const spreadWant = this.expanded.size ? 1 : 0
    if (this.spreadT !== spreadWant) {
      const d = spreadWant - this.spreadT
      this.spreadT =
        RM || Math.abs(d) < 0.001 ? spreadWant : this.spreadT + Math.sign(d) * Math.min(Math.abs(d), dt * 2.2)
      moving = true
    }
    const spread = ease(this.spreadT)
    for (let c = 0; c < this.centre.length; c++) this.centre[c].copy(this.closedC[c]).lerp(this.openC[c], spread)
    for (let i = 0; i < this.N; i++) {
      const c = this.comp[i]
      const e = ease(this.expandT[c])
      this.cur[i].copy(this.centre[c]).addScaledVector(this.tmp2.subVectors(this.home[i], this.openC[c]), e)
    }

    // Files.
    const since = RM ? 1e9 : t - this.selT
    const focus = this.focusComp()
    const sel = this.sel
    const { atlas } = this.init
    this.sprites.forEach((s, i) => {
      const e = ease(this.expandT[this.comp[i]])
      const hiddenKind = this.hidden.has(atlas.nodes[i].kind) && i !== sel
      s.visible = e > 0.02 && !hiddenKind
      if (!s.visible) return
      s.position.copy(this.cur[i])
      const dist = this.cam.position.distanceTo(this.cur[i])
      // Near reads first: brightest at the camera's target distance and nearer,
      // falling away behind it, and thinning out if it comes right up to the lens.
      const depth = Math.max(0.2, Math.min(1, 1.55 - 0.65 * (dist / Math.max(1, O.r))))
      const lens = Math.max(0.06, Math.min(1, (dist - 6) / 26))
      let want = 1
      if (this.pathSet) want = this.pathSet.has(i) ? 1 : 0.16
      else if (sel !== null) {
        const d = this.reach.get(i)
        want = d !== undefined && since > d * 260 ? 1 : 0.24
      } else if (this.highlight) want = this.highlight.has(i) ? 1 : 0.16
      else if (focus !== null) want = this.comp[i] === focus ? 1 : 0.22
      if (this.closeUp && i !== sel) want *= 0.22
      want *= i === sel ? 1 : depth * lens
      s.material.opacity += (want * e - s.material.opacity) * (RM ? 1 : 0.16)
      const up = i === sel ? 1.5 : i === this.hover ? 1.3 : this.highlight?.has(i) && sel === null && !this.pathSet ? 1.35 : 1
      const target = this.scale[i] * up * (0.35 + 0.65 * e)
      s.scale.setScalar(s.scale.x + (target - s.scale.x) * (RM ? 1 : 0.2))
    })

    // Components.
    this.visuals.forEach((v, c) => {
      if (!v) return
      const e = ease(this.expandT[c])
      const r = v.coreR + (v.expR - v.coreR) * e
      this.curR[c] = r
      const focused = focus === c
      // The selected file's own component stays legible round it.
      const home = sel !== null && this.comp[sel] === c
      const dimmed = !home && ((focus !== null && !focused) || sel !== null || this.pathSet !== null)
      v.boundary.position.copy(this.centre[c])
      v.core.position.copy(this.centre[c])
      v.boundary.quaternion.copy(this.cam.quaternion)
      v.boundary.scale.setScalar(r)
      v.boundary.material.color.set(focused ? this.init.tokens.hot : this.init.tokens.inkDim)
      const bWant = focused ? 1 : home ? 0.75 : dimmed ? 0.3 : e > 0.5 ? 0.6 : 0.85
      v.boundary.material.opacity += (bWant - v.boundary.material.opacity) * (RM ? 1 : 0.15)
      const cWant = (1 - e) * (dimmed && !focused ? 0.3 : 1)
      v.core.material.opacity += (cWant - v.core.material.opacity) * (RM ? 1 : 0.18)
      v.core.visible = v.core.material.opacity > 0.02
      v.core.scale.setScalar(v.coreR * 1.55)

      // Its name and its open/close button: HTML, placed above the boundary.
      let tag = this.tags.get(c)
      if (!tag || !tag.isConnected) {
        tag = this.init.overlay.querySelector<HTMLElement>(`[data-comp="${c}"]`) ?? undefined
        if (tag) this.tags.set(c, tag)
      }
      if (!tag) return
      this.tmp.copy(this.centre[c]).project(this.cam)
      const W = this.init.canvas.clientWidth
      const H = this.init.canvas.clientHeight
      const d = this.cam.position.distanceTo(this.centre[c])
      const behind = this.tmp.z > 1 || d < r * 0.6
      const x = ((this.tmp.x + 1) / 2) * W
      const screenR = (r / (d * Math.tan(THREE.MathUtils.degToRad(this.cam.fov / 2)))) * (H / 2)
      const y = ((1 - this.tmp.y) / 2) * H - screenR - 6
      const off = behind || x < -120 || x > W + 120 || y < -40 || y > H + 40
      const lWant = off || this.closeUp ? 0 : dimmed && !focused ? 0.4 : 1
      const was = Number(tag.dataset.alpha ?? 0)
      const alpha = RM ? lWant : was + (lWant - was) * 0.2
      tag.dataset.alpha = alpha.toFixed(3)
      tag.style.opacity = alpha.toFixed(3)
      tag.style.visibility = alpha < 0.03 ? 'hidden' : 'visible'
      tag.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px) translate(-50%, -100%)`
      tag.style.zIndex = String(Math.max(1, Math.round(2000 - d)))
      tag.dataset.focus = focused ? 'true' : 'false'
      tag.dataset.open = this.expanded.has(c) ? 'true' : 'false'
    })

    // Each column's heading, over its topmost part, while the whole codebase is in view.
    this.init.columns.forEach((col, k) => {
      let head = this.heads.get(k)
      if (!head || !head.isConnected) {
        head = this.init.overlay.querySelector<HTMLElement>(`[data-col="${k}"]`) ?? undefined
        if (head) this.heads.set(k, head)
      }
      if (!head || !col.length) return
      let top = -Infinity
      let x = 0
      for (const c of col) {
        top = Math.max(top, this.centre[c].y + this.curR[c])
        x += this.centre[c].x
      }
      this.tmp.set(x / col.length, top, 0).project(this.cam)
      const W = this.init.canvas.clientWidth
      const H = this.init.canvas.clientHeight
      const px = ((this.tmp.x + 1) / 2) * W
      const py = ((1 - this.tmp.y) / 2) * H - 44
      const want = this.tmp.z > 1 || this.closeUp || sel !== null || this.pathSet ? 0 : focus !== null ? 0.35 : 0.9
      const was = Number(head.dataset.alpha ?? 0)
      const alpha = RM ? want : was + (want - was) * 0.15
      head.dataset.alpha = alpha.toFixed(3)
      head.style.opacity = alpha.toFixed(3)
      head.style.visibility = alpha < 0.03 ? 'hidden' : 'visible'
      head.style.transform = `translate(${px.toFixed(1)}px, ${py.toFixed(1)}px) translate(-50%, -100%)`
    })

    // Links.
    const linkPos = (a: number) => this.anchorPos(a)
    this.buckets.forEach((l, k) => {
      this.fill(l, this.bucketEdges[k], linkPos)
      const base = [0.07, 0.17, 0.32][k]
      l.material.opacity = sel !== null || this.pathSet ? base * 0.35 : focus !== null ? base * 0.5 : base
    })
    this.fill(this.focusLines, this.focusEdges, linkPos)
    // What the selection calls is drawn light; what calls it, the blast tree, hot.
    this.focusLines.material.color.set(sel !== null ? this.init.tokens.ink : this.init.tokens.hot)
    this.focusLines.material.opacity = this.pathSet ? 0 : sel !== null ? Math.min(0.55, since / 900) : focus !== null ? 0.6 : 0
    this.fill(this.tree, this.treeEdges, a => this.cur[a])
    this.tree.material.opacity = sel === null || this.pathSet ? 0 : Math.min(0.8, since / 700)
    this.fill(this.pathLine, this.pathEdges, a => this.cur[a])
    this.pathLine.material.opacity = this.pathSet ? 0.95 : 0

    // Dots, travelling the way the call goes.
    const pAttr = this.particles.geometry.getAttribute('position') as THREE.BufferAttribute
    const pArr = pAttr.array as Float32Array
    const speed = this.pathSet ? 0.45 : 0.28
    this.particleEdges.forEach((pe, k) => {
      const a = linkPos(pe.a)
      const b = linkPos(pe.b)
      const f = RM ? 0.5 : (pe.phase + (t / 1000) * speed) % 1
      pArr[k * 3] = a.x + (b.x - a.x) * f
      pArr[k * 3 + 1] = a.y + (b.y - a.y) * f
      pArr[k * 3 + 2] = a.z + (b.z - a.z) * f
    })
    pAttr.needsUpdate = true
    this.particles.material.opacity = RM ? 0 : this.pathSet ? 1 : sel !== null ? Math.min(0.9, since / 900) : focus !== null ? 0.45 : 0.75
    this.particles.material.size = this.pathSet ? 3.4 : 2.6

    // The selection's ring.
    this.ring.material.opacity = sel === null ? 0 : RM ? 0.9 : 0.55 + 0.3 * Math.sin(t / 260)
    if (sel !== null) {
      this.ring.position.copy(this.cur[sel])
      this.ring.scale.setScalar(this.scale[sel] * 1.5 * 1.35)
    }

    // File names.
    if (t - this.labelAt > 250 || moving) {
      this.labelAt = t
      this.updateLabels()
    }
    for (const [i, l] of this.fileLabels) {
      const want = this.labelShown.has(i) && this.sprites[i].visible ? 1 : 0
      l.material.opacity += (want - l.material.opacity) * (RM ? 1 : 0.2)
      l.visible = l.material.opacity > 0.02
      if (!l.visible) continue
      l.position.copy(this.cur[i])
      const h = this.fit(l)
      l.position.y += this.sprites[i].scale.x * 0.55 + h * 0.6
    }

    // Functions fade in as the camera closes on the selected file.
    const insideAlpha = this.insideFor === null ? 0 : Math.max(0, Math.min(1, (CLOSE + 18 - O.r) / 30))
    this.inside.children.forEach(o => {
      const m = (o as THREE.Sprite).material as THREE.Material & { opacity: number }
      const target = o.userData.calls ? insideAlpha * 0.55 : insideAlpha
      m.opacity += (target - m.opacity) * (RM ? 1 : 0.15)
      o.visible = m.opacity > 0.02
      if (o.visible && o.userData.label) this.fit(o as THREE.Sprite)
    })

    this.renderer.render(this.scene, this.cam)
  }

  /** Which files get their name drawn: the selection and its direct dependants, the
   *  request path, what is under the pointer, and, close in, the files near the target. */
  private updateLabels() {
    const { O } = this
    const want = new Set<number>()
    if (this.path) this.path.forEach(i => want.add(i))
    if (this.sel !== null) {
      want.add(this.sel)
      if (!this.path) for (const [i, d] of this.reach) if (d === 1 && want.size < 12) want.add(i)
    }
    if (this.hover !== null) want.add(this.hover)
    const reading = O.r < CLOSE && this.insideFor !== null
    if (!reading && O.r < 150) {
      const target = new THREE.Vector3(O.tx, O.ty, O.tz)
      const radius = O.r * 0.7
      const near: [number, number][] = []
      this.cur.forEach((p, i) => {
        if (!this.sprites[i].visible || this.sprites[i].material.opacity < 0.3) return
        const d = p.distanceTo(target)
        if (d < radius) near.push([i, d])
      })
      near.sort((a, b) => a[1] - b[1])
      for (const [i] of near.slice(0, 24)) want.add(i)
    }
    for (const i of want) {
      if (!this.fileLabels.has(i)) {
        const node = this.init.atlas.nodes[i]
        const l = this.label(node.fact ? node.path : shortName(node.path), 'file')
        this.fileLabels.set(i, l)
        this.group.add(l)
      }
    }
    this.labelShown = want
  }
}
