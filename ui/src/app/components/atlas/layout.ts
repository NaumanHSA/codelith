/* ------------------------------------------------------------------ *
 * Where every node sits in the atlas.
 *
 * Components stand in columns, left to right in the order a request meets
 * them (`componentTiers`), each column staggered in depth so its parts do
 * not hide one another; without columns they are spread over a sphere.
 * Each component's files sit in a ball round its centre. Then a short relaxation: files that import each
 * other inside a component are drawn together, any two that crowd are
 * pushed apart, and none may leave its component's ball. Deterministic,
 * with no randomness, so the same knowledge base always draws the same
 * map and the cached result stays true.
 *
 * Runs in a worker (`layout.worker.ts`); this module has no DOM and no
 * three.js so it can.
 * ------------------------------------------------------------------ */

export interface LayoutInput {
  componentCount: number
  /** Each node's component index. */
  component: Int32Array
  /** Flat [a0, b0, a1, b1, …]. */
  edges: Int32Array
  /** Components by column, left to right, each column top to bottom. */
  columns?: number[][]
}

export interface LayoutResult {
  /** Flat x, y, z per node. */
  positions: Float32Array
  /** Flat x, y, z per component. */
  centres: Float32Array
  /** The radius of each component's ball. */
  radii: Float32Array
}

const GOLDEN = 2.399963229728653
const ITERATIONS = 140
const MIN_GAP = 7.5
/** Room between columns for the links to be seen running between them. */
const GAP_X = 64
const GAP_Y = 14

function fib(i: number, n: number): [number, number, number] {
  const y = 1 - (2 * (i + 0.5)) / n
  const r = Math.sqrt(Math.max(0, 1 - y * y))
  const th = i * GOLDEN
  return [Math.cos(th) * r, y, Math.sin(th) * r]
}

/** Columns left to right; down each column, parts alternate forward and back and a
 *  little left and right, so a tall column stays compact and none hides another. */
export function columnCentres(
  columns: number[][],
  radii: ArrayLike<number>,
  centres: Float32Array,
  gapX = GAP_X,
  gapY = GAP_Y,
) {
  const maxR = columns.map(col => Math.max(...col.map(c => radii[c])))
  let x = 0
  const xs: number[] = []
  columns.forEach((_, t) => {
    if (t) x += maxR[t - 1] + maxR[t] + gapX
    xs.push(x)
  })
  columns.forEach((col, t) => {
    const stagger = col.length > 2
    let y = 0
    const ys: number[] = []
    col.forEach((c, k) => {
      if (k) y += (radii[col[k - 1]] + radii[c]) * (stagger ? 0.8 : 1) + gapY
      ys.push(y)
    })
    col.forEach((c, k) => {
      const zig = stagger ? (k % 2 ? 1 : -1) : 0
      centres[c * 3] = xs[t] - x / 2 + zig * maxR[t] * 0.3
      centres[c * 3 + 1] = y / 2 - ys[k]
      centres[c * 3 + 2] = zig * maxR[t] * 0.75
    })
  })
}

