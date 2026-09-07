import { useEffect, useMemo, useState } from 'react'
import type { FileEntry } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * What was read, laid out the way it sits on disk.
 *
 * This used to be one flat group per directory, on the reasoning that
 * "a full expand/collapse tree is more machinery than a two-level
 * repository needs". The repositories are not two levels:
 * `controller/app/repositories` is four, and Codelith goes deeper. Every
 * row sat at the same indent under a grey header, so the shape of the
 * project — which is most of what a file list is for — had to be read
 * out of the paths one at a time.
 *
 * Single-child directory chains are drawn as one row, `app/db` rather
 * than `app` containing `db` containing nothing else. Python packages
 * are mostly such chains, and a level that only ever holds one thing is
 * a level that costs indentation and says nothing.
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

type FileNode = { kind: 'file'; name: string; path: string; file: FileEntry }
type DirNode = { kind: 'dir'; name: string; path: string; children: Node[] }
type Node = FileNode | DirNode

/** Indent per level. Enough to read as a step, small enough that a deep path still
 *  leaves room for the filename in a 250px column. */
const STEP = 11

function build(files: FileEntry[]): Node[] {
  const root: DirNode = { kind: 'dir', name: '', path: '', children: [] }

  for (const file of files) {
    const parts = file.path.split('/')
    const filename = parts.pop() as string
    let node = root
    for (const part of parts) {
      const path = node.path ? `${node.path}/${part}` : part
      let next = node.children.find(
        (c): c is DirNode => c.kind === 'dir' && c.name === part,
      )
      if (!next) {
        next = { kind: 'dir', name: part, path, children: [] }
        node.children.push(next)
      }
      node = next
    }
    node.children.push({ kind: 'file', name: filename, path: file.path, file })
  }

  // Directories first, then files, each alphabetically. `localeCompare` so `App.tsx`
  // and `app.tsx` land next to each other rather than in separate halves of the list.
  const sort = (node: DirNode): void => {
    node.children.sort((a, b) =>
      a.kind === b.kind ? a.name.localeCompare(b.name) : a.kind === 'dir' ? -1 : 1,
    )
    for (const child of node.children) if (child.kind === 'dir') sort(child)
  }
  sort(root)

  // `a` holding only `b` holding only `c` becomes one row reading `a/b/c`. Done after
  // sorting so the merged name is built from the order that will be drawn.
  const compact = (node: DirNode): DirNode => {
    let here = node
    while (here.children.length === 1 && here.children[0].kind === 'dir') {
      const only = here.children[0] as DirNode
      here = { ...only, name: `${here.name}/${only.name}` }
    }
    return { ...here, children: here.children.map(c => (c.kind === 'dir' ? compact(c) : c)) }
  }

  return root.children.map(c => (c.kind === 'dir' ? compact(c) : c))
}

/** Every directory path in the tree, for the initial expansion and "expand all". */
function directories(nodes: Node[], into: Set<string> = new Set()): Set<string> {
  for (const node of nodes) {
    if (node.kind === 'dir') {
      into.add(node.path)
      directories(node.children, into)
    }
  }
  return into
}

export default function FileTree({ files, current, onPick }: Props) {
  const [filter, setFilter] = useState('')
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())

  const matching = useMemo(() => {
    const needle = filter.trim().toLowerCase()
    return needle ? files.filter(f => f.path.toLowerCase().includes(needle)) : files
  }, [files, filter])

  const tree = useMemo(() => build(matching), [matching])

  // Whatever is being read stays reachable. Collapsing a directory the open file is
  // inside would hide the one row the reader is using to keep their place, so its
  // ancestors are dropped from the collapsed set rather than being made unclickable.
  useEffect(() => {
    if (!current) return
    setCollapsed(prev => {
      const next = new Set(prev)
      let cut = current.lastIndexOf('/')
      while (cut > 0) {
        next.delete(current.slice(0, cut))
        cut = current.lastIndexOf('/', cut - 1)
      }
      return next.size === prev.size ? prev : next
    })
  }, [current])

  // A filter is a search, and a search that hides its own results behind a closed
  // directory is not one. Everything opens while filtering and the reader's own
  // collapsed set is remembered for when they clear it.
  const searching = filter.trim().length > 0
  const isOpen = (path: string) => searching || !collapsed.has(path)

  const toggle = (path: string) =>
    setCollapsed(prev => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })

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

      <div className="flex items-center gap-2 border-b border-rule px-2 py-1">
        <button
          type="button"
          onClick={() => setCollapsed(new Set())}
          className="tag text-ink-dim hover:text-ink"
        >
          expand all
        </button>
        <button
          type="button"
          onClick={() => setCollapsed(directories(tree))}
          className="tag text-ink-dim hover:text-ink"
        >
          collapse all
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto py-1">
        {tree.map(node => (
          <Row
            key={node.path}
            node={node}
            depth={0}
            current={current}
            onPick={onPick}
            isOpen={isOpen}
            toggle={toggle}
          />
        ))}

        {matching.length === 0 && (
          <p className="p-3 font-sans text-[11.5px] text-ink-dim">
            Nothing matching &ldquo;{filter}&rdquo;.
          </p>
        )}
      </div>
    </div>
  )
}

