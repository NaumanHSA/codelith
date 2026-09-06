import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../lib/api'
import { useAsync } from '../../lib/hooks'
import { ErrorState, SkeletonPanel } from '../States'
import CodeView from './CodeView'

/* ------------------------------------------------------------------ *
 * A file, read without leaving what you were reading.
 *
 * Following a reference out of the graph used to be a one-way trip:
 * the code page is a different route, so coming back meant rebuilding
 * the graph from the project down, and everything you had opened was
 * gone. A graph you cannot afford to leave is a graph you stop using.
 *
 * So the source arrives over the top instead. The graph keeps its state
 * and stays visible down the left, and the panel says where the file
 * came from - which module, which role - because the answer to "what am
 * I looking at" is exactly what the graph was showing a moment ago.
 * ------------------------------------------------------------------ */

export default function SourcePeek({
  projectId,
  path,
  line,
  origin,
  onClose,
}: {
  projectId: number
  path: string
  /** The line a symbol row asked for, if it was a symbol that opened this. */
  line?: number
  /** Where in the graph this came from, e.g. "src.dom · service". */
  origin?: string
  onClose: () => void
}) {
  const file = useAsync(sig => api.file(projectId, path, sig), [projectId, path])

  // Escape closes it. A panel that covers most of the screen and can only be
  // dismissed by finding a small button is a trap.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const name = path.split('/').pop() ?? path
  const range: [number, number] | null = line ? [line, line] : null

  return (
    <aside
      className="fixed inset-y-0 right-0 z-40 flex w-full flex-col border-l border-rule bg-panel shadow-[-6px_0_24px_rgba(20,18,15,0.14)] sm:w-[min(820px,62vw)]"
      role="dialog"
      aria-label={`Source of ${path}`}
    >
      <header className="flex items-start gap-3 border-b border-rule bg-sunk/50 px-3 py-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <span className="font-mono text-[12.5px] font-semibold text-ink">{name}</span>
            {file.data?.language && (
              <span className="tag text-ink-dim">{file.data.language}</span>
            )}
          </div>
          <p className="mt-0.5 break-all font-mono text-[10.5px] text-ink-dim">{path}</p>
          {origin && (
            <p className="mt-0.5 font-sans text-[10.5px] text-ink-dim">
              from <span className="text-hot-ink">{origin}</span>
            </p>
          )}
        </div>

        {/* The full page still exists and is still the addressable one, so the
            way to it stays. This panel is the shortcut, not the replacement. */}
        <Link
          to={`/app/projects/${projectId}/code?file=${encodeURIComponent(path)}${
            line ? `#L${line}` : ''
          }`}
          className="tag shrink-0 text-hot-ink hover:underline"
        >
          open full page ↗
        </Link>
        <button
          type="button"
          onClick={onClose}
          title="Close (Esc)"
          className="shrink-0 border border-rule px-1.5 text-[13px] leading-5 text-ink-dim hover:border-hot hover:text-hot-ink"
        >
          ×
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-hidden">
        {file.loading && <SkeletonPanel rows={12} />}
        {file.error && <ErrorState message={file.error} />}
        {file.data && (
          // The same viewer the full page uses, so the gaps are named here too
          // and a reader is not shown a tidier version of the truth.
          <CodeView file={file.data} range={range} onPickLine={() => {}} fill />
        )}
      </div>
    </aside>
  )
}
