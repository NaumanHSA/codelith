import type { Architecture, Atlas } from '../../lib/types'
import type { Adjacency } from './graph'

/* ------------------------------------------------------------------ *
 * The knowledge graph seen a level up: components and how they connect,
 * and the paths a request takes through a file. Pure, shared by the 3D
 * map and the 2D flow panel so both say the same thing.
 *
 * Direction everywhere is the direction of a call: from the code that
 * imports to the code it imports. A request enters at an entry point or
 * a route and flows towards the data, which is how a reader expects to
 * read it, left to right.
 * ------------------------------------------------------------------ */

export interface ComponentInfo {
  index: number
  name: string
  description: string
  group: string
  /** Node indexes in this component. */
  members: number[]
  /** Kind → how many files of that kind. */
  kinds: Record<string, number>
  /** Its kinds, most common first. */
  dominant: string[]
}

export interface ComponentEdge {
  from: number
  to: number
  /** File imports from one component's files to the other's. */
  imports: number
  /** What the architecture pass said the relation is: calls, reads, feeds… */
  verb: string | null
}

export function componentInfo(atlas: Atlas): ComponentInfo[] {
  const out: ComponentInfo[] = atlas.components.map((c, index) => ({
    index,
    name: c.name,
    description: c.description,
    group: c.group,
    members: [],
    kinds: {},
    dominant: [],
  }))
  atlas.nodes.forEach((n, i) => {
    const c = out[n.component]
    if (!c) return
    c.members.push(i)
    c.kinds[n.kind] = (c.kinds[n.kind] ?? 0) + 1
  })
  for (const c of out) c.dominant = Object.entries(c.kinds).sort((a, b) => b[1] - a[1]).map(([k]) => k)
  return out
}

/** Component-to-component flows: the imports between their files, and the relations
 *  the architecture pass named (which also cover links imports cannot see, such as a
 *  web UI calling an API over HTTP). */
export function componentEdges(atlas: Atlas, arch?: Architecture | null): ComponentEdge[] {
  const key = (a: number, b: number) => `${a}>${b}`
  const map = new Map<string, ComponentEdge>()
  for (const [a, b] of atlas.edges) {
    const ca = atlas.nodes[a].component
    const cb = atlas.nodes[b].component
    if (ca === cb) continue
    const k = key(ca, cb)
    const e = map.get(k) ?? { from: ca, to: cb, imports: 0, verb: null }
    e.imports++
    map.set(k, e)
  }
  if (arch?.available) {
    const byName = new Map(atlas.components.map((c, i) => [c.name.toLowerCase(), i]))
    for (const r of arch.relations) {
      const a = byName.get(r.source.toLowerCase())
      const b = byName.get(r.target.toLowerCase())
      if (a === undefined || b === undefined || a === b) continue
      const k = key(a, b)
      const e = map.get(k) ?? { from: a, to: b, imports: 0, verb: null }
      e.verb = r.kind || e.verb
      map.set(k, e)
    }
  }
  return [...map.values()]
}

const ENTRY_KINDS = new Set(['entry', 'api', 'cli'])
const DATA_KINDS = new Set(['store', 'external', 'data'])

/** The nearest node of the wanted kinds, walking `next` breadth first; the path to it,
 *  start excluded. Empty when none is reachable. */
function nearest(start: number, next: number[][], wanted: Set<string>, atlas: Atlas, limit = 8): number[] {
  const parent = new Map<number, number>([[start, -1]])
  const queue = [start]
  for (let head = 0; head < queue.length; head++) {
    const x = queue[head]
    if (x !== start && wanted.has(atlas.nodes[x].kind)) {
      const path: number[] = []
      for (let at = x; at !== start; at = parent.get(at)!) path.unshift(at)
      return path
    }
    if (pathLength(parent, x) >= limit) continue
    for (const y of next[x]) {
      if (parent.has(y)) continue
      parent.set(y, x)
      queue.push(y)
    }
  }
  return []
}

function pathLength(parent: Map<number, number>, x: number) {
  let n = 0
  for (let at = x; parent.get(at)! >= 0; at = parent.get(at)!) n++
  return n
}

export interface RequestPath {
  /** From the nearest entry point, route or command down to (not including) the file. */
  upstream: number[]
  /** From the file down to the nearest data access, datastore or outside service. */
  downstream: number[]
}

/** How a request reaches this file and where it goes after: the shortest way in from
 *  something that receives requests, and the shortest way out to the data. */
export function requestPath(atlas: Atlas, adj: Adjacency, file: number): RequestPath {
  const fromEntry = ENTRY_KINDS.has(atlas.nodes[file].kind) ? [] : nearest(file, adj.dependants, ENTRY_KINDS, atlas)
  return {
    upstream: [...fromEntry].reverse(),
    downstream: DATA_KINDS.has(atlas.nodes[file].kind) && atlas.nodes[file].fact ? [] : nearest(file, adj.uses, DATA_KINDS, atlas),
  }
}

