import type { PageStatus, SitePage, SiteSection } from '../../lib/types'
import { isPending } from '../../lib/site'

/* ------------------------------------------------------------------ *
 * Pages in the active section.
 *
 * Planned pages are listed, greyed, with the button that writes them.
 * That is the whole idea: the nav doubles as the project's documentation
 * roadmap, so what does not exist yet is as visible as what does — and
 * one click from existing.
 * ------------------------------------------------------------------ */

/** A small square whose colour says what state a page is in. */
export function PageMark({ status }: { status: PageStatus }) {
  const tone =
    status === 'ready'
      ? 'bg-ok'
      : status === 'generating'
        ? 'bg-hot anim-pulse'
        : status === 'stale'
          ? 'bg-warn'
          : status === 'failed'
            ? 'bg-bad'
            : status === 'orphaned'
              ? 'bg-ink-dim'
              : 'bg-rule'
  return <span className={`block size-[5px] shrink-0 rotate-45 ${tone}`} aria-hidden />
}

export default function SiteNav({
  section,
  activeSlug,
  onOpen,
  onGenerate,
  generating,
  canGenerate,
}: {
  section: SiteSection | null
  activeSlug?: string
  onOpen: (page: SitePage) => void
  onGenerate: (page: SitePage) => void
  generating: string | null
  canGenerate: boolean
}) {
  if (!section) return null

  return (
    <nav className="flex flex-col">
      <div className="flex items-center gap-2 px-3 py-2">
        <span className="tag truncate text-ink-dim">{section.title}</span>
        <span className="h-px flex-1 bg-rule" />
        <span className="tag shrink-0 text-ink-dim">{section.pages.length}</span>
      </div>

      {section.pages.map(page => {
        const active = page.slug === activeSlug
        const pending = isPending(page.status)
        const busy = generating === `${page.section_slug}/${page.slug}`
        return (
          <div
            key={page.id}
            className={`group relative flex items-center gap-2 pr-1.5 transition-colors ${
              active ? 'bg-hot-wash' : 'hover:bg-sunk/70'
            }`}
          >
            {active && <span className="absolute top-0 left-0 h-full w-[3px] bg-hot" />}
            <button
              onClick={() => onOpen(page)}
              title={page.intent ?? page.title}
              className="flex min-w-0 flex-1 items-center gap-2 py-[6px] pl-3 text-left"
            >
              <PageMark status={busy ? 'generating' : page.status} />
              <span
                className={`min-w-0 flex-1 truncate text-[11.5px] ${
                  active
                    ? 'font-semibold text-hot-ink'
                    : pending
                      ? 'text-ink-dim'
                      : 'text-ink-mid group-hover:text-ink'
                }`}
              >
                {page.title}
              </span>
            </button>

            {pending && canGenerate && (
              <button
                onClick={() => onGenerate(page)}
                disabled={busy}
                title={`Write “${page.title}” from the knowledge base`}
                className="tag shrink-0 border border-rule bg-panel px-1.5 py-[2px] text-ink-dim opacity-0 transition-all group-hover:opacity-100 hover:border-hot hover:text-hot-ink focus:opacity-100 disabled:opacity-100"
              >
                {busy ? 'writing…' : 'write'}
              </button>
            )}
            {busy && !pending && <span className="tag shrink-0 text-hot-ink">writing…</span>}
          </div>
        )
      })}

      {section.pages.length === 0 && (
        <p className="px-3 py-2 text-[10.5px] leading-snug text-ink-dim">
          Nothing planned in this section yet.
        </p>
      )}
    </nav>
  )
}
