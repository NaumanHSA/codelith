import { useEffect, useRef, useState } from 'react'
import type { Project } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * Which codebase the questions are about.
 *
 * A native `<select>` was the wrong control for this. It showed one
 * name and gave no way to tell two analysed repositories apart until
 * after picking one — and picking is the decision that determines what
 * every answer on this page will be grounded in. A list you can read
 * before choosing is worth the extra component.
 *
 * Rows carry what the projects list already knows: whether it has been
 * analysed, how much has been written about it, and where it came from.
 * None of that needs a request per repository, which a richer subtitle
 * would.
 * ------------------------------------------------------------------ */

function Row({
  project,
  selected,
  onPick,
}: {
  project: Project
  selected: boolean
  onPick: () => void
}) {
  const stale = project.kb_status === 'stale'
  const analysed = project.apps_ready
  const source = project.sources?.[0]?.url_or_path ?? ''

  return (
    <li>
      <button
        type="button"
        onClick={onPick}
        className={`flex w-full items-start gap-2.5 border-b border-rule px-3 py-2.5 text-left transition-colors last:border-b-0 ${
          selected ? 'bg-hot-wash' : 'hover:bg-sunk'
        }`}
      >
        <span
          className={`mt-[5px] block size-[7px] shrink-0 rotate-45 ${
            selected ? 'bg-hot' : analysed ? 'bg-ok' : 'bg-rule'
          }`}
        />
        <span className="min-w-0 flex-1">
          <span
            className={`block truncate text-[12.5px] font-semibold ${
              selected ? 'text-hot-ink' : 'text-ink'
            }`}
          >
            {project.name}
          </span>
          <span className="mt-0.5 flex flex-wrap items-baseline gap-x-2 text-[10.5px] text-ink-dim">
            {/* Whether it can answer at all comes first: an unanalysed repository
                is not a slower choice, it is one with nothing to say. */}
            <span className={stale ? 'text-warn' : analysed ? 'text-ok' : 'text-ink-dim'}>
              {stale ? 'reading is stale' : analysed ? 'analysed' : 'not analysed yet'}
            </span>
            {!!project.stats?.page_count && <span>{project.stats.page_count} pages</span>}
            {project.description ? (
              <span className="truncate">{project.description}</span>
            ) : (
              source && <span className="truncate font-mono">{source}</span>
            )}
          </span>
        </span>
      </button>
    </li>
  )
}

export default function RepositoryPicker({
  projects,
  selectedId,
  onSelect,
}: {
  projects: Project[]
  selectedId: number | null
  onSelect: (id: number) => void
}) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const selected = projects.find(p => p.id === selectedId) ?? null

  // Close on a click elsewhere or on Escape. A popover that can only be dismissed
  // by choosing something is a popover that has taken the page hostage.
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const only = projects.length <= 1

  return (
    <div ref={box} className="relative w-full">
      <span className="tag mb-1.5 block text-ink-dim">Repository</span>

      <button
        type="button"
        disabled={only}
        onClick={() => setOpen(o => !o)}
        className={`flex w-full items-center gap-3 border bg-panel px-3 py-2.5 text-left transition-colors ${
          open ? 'border-hot' : 'border-rule'
        } ${only ? 'cursor-default' : 'hover:border-ink'}`}
      >
        <span className="block size-2 shrink-0 rotate-45 bg-hot" />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[14px] font-semibold text-ink">
            {selected?.name ?? 'No codebase selected'}
          </span>
          {selected && (
            <span className="mt-0.5 block truncate font-mono text-[10.5px] text-ink-dim">
              {selected.sources?.[0]?.url_or_path ?? selected.slug}
            </span>
          )}
        </span>
        {/* One repository is a fact, not a choice — the caret would promise a list
            with nothing else in it. */}
        {!only && (
          <span className="tag shrink-0 text-ink-dim">
            {open ? 'close ▲' : `change ▾`}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute top-full right-0 left-0 z-40 mt-1 max-h-[320px] overflow-y-auto border border-ink bg-panel shadow-[4px_4px_0_0_var(--ink)]">
          <ul>
            {projects.map(p => (
              <Row
                key={p.id}
                project={p}
                selected={p.id === selectedId}
                onPick={() => {
                  onSelect(p.id)
                  setOpen(false)
                }}
              />
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
