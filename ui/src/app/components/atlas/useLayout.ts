import { useEffect, useMemo, useState } from 'react'
import type { Atlas } from '../../lib/types'
import { cacheKey, layout, readCached, writeCached, type LayoutInput, type LayoutResult } from './layout'
import { componentTiers, tierColumns } from './model'

/** A short, stable fingerprint of the column order. */
function signature(columns: number[][]): string {
  let h = 5381
  for (const ch of columns.map(c => c.join(',')).join('|')) h = ((h << 5) + h + ch.charCodeAt(0)) | 0
  return (h >>> 0).toString(36)
}

/**
 * The atlas's layout: from this browser's cache when the same knowledge base was
 * drawn before, otherwise computed in a worker and then cached. Falls back to the
 * main thread where a module worker cannot start.
 */
export function useLayout(projectId: number, atlas: Atlas | undefined): LayoutResult | null {
  const [result, setResult] = useState<{ key: string; layout: LayoutResult } | null>(null)

  // The columns are part of the key: the same reading laid out in another order is
  // another layout.
  const columns = useMemo(() => (atlas ? tierColumns(atlas, componentTiers(atlas)).map(c => c.parts) : null), [atlas])
  const key =
    atlas && columns
      ? `${cacheKey(projectId, atlas.commit, atlas.nodes.length, atlas.edges.length)}:${signature(columns)}`
      : null

  useEffect(() => {
    if (!atlas || !key) return
    const cached = readCached(key, atlas.nodes.length, atlas.components.length)
    if (cached) {
      setResult({ key, layout: cached })
      return
    }

    const input: LayoutInput = {
      componentCount: atlas.components.length,
      component: Int32Array.from(atlas.nodes, n => n.component),
      edges: Int32Array.from(atlas.edges.flat()),
      columns: columns ?? undefined,
    }
    let live = true
    const done = (r: LayoutResult) => {
      if (!live) return
      writeCached(key, r)
      setResult({ key, layout: r })
    }

    let worker: Worker | null = null
    try {
      worker = new Worker(new URL('./layout.worker.ts', import.meta.url), { type: 'module' })
      worker.onmessage = (e: MessageEvent<LayoutResult>) => {
        done(e.data)
        worker?.terminate()
      }
      worker.onerror = () => {
        worker?.terminate()
        done(layout(input))
      }
      worker.postMessage(input)
    } catch {
      done(layout(input))
    }
    return () => {
      live = false
      worker?.terminate()
    }
  }, [atlas, key, columns])

  return result && result.key === key ? result.layout : null
}
