import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../lib/api'
import { useAsync } from '../../lib/hooks'
import { Icon } from '../../lib/icons'
import type { FileChange } from '../../lib/types'
import { inputClass } from '../ui'
import { ErrorState, SkeletonPanel } from '../States'
import { Pill } from '../primitives'
import { DiffView } from './DiffView'
import { NEW_TAB } from '../layout/tabState'

/* ------------------------------------------------------------------ *
 * The files that changed between two readings, grouped by the part of
 * the codebase each is in, beside the selected one line by line.
 *
 * The header over a diff is the part GitHub cannot show: how much of the
 * code depends on the file, whether any test reaches it, and which
 * written pages cite it, from the later reading.
 * ------------------------------------------------------------------ */

const STATUS: Record<FileChange['status'], { letter: string; color: string; label: string }> = {
  added: { letter: 'A', color: 'var(--ok)', label: 'Added' },
  modified: { letter: 'M', color: 'var(--ink-mid)', label: 'Changed' },
  removed: { letter: 'D', color: 'var(--bad)', label: 'Removed' },
  renamed: { letter: 'R', color: 'var(--hot-ink)', label: 'Moved' },
}

const MODE_KEY = 'codelith.diff.mode'

function readMode(): 'split' | 'unified' {
  try {
    return localStorage.getItem(MODE_KEY) === 'unified' ? 'unified' : 'split'
  } catch {
    return 'split'
  }
}

function splitPath(path: string) {
  const cut = path.lastIndexOf('/')
  return cut < 0 ? { dir: '', name: path } : { dir: path.slice(0, cut + 1), name: path.slice(cut + 1) }
}

function Counts({ f }: { f: FileChange }) {
  if (f.large) return <span className="font-mono text-[11px] text-ink-dim">large</span>
  return (
    <span className="flex shrink-0 gap-1.5 font-mono text-[11px] tabular-nums">
      {f.added > 0 && <span className="text-ok">+{f.added}</span>}
      {f.removed > 0 && <span className="text-bad">-{f.removed}</span>}
    </span>
  )
}

function FileHeader({
  projectId,
  file,
  mode,
  onMode,
}: {
  projectId: number
  file: FileChange
  mode: 'split' | 'unified'
  onMode: (m: 'split' | 'unified') => void
}) {
  const s = STATUS[file.status]
  return (
    <header className="flex flex-col gap-2.5 border-b border-rule px-4 py-3">
      <div className="flex flex-wrap items-center gap-2.5">
        <span className="font-mono text-[12px] font-semibold" style={{ color: s.color }}>
          {s.label}
        </span>
        <h3 className="min-w-0 flex-1 font-mono text-[13px] font-semibold break-all text-ink">
          {file.old_path && file.old_path !== file.path && (
            <span className="font-normal text-ink-dim">
              {file.old_path} <Icon name="arrow-right" size={12} className="inline" />{' '}
            </span>
          )}
          {file.path}
        </h3>
        <Counts f={file} />
        <div className="flex gap-0.5 rounded-lg border border-rule bg-paper p-[3px]" role="tablist" aria-label="Diff layout">
          {(['split', 'unified'] as const).map(m => (
            <button
              key={m}
              type="button"
              role="tab"
              aria-selected={mode === m}
              onClick={() => onMode(m)}
              className={`rounded-md px-2.5 py-1 text-[12px] font-medium transition-colors ${
                mode === m ? 'bg-sunk text-ink shadow-[inset_0_0_0_1px_var(--line-2)]' : 'text-ink-mid hover:text-ink'
              }`}
            >
              {m === 'split' ? 'Side by side' : 'Unified'}
            </button>
          ))}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        {file.part && <Pill icon="boxes">{file.part}</Pill>}
        {file.status !== 'removed' && file.kind === null && (
          <>
            <Pill tone={file.reach >= 10 ? 'hot' : 'plain'} icon="git-fork" title="Files that import it, directly or through others">
              {file.reach ? `${file.reach} file${file.reach === 1 ? ' depends' : 's depend'} on it` : 'Nothing depends on it'}
            </Pill>
            <Pill tone={file.tests ? 'good' : file.reach ? 'warn' : 'plain'} icon="flask-conical">
              {file.tests ? `${file.tests} test${file.tests === 1 ? '' : 's'} reach it` : 'No test reaches it'}
            </Pill>
          </>
        )}
        {file.pages > 0 && (
          <Pill tone="warn" icon="file-text" title="Written pages that cite this file">
            Cited by {file.pages} page{file.pages === 1 ? '' : 's'}
          </Pill>
        )}
        {file.status !== 'removed' && (
          <Link
            to={`/app/projects/${projectId}/graph?file=${encodeURIComponent(file.path)}`}
            state={NEW_TAB}
            className="ml-auto flex items-center gap-1.5 text-[12px] text-ink-mid transition-colors hover:text-hot-ink"
          >
            <Icon name="network" size={13} /> Open in the graph
          </Link>
        )}
      </div>
    </header>
  )
}