function Row({
  node,
  depth,
  current,
  onPick,
  isOpen,
  toggle,
}: {
  node: Node
  depth: number
  current: string | null
  onPick: (path: string) => void
  isOpen: (path: string) => boolean
  toggle: (path: string) => void
}) {
  // One hairline per ancestor, so a filename thirty rows below its directory can
  // still be traced back to it. Drawn as a background on the row rather than as a
  // bordered wrapper per level: a wrapper indents the scrollbar too, and the guide
  // has to stop at the last row of a directory rather than running to the bottom of
  // the panel. The gradient starts at the same 6px the first row does and repeats on
  // the indent step, which puts each line exactly under its own level.
  const guides =
    depth === 0
      ? undefined
      : {
          backgroundImage:
            'repeating-linear-gradient(to right, var(--rule) 0 1px, transparent 1px ' +
            `${STEP}px)`,
          backgroundSize: `${depth * STEP}px 100%`,
          backgroundPosition: '6px 0',
          backgroundRepeat: 'no-repeat' as const,
        }
  const indent = { paddingLeft: 6 + depth * STEP, ...guides }

  if (node.kind === 'dir') {
    const open = isOpen(node.path)
    return (
      <>
        <button
          type="button"
          onClick={() => toggle(node.path)}
          title={node.path}
          style={indent}
          className="flex w-full items-center gap-1 py-[3px] pr-2 text-left font-mono text-[11px] text-ink-dim transition-colors hover:bg-sunk hover:text-ink"
        >
          <svg
            width="8"
            height="8"
            viewBox="0 0 8 8"
            className={`shrink-0 transition-transform ${open ? 'rotate-90' : ''}`}
            aria-hidden="true"
          >
            <path d="M2 0.5 L6.5 4 L2 7.5 Z" fill="currentColor" />
          </svg>
          <span className="min-w-0 flex-1 truncate">{node.name}</span>
        </button>
        {open &&
          node.children.map(child => (
            <Row
              key={child.path}
              node={child}
              depth={depth + 1}
              current={current}
              onPick={onPick}
              isOpen={isOpen}
              toggle={toggle}
            />
          ))}
      </>
    )
  }

  const on = node.path === current
  const file = node.file
  return (
    <button
      type="button"
      onClick={() => onPick(node.path)}
      title={node.path}
      // The extra inset lines a filename up with the directory name above it rather
      // than with that row's disclosure triangle.
      style={{ ...indent, paddingLeft: 6 + depth * STEP + 9 }}
      className={`flex w-full items-baseline gap-2 py-[3px] pr-2 text-left font-mono text-[11px] transition-colors ${
        on
          ? 'bg-hot-wash font-semibold text-hot-ink'
          : file.has_source
            ? 'text-ink-mid hover:bg-sunk hover:text-ink'
            : 'text-ink-dim hover:bg-sunk'
      }`}
    >
      <span className="min-w-0 flex-1 truncate">{node.name}</span>
      {file.has_source ? (
        file.symbols > 0 && (
          <span className="shrink-0 text-[9.5px] text-ink-dim">{file.symbols}</span>
        )
      ) : (
        <span className="shrink-0 text-[9.5px] text-ink-dim" title="Seen by analysis, no source kept">
          none
        </span>
      )}
    </button>
  )
}
