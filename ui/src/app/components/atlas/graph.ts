import type { Atlas } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * The atlas's graph arithmetic, shared by the 3D scene and the inspector
 * so what is drawn and what is listed can never disagree.
 *
 * Edges arrive as [importer, imported]. "What breaks if this changes" walks
 * them backwards: from a file to the files that import it, then to the
 * files that import those. Three hops, the same depth the pre-flight uses,
 * because past three the answer is most of the repository.
 * ------------------------------------------------------------------ */

export const BLAST_DEPTH = 3

export interface Blast {
  /** Node index → hops from the selection. The selection itself is 0. */
  distance: Map<number, number>
  /** Node index → the node one hop nearer the selection on a shortest path. */
  parent: Map<number, number>
}

export interface Adjacency {
  /** Who imports each node. */
  dependants: number[][]
  /** What each node imports. */
  uses: number[][]
}

export function adjacency(atlas: Atlas): Adjacency {
  const n = atlas.nodes.length
  const dependants: number[][] = Array.from({ length: n }, () => [])
  const uses: number[][] = Array.from({ length: n }, () => [])
  for (const [a, b] of atlas.edges) {
    dependants[b].push(a)
    uses[a].push(b)
  }
  return { dependants, uses }
}

/** Breadth first, so each file's distance is its shortest and its parent lies on
 *  a shortest path: the tree drawn is the nearest route to every dependant. */
export function blast(adj: Adjacency, from: number, depth = BLAST_DEPTH): Blast {
  const distance = new Map<number, number>([[from, 0]])
  const parent = new Map<number, number>()
  const queue = [from]
  for (let head = 0; head < queue.length; head++) {
    const x = queue[head]
    const d = distance.get(x)!
    if (d >= depth) continue
    for (const s of adj.dependants[x]) {
      if (distance.has(s)) continue
      distance.set(s, d + 1)
      parent.set(s, x)
      queue.push(s)
    }
  }
  return { distance, parent }
}

/** The dependants, nearest first, then by path. */
export function reachList(atlas: Atlas, b: Blast, from: number): [number, number][] {
  return [...b.distance]
    .filter(([i]) => i !== from)
    .sort((x, y) => x[1] - y[1] || atlas.nodes[x[0]].path.localeCompare(atlas.nodes[y[0]].path))
}

/**
 * Where the atlas opens. A file whose blast radius can be read: eight to twenty-four
 * dependants, preferring the kinds a newcomer recognises. The most depended-on file
 * draws so many paths that nothing is legible, which is the opposite of an invitation.
 */
export function openingNode(atlas: Atlas, adj: Adjacency): number | null {
  const files = atlas.nodes.map((n, i) => [n, i] as const).filter(([n]) => !n.fact && n.loc > 0)
  if (!files.length) return atlas.nodes.length ? 0 : null
  const size = (i: number) => blast(adj, i).distance.size - 1
  for (const kinds of [['data', 'api', 'model'], ['service', 'util', 'config']]) {
    const hit = files.find(([n, i]) => kinds.includes(n.kind) && size(i) >= 8 && size(i) <= 24)
    if (hit) return hit[1]
  }
  let best = files[0][1]
  let bestSize = -1
  for (const [, i] of files) {
    const s = size(i)
    if (s > bestSize && s <= 40) {
      best = i
      bestSize = s
    }
  }
  return best
}

/** A file's last segment, which is what a label has room for. */
export function shortName(path: string): string {
  const parts = path.split('/')
  const last = parts.pop() || path
  // `__init__.py` and `index.ts` say nothing alone; their folder says what they are.
  return /^(__init__|index|mod|main)\.[a-z]+$/i.test(last) && parts.length
    ? `${parts.pop()}/${last}`
    : last
}
