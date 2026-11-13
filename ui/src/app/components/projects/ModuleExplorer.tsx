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
        <Chips label="Role" values={roles} current={role} onPick={setRole} />
        {languages.length > 1 && (
          <Chips label="Language" values={languages} current={language} onPick={setLanguage} />
        )}
        <div className="ml-auto flex items-center gap-2">
          <span className="text-[12.5px] text-ink-dim">Sort by</span>
          <div className="flex gap-0.5 rounded-lg border border-rule bg-paper p-[3px]">
            {(['size', 'files', 'name'] as Sort[]).map(option => (
              <button
                key={option}
                type="button"
                aria-pressed={sort === option}
                onClick={() => setSort(option)}
                className={`rounded-md px-2.5 py-0.5 text-[12.5px] font-medium transition-colors ${
                  sort === option ? 'bg-sunk text-ink shadow-[inset_0_0_0_1px_var(--line-2)]' : 'text-ink-mid hover:text-ink'
                }`}
              >
                {option.charAt(0).toUpperCase() + option.slice(1)}
              </button>
            ))}
          </div>
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
        <span className="text-[12px] text-ink-dim">
          {rows.length} of {data.modules.length} module
          {data.modules.length === 1 ? '' : 's'}
          {shownLoc > 0 && `, ${shownLoc.toLocaleString()} lines`}
        </span>
        {data.without_summary > 0 && (
          <span className="text-[12px] text-warn">{data.without_summary} never summarised</span>
        )}
        {rows.length === 0 && <span className="text-[12px] text-ink-dim">Nothing matches that filter</span>}
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
      <span className="mr-0.5 text-[12.5px] text-ink-dim">{label}</span>
      {['', ...values].map(value => {
        const on = current === value
        return (
          <button
            key={value || 'all'}
            type="button"
            aria-pressed={on}
            onClick={() => onPick(value && current === value ? '' : value)}
            className={`rounded-full border px-2.5 py-0.5 text-[12px] font-medium transition-colors ${
              on
                ? 'border-hot-edge bg-hot-wash text-hot-ink'
                : 'border-rule text-ink-mid hover:border-line-2 hover:text-ink'
            }`}
          >
            {value ? value.charAt(0).toUpperCase() + value.slice(1) : 'All'}
          </button>
        )
      })}
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
          <span className="font-mono text-[13px] font-semibold text-ink">{module.name}</span>
          {module.role && (
            <span
              className={`rounded-md border px-1.5 py-[1px] text-[11.5px] font-medium ${
                ROLE_TONE[module.role] ?? 'border-rule text-ink-mid'
              }`}
            >
              {module.role}
            </span>
          )}
          {module.language && <span className="text-[12px] text-ink-dim">{module.language}</span>}
          <span className="ml-auto flex shrink-0 items-baseline gap-3 font-mono text-[11.5px] tabular-nums">
            <span className="text-ink-dim">
              {module.file_count} file{module.file_count === 1 ? '' : 's'}
            </span>
            <span className="text-ink-mid">{module.loc.toLocaleString()} lines</span>
            {module.symbols > 0 && <span className="text-ink-dim">{module.symbols} symbols</span>}
          </span>
        </div>

        {/* The reason the row exists. Clamped to two lines closed, whole when open:
            three hundred characters each across twenty modules is a wall if every
            one of them is expanded at once. */}
        {module.summary ? (
          <p
            className={`mt-1 text-[12.5px] leading-relaxed text-ink-mid ${
              open ? '' : 'line-clamp-2'
            }`}
          >
            {module.summary}
          </p>
        ) : (
          <p className="mt-1 text-[12.5px] italic text-ink-dim">
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
                className="font-mono text-[12px] text-hot-ink hover:underline"
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