function FileDiffPane({
  projectId,
  before,
  after,
  file,
}: {
  projectId: number
  before: number
  after: number
  file: FileChange
}) {
  const [mode, setMode] = useState(readMode)
  const diff = useAsync(
    sig => api.compareFile(projectId, file.path, { before, after, oldPath: file.old_path }, sig),
    [projectId, before, after, file.path, file.old_path],
  )
  const changeMode = (m: 'split' | 'unified') => {
    setMode(m)
    try {
      localStorage.setItem(MODE_KEY, m)
    } catch {
      /* remembered for this page only */
    }
  }
  return (
    <div className="flex min-w-0 flex-col overflow-hidden rounded-xl border border-rule bg-panel">
      <FileHeader projectId={projectId} file={file} mode={mode} onMode={changeMode} />
      {diff.loading ? (
        <div className="p-4">
          <SkeletonPanel rows={8} />
        </div>
      ) : diff.error ? (
        <div className="p-4">
          <ErrorState message={diff.error} onRetry={diff.reload} compact />
        </div>
      ) : diff.data ? (
        <>
          {diff.data.masked && (
            <p className="flex items-center gap-2 border-b border-rule px-4 py-2 text-[12.5px] text-ink-mid">
              <Icon name="key-round" size={13} className="text-warn" />
              An environment file: the names are compared, the values were never kept.
            </p>
          )}
          {!diff.data.whole && (
            <p className="border-b border-rule px-4 py-2 text-[12.5px] text-ink-mid">
              A long file: only the changes and three lines around each are shown.
            </p>
          )}
          {file.status === 'renamed' && file.similarity === 1 ? (
            <p className="px-4 py-6 text-center text-[13px] text-ink-mid">Moved without a change to its content.</p>
          ) : (
            <DiffView key={`${file.path}-${mode}`} rows={diff.data.rows} language={diff.data.language} mode={mode} />
          )}
        </>
      ) : null}
    </div>
  )
}

