import { useLocation } from 'react-router-dom'
import { useProjectsList } from '../../projects-list'
import { RailAction, RailNote, RailRow } from './RailRow'

/* ------------------------------------------------------------------ *
 * Documentation in the rail.
 *
 * A per-codebase app reached from a place with no codebase selected —
 * so it lists the codebases rather than making somebody pick first and
 * find out what they can do second. Three, newest-touched first: this is
 * a shortcut back to recent work, not an index. The index is Codebases.
 *
 * Each row says what has actually been written there, because "open
 * Documentation" means two different things depending on whether there
 * are pages to read or a site still to compose.
 * ------------------------------------------------------------------ */

const SHOWN = 3

export default function DocsRail() {
  const location = useLocation()
  const { projects, loading } = useProjectsList()

  // Only a codebase that has been read can be written about. An unanalysed one
  // in this list would open a page whose only content is "analyse first".
  const ready = projects.filter(p => p.apps_ready)
  const shown = ready.slice(0, SHOWN)

  if (loading) return <RailNote>Loading…</RailNote>

  return (
    <>
      {shown.length === 0 ? (
        <RailNote>Analyse a codebase to write about it.</RailNote>
      ) : (
        shown.map(p => {
          const to = `/app/projects/${p.id}/compose`
          const pages = p.stats?.page_count ?? 0
          const docs = p.stats?.doc_count ?? 0
          const written = pages + docs
          return (
            <RailRow
              key={p.id}
              to={to}
              active={location.pathname === to}
              label={p.name}
              sub={
                written
                  ? `${pages ? `${pages} page${pages === 1 ? '' : 's'}` : ''}${
                      pages && docs ? ' · ' : ''
                    }${docs ? `${docs} doc${docs === 1 ? '' : 's'}` : ''}`
                  : 'nothing written yet'
              }
              title={`Documentation — ${p.name}`}
            />
          )
        })
      )}

      {ready.length > SHOWN && (
        <RailAction to="/app/projects">View all {ready.length} →</RailAction>
      )}

      <RailAction to="/app/documents" active={location.pathname.startsWith('/app/documents')}>
        <span className="block size-[5px] shrink-0 rotate-45 border border-ink-dim group-hover:border-hot group-hover:bg-hot" />
        Published documents
      </RailAction>
    </>
  )
}
