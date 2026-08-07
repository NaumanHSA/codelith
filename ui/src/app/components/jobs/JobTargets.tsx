import { Link } from 'react-router-dom'
import { PageMark } from '../docs/PageMark'
import { isTerminal, type Job, type Site, type SitePage } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * What this run is writing, and how far each page has got.
 *
 * A composition run used to be described as "Architecture · 4 pages",
 * which says the shape of the work and nothing about its subject — every
 * run looked identical in a list, and landing on one from a notification
 * told you nothing at all.
 *
 * The addresses are already on the job (`scope.pages`). Everything else
 * comes from the site map, which is the only thing that knows a page's
 * title, its section's title, and — crucially — its *current* status. So
 * this doubles as live per-page progress: the site is re-fetched while
 * the job runs, and each row moves planned → writing → written on its
 * own, which is the one view that shows a five-page run as five things
 * happening rather than one bar.
 *
 * Every row links to the page. From the page, `PageProgress` links back
 * to the run. Neither direction should be a dead end.
 * ------------------------------------------------------------------ */

interface Target {
  address: string
  sectionTitle: string
  page: SitePage | null
}

function resolve(job: Job, site: Site | null): Target[] {
  const addresses = job.scope?.pages ?? []
  return addresses.map(address => {
    const [sectionSlug, slug] = address.split('/')
    const section = site?.sections.find(s => s.slug === sectionSlug)
    return {
      address,
      sectionTitle: section?.title ?? sectionSlug,
      page: section?.pages.find(p => p.slug === slug) ?? null,
    }
  })
}

const STATE: Record<string, { label: string; tone: string }> = {
  generating: { label: 'writing…', tone: 'text-hot-ink' },
  ready: { label: 'written', tone: 'text-ok' },
  stale: { label: 'out of date', tone: 'text-warn' },
  failed: { label: 'failed', tone: 'text-bad' },
  planned: { label: 'queued', tone: 'text-ink-dim' },
  orphaned: { label: 'orphaned', tone: 'text-ink-dim' },
}

export default function JobTargets({
  job, site, projectId, projectName,
}: {
  job: Job
  site: Site | null
  projectId: number
  projectName?: string | null
}) {
  const targets = resolve(job, site)
  if (!targets.length) return null

  const done = targets.filter(t => t.page?.status === 'ready').length
  const writing = targets.find(t => t.page?.status === 'generating')
  const live = !isTerminal(job.status)

  return (
    <div className="mb-3 border border-rule bg-panel">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 border-b border-rule px-3 py-2">
        <span className="tag text-ink-dim">writing into</span>
        <Link
          to={`/app/projects/${projectId}`}
          className="text-[12px] font-semibold text-ink transition-colors hover:text-hot-ink"
        >
          {projectName ?? `project ${projectId}`}
        </Link>
        <span className="text-ink-dim">/</span>
        <Link
          to={`/app/projects/${projectId}/docs`}
          className="text-[12px] text-ink-mid transition-colors hover:text-hot-ink"
        >
          documentation
        </Link>
        {targets.length > 1 && (
          <span className="tag ml-auto text-ink-dim">
            {done}/{targets.length} written
          </span>
        )}
      </div>

      {/* The one line that answers "what is it doing right now?" */}
      {writing && (
        <div className="flex items-center gap-2 border-b border-rule bg-hot-wash/50 px-3 py-1.5">
          <span className="anim-blink block size-[6px] shrink-0 rounded-full bg-hot" />
          <span className="tag shrink-0 text-hot-ink">now writing</span>
          <span className="min-w-0 truncate text-[12px] font-semibold text-ink">
            {writing.page?.title ?? writing.address}
          </span>
          <span className="tag shrink-0 text-ink-dim">{writing.sectionTitle}</span>
        </div>
      )}

      {/* The run is over and the thing it made is one click away. Landing on a
          finished job and having to work out where the output went is the whole
          reason this is here — and the first written page is the obvious target. */}
      {done > 0 && !live && (
        <div className="flex flex-wrap items-center gap-2 border-b border-rule bg-hot-wash/40 px-3 py-2.5">
          <span className="tag text-ink-mid">
            {done === 1 ? 'The page is ready to read' : `${done} pages are ready to read`}
          </span>
          <Link
            to={`/app/projects/${projectId}/docs/${(targets.find(t => t.page?.status === 'ready') ?? targets[0]).address}`}
            className="ml-auto border border-hot bg-hot px-3 py-[5px] text-[12px] font-semibold tracking-tight text-paper transition-opacity hover:opacity-90"
          >
            Read the document →
          </Link>
        </div>
      )}

      <ul className="divide-y divide-rule">
        {targets.map(t => {
          const status = t.page?.status ?? 'planned'
          const state = STATE[status] ?? STATE.planned
          return (
            <li key={t.address}>
              <Link
                to={`/app/projects/${projectId}/docs/${t.address}`}
                className="group flex items-center gap-2.5 px-3 py-2 transition-colors hover:bg-hot-wash/60"
              >
                <PageMark status={status} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[12px] text-ink">
                    {t.page?.title ?? t.address}
                  </span>
                  <span className="tag block truncate text-ink-dim">
                    {t.sectionTitle} · {t.address}
                  </span>
                </span>
                {t.page?.word_count ? (
                  <span className="tag hidden shrink-0 text-ink-dim sm:block">
                    {t.page.word_count.toLocaleString()} words
                  </span>
                ) : null}
                <span className={`tag shrink-0 ${state.tone}`}>{state.label}</span>
                <span className="tag shrink-0 text-hot-ink opacity-0 transition-opacity group-hover:opacity-100">
                  open →
                </span>
              </Link>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