export function FilesChanged({
  projectId,
  before,
  after,
  files,
  selected,
  onSelect,
  filter,
  onFilter,
}: {
  projectId: number
  before: number
  after: number
  files: FileChange[]
  selected: string | null
  onSelect: (path: string) => void
  /** Kept by the page, so another tab can open the files under a path. */
  filter: string
  onFilter: (q: string) => void
}) {
  const [folded, setFolded] = useState<Set<string>>(new Set())

  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase()
    return q ? files.filter(f => f.path.toLowerCase().includes(q) || (f.part ?? '').toLowerCase().includes(q)) : files
  }, [files, filter])

  // Grouped by part, the parts with most lines changed first.
  const groups = useMemo(() => {
    const by = new Map<string, FileChange[]>()
    for (const f of shown) {
      const key = f.part ?? (f.status === 'removed' ? 'Removed' : 'Other')
      by.set(key, [...(by.get(key) ?? []), f])
    }
    const weight = (list: FileChange[]) => list.reduce((n, f) => n + f.added + f.removed, 0)
    return [...by.entries()].sort((a, b) => weight(b[1]) - weight(a[1]) || a[0].localeCompare(b[0]))
  }, [shown])

  const order = useMemo(() => groups.flatMap(([part, list]) => (folded.has(part) ? [] : list)), [groups, folded])
  const current = files.find(f => f.path === selected) ?? order[0] ?? null

  // A file opened by a link, or by j and k, is kept in sight in the list.
  useEffect(() => {
    document.querySelector('[data-changed-file][aria-current="true"]')?.scrollIntoView({ block: 'nearest' })
  }, [current?.path])

  // j and k step through the files, as they do in a review.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
      if (e.key !== 'j' && e.key !== 'k') return
      const at = current ? order.findIndex(f => f.path === current.path) : -1
      const next = order[e.key === 'j' ? at + 1 : at - 1]
      if (next) {
        e.preventDefault()
        onSelect(next.path)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [order, current, onSelect])

  if (!files.length)
    return <p className="rounded-xl border border-rule bg-panel px-4 py-6 text-center text-[13px] text-ink-mid">No file changed between these readings.</p>

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(240px,320px)_minmax(0,1fr)]">
      <aside className="flex min-w-0 flex-col gap-2 lg:sticky lg:top-3 lg:max-h-[calc(100vh-120px)] lg:self-start">
        <input
          className={inputClass}
          placeholder={`Filter ${files.length} files`}
          value={filter}
          onChange={e => onFilter(e.target.value)}
          aria-label="Filter the changed files"
        />
        <div className="min-h-0 overflow-y-auto rounded-xl border border-rule bg-panel py-1">
          {groups.map(([part, list]) => {
            const closed = folded.has(part)
            return (
              <div key={part}>
                <button
                  type="button"
                  onClick={() =>
                    setFolded(s => {
                      const next = new Set(s)
                      if (next.has(part)) next.delete(part)
                      else next.add(part)
                      return next
                    })
                  }
                  className="flex w-full items-center gap-1.5 px-3 pt-2.5 pb-1 text-left text-[11.5px] font-semibold tracking-wide text-ink-dim uppercase hover:text-ink"
                  aria-expanded={!closed}
                >
                  <Icon name={closed ? 'chevron-right' : 'chevron-down'} size={12} />
                  <span className="truncate">{part}</span>
                  <span className="ml-auto font-mono font-normal">{list.length}</span>
                </button>
                {!closed &&
                  list.map(f => {
                    const { dir, name } = splitPath(f.path)
                    const s = STATUS[f.status]
                    const on = current?.path === f.path
                    return (
                      <button
                        key={f.path}
                        type="button"
                        onClick={() => onSelect(f.path)}
                        aria-current={on}
                        data-changed-file
                        title={f.old_path ? `${f.old_path} → ${f.path}` : f.path}
                        className={`flex w-full items-center gap-2 px-3 py-1.5 text-left transition-colors ${
                          on ? 'bg-sunk shadow-[inset_2px_0_0_var(--hot)]' : 'hover:bg-hover'
                        }`}
                      >
                        <span className="w-3 shrink-0 font-mono text-[11px] font-bold" style={{ color: s.color }} aria-label={s.label}>
                          {s.letter}
                        </span>
                        <span className="flex min-w-0 flex-1 items-baseline" dir="rtl">
                          <bdi className="truncate font-mono text-[12px]">
                            <span className="text-ink-dim">{dir}</span>
                            <span className={on ? 'text-ink' : 'text-ink-mid'}>{name}</span>
                          </bdi>
                        </span>
                        <Counts f={f} />
                      </button>
                    )
                  })}
              </div>
            )
          })}
        </div>
        <p className="px-1 text-[11.5px] text-ink-dim">
          <kbd className="font-mono">j</kbd> and <kbd className="font-mono">k</kbd> step through the files.
        </p>
      </aside>
      {current && <FileDiffPane projectId={projectId} before={before} after={after} file={current} />}
    </div>
  )
}
