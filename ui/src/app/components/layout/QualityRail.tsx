import { useLocation, useNavigate } from 'react-router-dom'
import { useAsync } from '../../lib/hooks'
import { api } from '../../lib/api'

/* ------------------------------------------------------------------ *
 * Quality in the rail.
 *
 * A per-codebase app in a place that has no codebase selected — the
 * same problem the dashboard cards have, and the same answer: route by
 * what exists rather than making somebody pick first and find out what
 * they can do second.
 *
 * One analysed codebase goes straight through. Several list, because
 * choosing between them is the actual question. None says so.
 * ------------------------------------------------------------------ */

export default function QualityRail() {
  const navigate = useNavigate()
  const location = useLocation()
  const { data: projects } = useAsync(() => api.projects(30, 0), [])

  const ready = (projects ?? []).filter(p => p.apps_ready)

  if (!projects) {
    return <p className="px-4 py-1 text-[10.5px] text-ink-dim">Loading…</p>
  }

  if (!ready.length) {
    return (
      <p className="px-4 py-1 text-[10.5px] leading-snug text-ink-dim">
        Analyse a codebase to check it.
      </p>
    )
  }

  return (
    <>
      {ready.map(project => {
        const to = `/app/projects/${project.id}/quality`
        const active = location.pathname === to
        return (
          <button
            key={project.id}
            onClick={() => navigate(to)}
            className={`group relative flex w-full items-center gap-2 py-[5px] pr-2 pl-4 text-left transition-colors ${
              active ? 'bg-hot-wash' : 'hover:bg-sunk'
            }`}
          >
            {active && <span className="absolute top-0 left-0 h-full w-[3px] bg-hot" />}
            <span
              className={`block size-[5px] shrink-0 rotate-45 ${
                active ? 'bg-hot' : 'bg-rule group-hover:bg-hot'
              }`}
            />
            <span
              className={`min-w-0 flex-1 truncate text-[11px] ${
                active ? 'font-semibold text-hot-ink' : 'text-ink-mid'
              }`}
            >
              {project.name}
            </span>
          </button>
        )
      })}
    </>
  )
}
