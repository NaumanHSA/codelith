import { Link } from 'react-router-dom'
import type { Project } from '../../lib/types'
import { languageShares, relativeTime } from '../../lib/format'
import { StatusBadge } from '../ui'
import { EmptyState, ErrorState, SkeletonPanel } from '../States'

/* ------------------------------------------------------------------ *
 * The three codebases most recently touched, said properly.
 *
 * The old rows carried "1 job · 0 docs · updated 9h ago", which is
 * bookkeeping about this product rather than anything about the
 * codebase. What somebody wants from a row here is whether it has been
 * read, how big it is, what it is written in, and whether anything has
 * been written about it — and the list endpoint already returns all of
 * that, including the probe.
 *
 * Three rows at most. It is a shortcut back to recent work, not an
 * index, and a panel that grows with the account pushes everything
 * below it off the first screen.
 *
 * Rows keep their own height rather than dividing the panel. Sharing it
 * out meant one codebase got a row the height of three, which read as a
 * rendering fault rather than as an empty list.
 * ------------------------------------------------------------------ */

const SHOWN = 3

/** One fact about a codebase. Absent rather than "unknown" when unmeasured —
 *  a row of unknowns reads as broken. */
function Fact({ children, tone }: { children: React.ReactNode; tone?: 'ok' | 'dim' }) {
  return (
    <span
      className={`tag flex items-center gap-1.5 ${
        tone === 'ok' ? 'text-ok' : tone === 'dim' ? 'text-warn' : 'text-ink-dim'
      }`}
    >
      {children}
    </span>
  )
}

function Row({ project }: { project: Project }) {
  const source = project.sources?.[0]
  const probe = source?.config_json?.probe
  const language = languageShares(probe?.languages)[0]?.name
  const pages = project.stats?.page_count ?? 0
  const docs = project.stats?.doc_count ?? 0
  const written = pages + docs

  const analysing = project.latest_job?.status === 'running'

  return (
    <Link
      to={`/app/projects/${project.id}`}
      className="group flex shrink-0 flex-col gap-1 border-b border-rule px-3.5 py-2.5 transition-colors last:border-b-0 hover:bg-hot-wash"
    >
      <div className="flex min-w-0 items-center gap-2">
        <span className="block size-[6px] shrink-0 rotate-45 bg-hot" />
        <span className="truncate text-[13px] font-semibold text-ink">{project.name}</span>
        {project.latest_job && <StatusBadge status={project.latest_job.status} />}
        <span className="tag plate-arrow ml-auto shrink-0 text-ink-dim transition-colors group-hover:text-hot-ink">
          →
        </span>
      </div>

      {/* The repository is the description when nobody wrote one — more use
          than the sentence "No description." */}
      <p className="truncate font-sans text-[11.5px] leading-snug text-ink-mid">
        {project.description || source?.url_or_path || 'No source attached.'}
      </p>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {analysing ? (
          <Fact tone="dim">
            <span className="anim-spin block size-[7px] rounded-full border border-hot border-t-transparent" />
            analysing
          </Fact>
        ) : project.apps_ready ? (
          <Fact tone="ok">
            <span className="block size-[6px] rotate-45 bg-ok" />
            analysed
          </Fact>
        ) : (
          <Fact tone="dim">
            <span className="block size-[6px] rotate-45 border border-warn" />
            not analysed
          </Fact>
        )}

        {probe?.file_count != null && <Fact>{probe.file_count.toLocaleString()} files</Fact>}
        {language && <Fact>{language}</Fact>}
        {source?.branch && <Fact>{source.branch}</Fact>}

        <Fact>
          {written
            ? `${pages ? `${pages} page${pages === 1 ? '' : 's'}` : `${docs} doc${docs === 1 ? '' : 's'}`} written`
            : 'nothing written'}
        </Fact>

        <span className="tag ml-auto text-ink-dim">{relativeTime(project.updated_at)}</span>
      </div>
    </Link>
  )
}

export default function RecentProjects({
  projects,
  loading,
  error,
  onRetry,
}: {
  projects: Project[] | null
  loading: boolean
  error: string | null
  onRetry: () => void
}) {
  const recent = (projects ?? []).slice(0, SHOWN)

  return (
    <section className="plate flex flex-col overflow-hidden">
      <header className="flex shrink-0 items-center gap-2.5 border-b border-rule bg-sunk/60 px-3 py-2">
        <h2 className="text-[11.5px] font-semibold tracking-tight text-ink">
          Recent codebases
        </h2>
        <Link to="/app/projects" className="tag plate-arrow ml-auto text-hot-ink hover:underline">
          Show all{projects?.length ? ` ${projects.length}` : ''} →
        </Link>
      </header>

      <div className="flex flex-col">
        {loading ? (
          <div className="p-3">
            <SkeletonPanel rows={4} />
          </div>
        ) : error ? (
          <div className="p-3">
            <ErrorState message={error} onRetry={onRetry} compact />
          </div>
        ) : !recent.length ? (
          <EmptyState
            title="No codebases yet"
            body="Add a repository above — nothing else happens until one has been read."
            compact
          />
        ) : (
          recent.map(p => <Row key={p.id} project={p} />)
        )}
      </div>
    </section>
  )
}
