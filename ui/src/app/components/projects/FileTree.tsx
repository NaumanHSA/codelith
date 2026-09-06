import { useMemo, useState } from 'react'
import type { FileEntry } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * What was read, grouped the way it sits on disk.
 *
 * Flat is wrong past about twenty files and a full expand/collapse tree
 * is more machinery than a two-level repository needs. So: one group
 * per directory, sorted, with the root's own files first. Forty-four
 * files here, sixteen on the other project.
 *
 * A file with nothing stored behind it is still listed, greyed and
 * marked. Dropping it would be the more comfortable choice and the
 * dishonest one: a reader who cannot find `README.md` in the tree
 * concludes it was never in the repository, rather than that analysis
 * kept nothing of it.
 * ------------------------------------------------------------------ */

type Props = {
  files: FileEntry[]
  current: string | null
  onPick: (path: string) => void
}

function directoryOf(path: string): string {
  const cut = path.lastIndexOf('/')
  return cut === -1 ? '' : path.slice(0, cut)
}

export default function FileTree({ files, current, onPick }: Props) {
  const [filter, setFilter] = useState('')

  const groups = useMemo(() => {
    const needle = filter.trim().toLowerCase()
    const matching = needle
      ? files.filter(f => f.path.toLowerCase().includes(needle))
      : files
    const byDir = new Map<string, FileEntry[]>()
    for (const file of matching) {
      const dir = directoryOf(file.path)
      byDir.set(dir, [...(byDir.get(dir) ?? []), file])
    }
    // The root sorts first, then the rest alphabetically. `''` already sorts before
    // everything, but relying on that would break the day a directory is named with
    // a leading character below `/`.
    return [...byDir.entries()].sort(([a], [b]) =>
      a === '' ? -1 : b === '' ? 1 : a.localeCompare(b),
    )
  }, [files, filter])

  const shown = groups.reduce((n, [, entries]) => n + entries.length, 0)

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-rule p-2">
        <input
          value={filter}
          onChange={e => setFilter(e.target.value)}
          placeholder="filter files"
          className="w-full border border-rule bg-panel px-2 py-1 font-mono text-[11px] text-ink placeholder:text-ink-dim focus:border-hot focus:outline-none"
        />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {groups.map(([dir, entries]) => (
          <div key={dir || '/'}>
            <div className="sticky top-0 z-10 truncate border-b border-rule bg-sunk px-2 py-[3px] font-mono text-[10px] tracking-wide text-ink-dim">
              {dir || './'}
            </div>
            <ul>
              {entries.map(file => {
                const on = file.path === current
                return (
                  <li key={file.path}>
                    <button
                      type="button"
                      onClick={() => onPick(file.path)}
                      title={file.path}
                      className={`flex w-full items-baseline gap-2 px-2 py-[3px] text-left font-mono text-[11px] transition-colors ${
                        on
                          ? 'bg-hot-wash font-semibold text-hot-ink'
                          : file.has_source
                            ? 'text-ink-mid hover:bg-sunk hover:text-ink'
                            : 'text-ink-dim hover:bg-sunk'
                      }`}
                    >
                      <span className="min-w-0 flex-1 truncate">
                        {file.path.slice(dir ? dir.length + 1 : 0)}
                      </span>
                      {file.has_source ? (
                        file.symbols > 0 && (
                          <span className="shrink-0 text-[9.5px] text-ink-dim">
                            {file.symbols}
                          </span>
                        )
                      ) : (
                        <span
                          className="shrink-0 text-[9.5px] text-ink-dim"
                          title="Seen by analysis, no source kept"
                        >
                          none
                        </span>
                      )}
                    </button>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}

        {shown === 0 && (
          <p className="p-3 font-sans text-[11.5px] text-ink-dim">
            Nothing matching &ldquo;{filter}&rdquo;.
          </p>
        )}
      </div>
    </div>
  )
}
