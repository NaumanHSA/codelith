import { useLocation } from 'react-router-dom'
import { useProjectsList } from '../../projects-list'
import { RailNote, RailRow } from './RailRow'

/* ------------------------------------------------------------------ *
 * Quality in the rail.
 *
 * A per-codebase app in a place that has no codebase selected — the
 * same problem Documentation has, and the same answer: route by what
 * exists rather than making somebody pick first and find out what they
 * can do second.
 *
 * Nothing here reports a count. A check is not run until somebody asks
 * for one, so a number beside a codebase would either be stale or a lie
 * about work that has not happened.
 * ------------------------------------------------------------------ */

export default function QualityRail() {
  const location = useLocation()
  const { projects, loading } = useProjectsList()

  const ready = projects.filter(p => p.apps_ready)

  if (loading) return <RailNote>Loading…</RailNote>
  if (!ready.length) return <RailNote>Analyse a codebase to check it.</RailNote>

  return (
    <>
      {ready.slice(0, 5).map(p => {
        const to = `/app/projects/${p.id}/quality`
        return (
          <RailRow
            key={p.id}
            to={to}
            active={location.pathname === to}
            label={p.name}
            title={`Quality — ${p.name}`}
          />
        )
      })}
    </>
  )
}
