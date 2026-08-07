import type { SitePage, SiteSection } from '../../lib/types'
import { isPending } from '../../lib/site'
import Menu, { type MenuItem } from '../Menu'
import Tooltip from '../Tooltip'
// Re-exported so existing importers keep working; it lives on its own now because
// the job page shows the same marks and the two must not drift apart.
import { PageMark } from './PageMark'

export { PageMark }

/* ------------------------------------------------------------------ *
 * Pages in the active section.
 *
 * Planned pages are listed, greyed, with a way to write them. That is
 * the whole idea: the nav doubles as the project's documentation
 * roadmap, so what does not exist yet is as visible as what does — and
 * one click from existing.
 *
 * Every action lives in one always-visible menu rather than as controls
 * that fade in on hover. A hover-only affordance tells nobody it is
 * there, and on a touch screen it exists for nobody at all.
 * ------------------------------------------------------------------ */

export default function SiteNav({
  section,
  activeSlug,
  onOpen,
  onGenerate,
  onDelete,
  onExport,
  generating,
  canGenerate,
  bare = false,
}: {
  section: SiteSection | null
  activeSlug?: string
  onOpen: (page: SitePage) => void
  onGenerate: (page: SitePage) => void
  onDelete: (page: SitePage) => void
  onExport: (page: SitePage) => void
  generating: string | null
  canGenerate: boolean
  /** Drop the outer border when the caller already draws one around it. */
  bare?: boolean
}) {
  if (!section) return null

  return (
    // Bordered like the document container it sits beside, rather than bleeding into
    // the shell's rail. These are the site's files; against the reading column they
    // should read as a peer of it, not as chrome.
    <nav className={`flex flex-col ${bare ? '' : 'border border-rule bg-panel'}`}>
      <div className="flex items-center gap-2 border-b border-rule px-3 py-2">
        <span className="tag truncate text-ink-dim">{section.title}</span>
        <span className="h-px flex-1 bg-rule" />
        <span className="tag shrink-0 text-ink-dim">{section.pages.length}</span>
      </div>

      {section.pages.map(page => {
        const active = page.slug === activeSlug
        const pending = isPending(page.status)
        // The server's view first, the local one only as the optimistic gap between
        // pressing write and the map catching up. A page claimed by someone else's
        // run has to look busy here too.
        const busy =
          page.status === 'generating' || generating === `${page.section_slug}/${page.slug}`
        const written = page.status === 'ready' || page.status === 'stale'

        const items: MenuItem[] = []
        if (canGenerate) {
          items.push({
            label: written ? 'Rewrite this page' : 'Write this page',
            onSelect: () => onGenerate(page),
            disabled: busy,
            hint: busy ? 'A run is writing it now' : undefined,
          })
        }
        items.push({
          label: 'Export as Markdown',
          onSelect: () => onExport(page),
          disabled: !written,
          hint: written ? undefined : 'Nothing written yet',
        })
        if (canGenerate) {
          items.push({
            label: 'Delete this page',
            onSelect: () => onDelete(page),
            danger: true,
            disabled: busy,
            // A run in flight would finish and write prose back to a row that no
            // longer exists, so the API refuses it too.
            hint: busy ? 'Cannot delete while it is being written' : undefined,
          })
        }

        return (
          <div
            key={page.id}
            className={`group relative flex items-center gap-1.5 pr-1.5 transition-colors ${
              active ? 'bg-hot-wash' : 'hover:bg-sunk/70'
            }`}
          >
            {active && <span className="absolute top-0 left-0 h-full w-[3px] bg-hot" />}

            <Tooltip content={page.intent} className="min-w-0 flex-1">
              <button
                onClick={() => onOpen(page)}
                className="flex w-full min-w-0 items-center gap-2 py-[9px] pl-3 text-left"
              >
                <PageMark status={busy ? 'generating' : page.status} />
                <span
                  className={`min-w-0 flex-1 truncate text-[12.5px] ${
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
            </Tooltip>

            {busy && <span className="tag shrink-0 text-hot-ink">writing…</span>}

            <Menu items={items} label={`Actions for ${page.title}`} />
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