/* ------------------------------------------------------------------ *
 * Tiers: the parts of a codebase in the order a request meets them, so
 * the map and the diagram both read left to right the same way.
 *
 * Decided from what analysis already stored, never from a language's file
 * names: the kinds of file a part is made of, and which way the imports
 * between parts mostly run. A part that is mostly imported is leant on;
 * one that mostly imports does the leaning.
 * ------------------------------------------------------------------ */

export const TIERS = [
  { name: 'Where work comes in', hint: 'Entry points, commands, routes, screens and the tests that drive them' },
  { name: 'Core logic', hint: 'The parts that call more than they are called' },
  { name: 'Shared helpers', hint: 'The parts the rest leans on' },
  { name: 'Data and outside services', hint: 'Where it stores things and what it calls beyond the codebase' },
] as const

const TIER_ENTRY = new Set(['entry', 'cli', 'api', 'ui'])
const TIER_DATA = new Set(['data', 'store', 'external'])

/** Each component's tier, an index into `TIERS`; -1 for a component with no files.
 *  The server decides them (`knowledge/shape.py`) so a review of a change checks it
 *  against the same columns the map draws; this copy is for an older server. */
export function componentTiers(atlas: Atlas): Int32Array {
  if (atlas.tiers && atlas.tiers.length === atlas.components.length) return Int32Array.from(atlas.tiers)
  const info = componentInfo(atlas)
  const edges = componentEdges(atlas)
  const inn = new Float64Array(info.length)
  const out = new Float64Array(info.length)
  for (const e of edges) {
    out[e.from] += e.imports
    inn[e.to] += e.imports
  }
  const tiers = new Int32Array(info.length).fill(-1)
  for (const c of info) {
    const n = c.members.length
    if (!n) continue
    const share = (set: Set<string>) => Object.entries(c.kinds).reduce((s, [k, v]) => s + (set.has(k) ? v : 0), 0) / n
    const tests = (c.kinds.test ?? 0) / n
    const i = c.index
    if (c.group === 'outside' || share(TIER_DATA) >= 0.5) tiers[i] = 3
    else if (c.group === 'config' || c.group === 'setup') tiers[i] = 2
    else if (share(TIER_ENTRY) >= 0.3 || tests >= 0.5 || (inn[i] === 0 && out[i] > 0)) tiers[i] = 0
    else tiers[i] = (out[i] - inn[i]) / (out[i] + inn[i] + 1) >= 0 ? 1 : 2
  }
  return tiers
}

/** The tiers that have parts, each with its parts ordered to keep links from crossing:
 *  by the mean row of the parts they are linked to in the columns before. */
export function tierColumns(atlas: Atlas, tiers: Int32Array): { tier: number; parts: number[] }[] {
  const info = componentInfo(atlas)
  const weight = new Map<string, number>()
  for (const e of componentEdges(atlas)) {
    const k = e.from < e.to ? `${e.from}:${e.to}` : `${e.to}:${e.from}`
    weight.set(k, (weight.get(k) ?? 0) + e.imports)
  }
  const w = (a: number, b: number) => weight.get(a < b ? `${a}:${b}` : `${b}:${a}`) ?? 0

  const cols: { tier: number; parts: number[] }[] = []
  for (let t = 0; t < TIERS.length; t++) {
    const parts = info.filter(c => tiers[c.index] === t).map(c => c.index)
    if (parts.length) cols.push({ tier: t, parts })
  }
  const row = new Map<number, number>()
  cols.forEach((col, k) => {
    // The first column leads with what receives work; the tests that drive it go last.
    const tests = (c: number) => Number((info[c].kinds.test ?? 0) * 2 >= info[c].members.length)
    if (k === 0) col.parts.sort((a, b) => tests(a) - tests(b) || info[b].members.length - info[a].members.length)
    else {
      const key = (c: number) => {
        let sum = 0
        let total = 0
        for (const [p, r] of row) {
          const x = w(c, p)
          sum += x * r
          total += x
        }
        return total ? sum / total : Number.MAX_SAFE_INTEGER
      }
      const keys = new Map(col.parts.map(c => [c, key(c)]))
      col.parts.sort((a, b) => keys.get(a)! - keys.get(b)! || info[b].members.length - info[a].members.length)
    }
    // Rows are fractions of the column, so a tall column and a short one compare.
    col.parts.forEach((c, r) => row.set(c, col.parts.length > 1 ? r / (col.parts.length - 1) : 0.5))
  })
  return cols
}
