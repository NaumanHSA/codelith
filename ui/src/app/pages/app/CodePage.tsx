import { useCallback, useEffect, useMemo } from 'react'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../../lib/api'
import { useAsync } from '../../lib/hooks'
import { EmptyState, ErrorState, SkeletonPanel } from '../../components/States'
import { PageHead, Panel } from '../../components/ui'
import FileTree from '../../components/projects/FileTree'
import CodeView from '../../components/projects/CodeView'
import type { SymbolEntry } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * The code the knowledge base kept.
 *
 * Everything else in the studio talks *about* the repository. This is
 * the only page that shows it, which is why it exists: a product whose
 * claim is that it read your code and never shows you a line of it is
 * asking to be taken on faith.
 *
 * Addressable on purpose. `?file=src/x.js#L12-L30` is the shape a
 * citation needs, so an answer from Ask or a page on a published site
 * can point at the lines it was drawn from rather than naming them and
 * hoping.
 * ------------------------------------------------------------------ */

/** `#L12` or `#L12-L30`. Anything else is not a range and is ignored. */
function parseRange(hash: string): [number, number] | null {
  const match = /^#L(\d+)(?:-L?(\d+))?$/.exec(hash)
  if (!match) return null
  const from = Number(match[1])
  const to = match[2] ? Number(match[2]) : from
  if (!from) return null
  // Backwards is a typo, not an empty selection.
  return from <= to ? [from, to] : [to, from]
}

const KIND_TONE: Record<string, string> = {
  function: 'text-hot-ink',
  method: 'text-hot-ink',
  class: 'text-ink',
  interface: 'text-ink',
  variable: 'text-ink-mid',
  constant: 'text-ink-mid',
}

export default function CodePage() {
  const { projectId } = useParams()
  const id = Number(projectId)
  const [params, setParams] = useSearchParams()
  const location = useLocation()
  const navigate = useNavigate()

  const path = params.get('file')
  const range = useMemo(() => parseRange(location.hash), [location.hash])

  const project = useAsync(() => api.project(id), [id])
  const tree = useAsync(sig => api.files(id, sig), [id])
  const file = useAsync(
    sig => (path ? api.file(id, path, sig) : Promise.resolve(null)),
    [id, path],
  )

  // Opening the page with no file chosen should not be an empty pane. The first
  // file with source in it is a better guess than nothing, and it is one the reader
  // immediately replaces.
  useEffect(() => {
    if (!path && tree.data?.files.length) {
      const first = tree.data.files.find(f => f.has_source)
      if (first) setParams({ file: first.path }, { replace: true })
    }
  }, [path, tree.data, setParams])

  const pick = useCallback(
    (next: string) => {
      // The hash goes with the old file. Keeping it would land the reader on a line
      // number that means nothing in the new one.
      navigate(`?file=${encodeURIComponent(next)}`, { replace: false })
    },
    [navigate],
  )

  const pickLine = useCallback(
    (line: number, extend: boolean) => {
      const next =
        extend && range
          ? `#L${Math.min(range[0], line)}-L${Math.max(range[0], line)}`
          : `#L${line}`
      navigate(`${location.pathname}${location.search}${next}`, { replace: true })
    },
    [navigate, location.pathname, location.search, range],
  )

  if (!Number.isFinite(id)) return <ErrorState message="Not a project." />

  return (
    <div className="space-y-3">
      <PageHead
        index="04"
        title="Source"
        sub={
          project.data ? (
            <>
              <Link to={`/app/projects/${id}`} className="text-hot-ink hover:underline">
                {project.data.name}
              </Link>
              {tree.data?.available && (
                <>
                  {' · '}
                  {tree.data.files.length} files
                  {tree.data.total_loc > 0 && `, ${tree.data.total_loc.toLocaleString()} lines`}
                  {tree.data.without_source > 0 && (
                    <span className="text-ink-dim">
                      {' · '}
                      {tree.data.without_source} with no source kept
                    </span>
                  )}
                </>
              )}
            </>
          ) : null
        }
      />

      {tree.loading && <SkeletonPanel rows={8} />}
      {tree.error && <ErrorState message={tree.error} />}

      {tree.data && !tree.data.available && (
        <EmptyState
          title="Nothing read yet"
          body="Analyse this codebase and its files will be readable here."
          action={
            <Link to={`/app/projects/${id}`} className="text-hot-ink hover:underline">
              Back to the codebase
            </Link>
          }
        />
      )}

      {tree.data?.available && (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-[260px_1fr_210px]">
          <Panel
            title="Files"
            className="max-h-[74vh]"
            bodyClass="h-[calc(74vh-33px)]"
          >
            <FileTree files={tree.data.files} current={path} onPick={pick} />
          </Panel>

          {/* min-w-0: a 1fr track will not shrink below its content, so without
              it the code column pushes the outline off the right of the page the
              first time a file has a long line in it. */}
          <Panel
            className="min-w-0"
            title={
              <span className="font-mono text-[11.5px]">{path ?? 'no file selected'}</span>
            }
            action={
              file.data?.language ? (
                <span className="tag text-ink-dim">{file.data.language}</span>
              ) : null
            }
          >
            {file.loading && <SkeletonPanel rows={10} />}
            {file.error && <ErrorState message={file.error} />}
            {file.data && (
              <CodeView file={file.data} range={range} onPickLine={pickLine} />
            )}
            {!path && !file.loading && (
              <p className="p-4 font-sans text-[12px] text-ink-dim">
                Pick a file on the left.
              </p>
            )}
          </Panel>

          <Panel
            title="In this file"
            action={
              file.data?.symbols.length ? (
                <span className="tag text-ink-dim">{file.data.symbols.length}</span>
              ) : null
            }
            className="max-h-[74vh]"
            bodyClass="max-h-[calc(74vh-33px)] overflow-y-auto"
          >
            <Outline symbols={file.data?.symbols ?? []} active={range} onPick={pickLine} />
          </Panel>
        </div>
      )}
    </div>
  )
}

/**
 * The symbols the parser found, in the order they appear.
 *
 * From `graph_symbols`, which records where a declaration starts and sometimes
 * where it ends. Clicking one links to its line, so the outline and the deep link
 * are the same mechanism rather than two.
 */
function Outline({
  symbols,
  active,
  onPick,
}: {
  symbols: SymbolEntry[]
  active: [number, number] | null
  onPick: (line: number, extend: boolean) => void
}) {
  if (!symbols.length) {
    return (
      <p className="p-3 font-sans text-[11.5px] leading-relaxed text-ink-dim">
        No symbols recorded for this file. Analysis parses the languages it has a
        provider for; everything else is indexed as text.
      </p>
    )
  }

  return (
    <ul>
      {symbols.map(symbol => {
        const on = !!active && symbol.line >= active[0] && symbol.line <= active[1]
        return (
          <li key={`${symbol.qname}:${symbol.line}`}>
            <button
              type="button"
              onClick={() => onPick(symbol.line, false)}
              className={`flex w-full items-baseline gap-2 border-b border-rule px-2.5 py-[5px] text-left last:border-b-0 ${
                on ? 'bg-hot-wash' : 'hover:bg-sunk'
              }`}
            >
              <span
                className={`min-w-0 flex-1 truncate font-mono text-[11px] ${
                  KIND_TONE[symbol.kind] ?? 'text-ink-mid'
                }`}
                title={`${symbol.qname || symbol.name} · ${symbol.kind}`}
              >
                {symbol.name}
              </span>
              <span className="shrink-0 font-mono text-[9.5px] tabular-nums text-ink-dim">
                {symbol.line}
              </span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}