export function layout({ componentCount, component, edges, columns }: LayoutInput): LayoutResult {
  const n = component.length
  const C = Math.max(1, componentCount)
  const count = new Int32Array(C)
  for (let i = 0; i < n; i++) count[component[i]]++

  const radii = new Float32Array(C)
  for (let c = 0; c < C; c++) radii[c] = 9 + Math.cbrt(Math.max(1, count[c])) * 7.2

  // Centres on a flattened sphere, the largest components first so they get the
  // equator. Scaled with the codebase: 124 units suits a few hundred files.
  const order = [...Array(C).keys()].sort((a, b) => count[b] - count[a])
  const R = Math.max(70, Math.min(360, 124 * Math.sqrt(Math.max(n, 40) / 370)))
  const centres = new Float32Array(C * 3)
  if (columns?.length) columnCentres(columns, radii, centres)
  else
    order.forEach((c, k) => {
      const [x, y, z] = fib(k, C)
      centres[c * 3] = x * R
      centres[c * 3 + 1] = y * R * 0.62
      centres[c * 3 + 2] = z * R
    })

  // Seed: each component's files on a fibonacci ball round its centre.
  const pos = new Float32Array(n * 3)
  const seq = new Int32Array(C)
  for (let i = 0; i < n; i++) {
    const c = component[i]
    const k = seq[c]++
    const [x, y, z] = fib(k, count[c])
    const shell = (0.55 + 0.45 * (((k * 7) % 10) / 10)) * radii[c]
    pos[i * 3] = centres[c * 3] + x * shell
    pos[i * 3 + 1] = centres[c * 3 + 1] + y * shell
    pos[i * 3 + 2] = centres[c * 3 + 2] + z * shell
  }

  // Only edges inside a component pull; one between components would drag clusters
  // into each other and the grouping is the point of the map.
  const inner: number[] = []
  for (let e = 0; e < edges.length; e += 2) {
    const a = edges[e]
    const b = edges[e + 1]
    if (a !== b && component[a] === component[b]) inner.push(a, b)
  }

  const cell = MIN_GAP * 1.6
  const key = (x: number, y: number, z: number) =>
    `${Math.floor(x / cell)},${Math.floor(y / cell)},${Math.floor(z / cell)}`
  const delta = new Float32Array(n * 3)

  for (let it = 0; it < ITERATIONS; it++) {
    const cool = 1 - it / ITERATIONS
    delta.fill(0)

    for (let e = 0; e < inner.length; e += 2) {
      const a = inner[e] * 3
      const b = inner[e + 1] * 3
      const dx = pos[b] - pos[a]
      const dy = pos[b + 1] - pos[a + 1]
      const dz = pos[b + 2] - pos[a + 2]
      const d = Math.hypot(dx, dy, dz) || 1
      const f = ((d - MIN_GAP * 1.4) / d) * 0.035
      delta[a] += dx * f
      delta[a + 1] += dy * f
      delta[a + 2] += dz * f
      delta[b] -= dx * f
      delta[b + 1] -= dy * f
      delta[b + 2] -= dz * f
    }

    const grid = new Map<string, number[]>()
    for (let i = 0; i < n; i++) {
      const k = key(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2])
      const bucket = grid.get(k)
      if (bucket) bucket.push(i)
      else grid.set(k, [i])
    }
    for (let i = 0; i < n; i++) {
      const gx = Math.floor(pos[i * 3] / cell)
      const gy = Math.floor(pos[i * 3 + 1] / cell)
      const gz = Math.floor(pos[i * 3 + 2] / cell)
      for (let ox = -1; ox <= 1; ox++)
        for (let oy = -1; oy <= 1; oy++)
          for (let oz = -1; oz <= 1; oz++) {
            const bucket = grid.get(`${gx + ox},${gy + oy},${gz + oz}`)
            if (!bucket) continue
            for (const j of bucket) {
              if (j <= i) continue
              const dx = pos[j * 3] - pos[i * 3]
              const dy = pos[j * 3 + 1] - pos[i * 3 + 1]
              const dz = pos[j * 3 + 2] - pos[i * 3 + 2]
              const d = Math.hypot(dx, dy, dz) || 0.01
              if (d >= MIN_GAP) continue
              const push = ((MIN_GAP - d) / d) * 0.5
              delta[i * 3] -= dx * push
              delta[i * 3 + 1] -= dy * push
              delta[i * 3 + 2] -= dz * push
              delta[j * 3] += dx * push
              delta[j * 3 + 1] += dy * push
              delta[j * 3 + 2] += dz * push
            }
          }
    }

    for (let i = 0; i < n; i++) {
      const c = component[i]
      for (let a = 0; a < 3; a++) pos[i * 3 + a] += delta[i * 3 + a] * cool
      // Stay inside the component's ball.
      const dx = pos[i * 3] - centres[c * 3]
      const dy = pos[i * 3 + 1] - centres[c * 3 + 1]
      const dz = pos[i * 3 + 2] - centres[c * 3 + 2]
      const d = Math.hypot(dx, dy, dz)
      if (d > radii[c]) {
        const s = radii[c] / d
        pos[i * 3] = centres[c * 3] + dx * s
        pos[i * 3 + 1] = centres[c * 3 + 1] + dy * s
        pos[i * 3 + 2] = centres[c * 3 + 2] + dz * s
      }
    }
  }

  return { positions: pos, centres, radii }
}

/* ------------------------------------------------------------------ *
 * The cache. One knowledge base always lays out the same way, so the
 * result is kept per codebase and commit, in this browser only.
 * ------------------------------------------------------------------ */

const VERSION = 3

export function cacheKey(projectId: number, commit: string | null, nodes: number, edges: number) {
  return `codelith.atlas.layout.v${VERSION}:${projectId}:${commit ?? 'none'}:${nodes}:${edges}`
}

export function readCached(key: string, nodes: number, components: number): LayoutResult | null {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return null
    const { p, c, r } = JSON.parse(raw) as { p: number[]; c: number[]; r: number[] }
    if (p.length !== nodes * 3 || c.length !== components * 3) return null
    return { positions: Float32Array.from(p), centres: Float32Array.from(c), radii: Float32Array.from(r) }
  } catch {
    return null
  }
}

export function writeCached(key: string, result: LayoutResult) {
  const round = (a: Float32Array) => Array.from(a, v => Math.round(v * 10) / 10)
  try {
    // One layout per codebase: drop older commits' before writing this one.
    const prefix = key.split(':').slice(0, 2).join(':') + ':'
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const k = localStorage.key(i)
      if (k && k.startsWith(prefix) && k !== key) localStorage.removeItem(k)
    }
    localStorage.setItem(
      key,
      JSON.stringify({ p: round(result.positions), c: round(result.centres), r: round(result.radii) }),
    )
  } catch {
    /* storage full or blocked: the layout is recomputed next time */
  }
}
