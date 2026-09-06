import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import type { ModuleEntry, Modules } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * The modules, with what was written about each of them.
 *
 * This replaces a radar of role counts. The radar plotted five numbers
 * and looked like understanding; underneath it sat twenty modules with
 * a paragraph each, every paragraph the output of a call nobody has
 * ever read the result of.
 *
 * A row therefore leads with the prose, not the metrics. Size, role and
 * language are how you find the row; the sentence is why you came.
 *
 * And a module opens. Its files are stored with it, so each one is a
 * link into the source viewer, which is the difference between "we
 * understood this" and "here is what we understood it from".
 * ------------------------------------------------------------------ */

type Sort = 'size' | 'name' | 'files'

const ROLE_TONE: Record<string, string> = {
  api: 'border-hot-edge bg-hot-wash text-hot-ink',
  service: 'border-rule text-ink-mid',
  utility: 'border-rule text-ink-dim',
  config: 'border-rule text-ink-dim',
  cli: 'border-rule text-warn',
  test: 'border-rule text-ok',
  schema: 'border-rule text-ink-mid',
}

export default function ModuleExplorer({
  data,
  projectId,
}: {
  data: Modules
  projectId: number
}) {
  const [role, setRole] = useState<string>('')
  const [language, setLanguage] = useState<string>('')
  const [sort, setSort] = useState<Sort>('size')
  const [open, setOpen] = useState<string | null>(null)

  const roles = useMemo(
    () => [...new Set(data.modules.map(m => m.role).filter(Boolean))].sort(),
    [data],
  )
  const languages = useMemo(
    () => [...new Set(data.modules.map(m => m.language).filter(Boolean))].sort(),
    [data],
  )

  const rows = useMemo(() => {
    const filtered = data.modules.filter(
      m => (!role || m.role === role) && (!language || m.language === language),
    )
    const sorted = [...filtered]
    if (sort === 'name') sorted.sort((a, b) => a.name.localeCompare(b.name))
    else if (sort === 'files') sorted.sort((a, b) => b.file_count - a.file_count || b.loc - a.loc)
    // 'size' is the order the API already returns, so it needs no sort at all.
    return sorted
  }, [data, role, language, sort])

  const shownLoc = rows.reduce((n, m) => n + m.loc, 0)

  return (
    <div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-rule bg-sunk/40 px-3 py-2">
        <Chips label="role" values={roles} current={role} onPick={setRole} />
        {languages.length > 1 && (
          <Chips label="language" values={languages} current={language} onPick={setLanguage} />
        )}
        <div className="ml-auto flex items-center gap-1.5">
          <span className="tag text-ink-dim">sort</span>
          {(['size', 'files', 'name'] as Sort[]).map(option => (
            <button
              key={option}
              type="button"
              onClick={() => setSort(option)}
              className={`tag px-1.5 py-[2px] ${
                sort === option ? 'text-hot-ink underline' : 'text-ink-dim hover:text-ink'
              }`}
            >
              {option}
            </button>
          ))}
        </div>
      </div>

      <ul>
        {rows.map(module => (
          <Row
            key={module.path}
            module={module}
            projectId={projectId}
            open={open === module.path}
            onToggle={() => setOpen(open === module.path ? null : module.path)}
          />
        ))}
      </ul>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-rule bg-sunk/40 px-3 py-1.5">
        <span className="tag text-ink-dim">
          {rows.length} of {data.modules.length} module
          {data.modules.length === 1 ? '' : 's'}
          {shownLoc > 0 && `, ${shownLoc.toLocaleString()} lines`}
        </span>
        {data.without_summary > 0 && (
          <span className="tag text-warn">
            {data.without_summary} never summarised
          </span>
        )}
        {rows.length === 0 && (
          <span className="tag text-ink-dim">nothing matches that filter</span>
        )}
      </div>
    </div>
  )
}

function Chips({
  label,
  values,
  current,
  onPick,
}: {
  label: string
  values: string[]
  current: string
  onPick: (value: string) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-1">
      <span className="tag text-ink-dim">{label}</span>
      <button
        type="button"
        onClick={() => onPick('')}
        className={`tag px-1.5 py-[2px] ${
          current ? 'text-ink-dim hover:text-ink' : 'text-hot-ink underline'
        }`}
      >
        all
      </button>
      {values.map(value => (
        <button
          key={value}
          type="button"
          onClick={() => onPick(current === value ? '' : value)}
          className={`tag px-1.5 py-[2px] ${
            current === value ? 'text-hot-ink underline' : 'text-ink-dim hover:text-ink'
          }`}
        >
          {value}
        </button>
      ))}
    </div>
  )
}

function Row({
  module,
  projectId,
  open,
  onToggle,
}: {
  module: ModuleEntry
  projectId: number
  open: boolean
  onToggle: () => void
}) {
  return (
    <li className="border-b border-rule last:border-b-0">
      <button
        type="button"
        onClick={onToggle}
        className="w-full px-3 py-2 text-left transition-colors hover:bg-sunk/50"
      >
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <span className="font-mono text-[12px] font-semibold text-ink">{module.name}</span>
          {module.role && (
            <span
              className={`tag border px-1.5 py-[1px] ${
                ROLE_TONE[module.role] ?? 'border-rule text-ink-mid'
              }`}
            >
              {module.role}
            </span>
          )}
          {module.language && <span className="tag text-ink-dim">{module.language}</span>}
          <span className="ml-auto flex shrink-0 items-baseline gap-2">
            <span className="tag tabular-nums text-ink-dim">
              {module.file_count} file{module.file_count === 1 ? '' : 's'}
            </span>
            <span className="tag tabular-nums text-ink-mid">
              {module.loc.toLocaleString()} loc
            </span>
            {module.symbols > 0 && (
              <span className="tag tabular-nums text-ink-dim">{module.symbols} sym</span>
            )}
          </span>
        </div>

        {/* The reason the row exists. Clamped to two lines closed, whole when open:
            three hundred characters each across twenty modules is a wall if every
            one of them is expanded at once. */}
        {module.summary ? (
          <p
            className={`mt-1 font-sans text-[11.5px] leading-relaxed text-ink-mid ${
              open ? '' : 'line-clamp-2'
            }`}
          >
            {module.summary}
          </p>
        ) : (
          <p className="mt-1 font-sans text-[11.5px] italic text-ink-dim">
            {module.is_test
              ? 'Test modules are not summarised.'
              : 'No summary was written for this module.'}
          </p>
        )}
      </button>

      {open && module.files.length > 0 && (
        <div className="border-t border-dashed border-rule bg-sunk/30 px-3 py-1.5">
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            {module.files.map(file => (
              <Link
                key={file}
                to={`/app/projects/${projectId}/code?file=${encodeURIComponent(file)}`}
                className="font-mono text-[11px] text-hot-ink hover:underline"
              >
                {file}
              </Link>
            ))}
          </div>
        </div>
      )}
    </li>
  )
}
