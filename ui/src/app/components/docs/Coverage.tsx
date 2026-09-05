import { useState, type ReactNode } from 'react'
import type { Site, SitePage } from '../../lib/types'
import { coverage, isPending } from '../../lib/site'
import { Button, Meter } from '../ui'
import { PageMark } from './SiteNav'

/* ------------------------------------------------------------------ *
 * The whole map at a glance: what is built, what is planned, what has
 * gone stale.
 *
 * This is the screen that makes a documentation site feel different
 * from a folder of documents — you can see the shape of what the
 * project *should* document, and how much of it exists.
 * ------------------------------------------------------------------ */

function Legend({ n, label, tone }: { n: number; label: string; tone: string }) {
  if (!n) return null
  return (
    <span className="flex items-center gap-1.5">
      <span className={`block size-[5px] rotate-45 ${tone}`} aria-hidden />
      <span className="tag text-ink-dim">
        {n} {label}
      </span>
    </span>
  )
}

export default function Coverage({
  site,
  onOpen,
  onGenerateSection,
  generatingSection,
  canGenerate,
  home,
  selected,
  onToggleSelect,
}: {
  site: Site
  onOpen: (sectionSlug: string, page: SitePage) => void
  onGenerateSection: (sectionSlug: string) => void
  generatingSection: string | null
  canGenerate: boolean
  /** The nav-aware landing prose, rendered by the caller so this file stays light. */
  home?: ReactNode
  /** Page addresses picked for the next write. The bar that acts on them lives in
   *  the caller, because it is the caller that owns the compose call. */
  selected: Set<string>
  onToggleSelect: (address: string) => void
}) {
  const c = coverage(site)

  // Collapsed by default. Every page of every section expanded meant the map opened
  // two screens tall — you scrolled past twenty-three cards you were not choosing to
  // reach the controls, which is how nobody found them. The header carries the counts,
  // so the whole site is scannable without opening anything.
  //
  // A section still being written opens itself: that is the one you came to watch.
  const [open, setOpen] = useState<Set<string>>(
    () =>
      new Set(
        site.sections
          .filter(sec => sec.pages.some(p => p.status === 'generating'))
          .map(sec => sec.slug),
      ),
  )

  const toggleOpen = (slug: string) =>
    setOpen(prev => {
      const next = new Set(prev)
      if (next.has(slug)) next.delete(slug)
      else next.add(slug)
      return next
    })


  return (
    <div className="space-y-5">
      {home}
      <section className="plate">
        <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-rule bg-sunk/60 px-3 py-2">
          <span className="tag text-hot-ink">COV</span>
          <h2 className="text-[11.5px] font-semibold tracking-tight text-ink">Coverage</h2>
          <span className="ml-auto flex flex-wrap items-center gap-3">
            <Legend n={c.ready} label="written" tone="bg-ok" />
            <Legend n={c.stale} label="stale" tone="bg-warn" />
            <Legend n={c.generating} label="writing" tone="bg-hot" />
            <Legend n={c.failed} label="failed" tone="bg-bad" />
            <Legend n={c.planned} label="planned" tone="bg-rule" />
            <Legend n={c.orphaned} label="retired" tone="bg-ink-dim" />
          </span>
        </header>
        <div className="flex items-center gap-3 px-3 py-3">
          <Meter pct={c.pct} segments={28} />
          <span className="text-[12px] font-semibold text-ink">{c.pct}%</span>
          <span className="text-[11px] text-ink-dim">
            {c.ready + c.stale} of {c.total - c.orphaned} planned pages written
          </span>
        </div>
      </section>

      {site.sections.map(section => {
        const pending = section.pages.filter(p => isPending(p.status)).length
        const written = section.pages.filter(p => !isPending(p.status)).length
        const picked = section.pages.filter(p =>
          selected.has(`${section.slug}/${p.slug}`),
        ).length
        const busy = generatingSection === section.slug
        const isOpen = open.has(section.slug)
        return (
          <section key={section.slug} className="plate">
            <header className="flex items-center gap-2.5 border-b border-rule bg-sunk/60 pr-3">
              {/* The whole label is the toggle. A chevron alone is a small target and
                  gives no clue that the row does anything. */}
              <button
                onClick={() => toggleOpen(section.slug)}
                aria-expanded={isOpen}
                className="flex min-w-0 flex-1 items-center gap-2.5 px-3 py-2 text-left transition-colors hover:bg-hot-wash"
              >
                <span
                  className={`tag shrink-0 text-ink-dim transition-transform ${isOpen ? 'rotate-90' : ''}`}
                  aria-hidden
                >
                  ▸
                </span>
                <h3 className="truncate text-[11.5px] font-semibold tracking-tight text-ink">
                  {section.title}
                </h3>
                <span className="tag shrink-0 text-ink-dim">{written}/{section.pages.length}</span>
                {/* Enough to decide without opening it: that is the point of collapsing. */}
                <span className="tag shrink-0 text-ink-dim">
                  {pending > 0 ? `${pending} to write` : 'complete'}
                </span>
                {picked > 0 && (
                  <span className="tag shrink-0 text-hot-ink">{picked} selected</span>
                )}
              </button>
              {pending > 0 && canGenerate && (
                <Button variant="ghost" onClick={() => onGenerateSection(section.slug)} disabled={busy}>
                  {busy ? 'writing…' : `write ${pending} remaining`}
                </Button>
              )}
            </header>
            <ul hidden={!isOpen}>
              {section.pages.map(page => (
                <li key={page.id} className="flex items-stretch border-b border-rule last:border-b-0">
                  {canGenerate && (
                    // A written page can still be picked — it is the only way to
                    // regenerate one whole, and the reason to is usually depth. But
                    // it must not look like the unwritten ones: this list is headed
                    // "Coverage", counts "planned pages written", and offers "write N
                    // remaining", so an identical checkbox on a finished page reads as
                    // filling a gap right up until it replaces work.
                    <label
                      className={`flex cursor-pointer items-start pt-[9px] pl-3 select-none ${
                        isPending(page.status) ? '' : 'opacity-60'
                      }`}
                      title={
                        isPending(page.status)
                          ? 'Write this page in the next run'
                          : 'REPLACE this page: it is already written, and rewriting discards the current text'
                      }
                    >
                      <input
                        type="checkbox"
                        className={
                          isPending(page.status)
                            ? 'accent-[var(--hot)]'
                            : 'accent-[var(--warn)]'
                        }
                        checked={selected.has(`${section.slug}/${page.slug}`)}
                        onChange={() => onToggleSelect(`${section.slug}/${page.slug}`)}
                      />
                    </label>
                  )}
                  <button
                    onClick={() => onOpen(section.slug, page)}
                    className="flex w-full items-start gap-2.5 px-3 py-2 text-left transition-colors hover:bg-sunk/60"
                  >
                    <span className="pt-[5px]">
                      <PageMark status={page.status} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-baseline gap-x-2">
                        <span className="text-[12px] font-semibold text-ink">{page.title}</span>
                        <span className="tag text-ink-dim">
                          {section.slug}/{page.slug}
                        </span>
                        {page.word_count > 0 && (
                          <span className="tag text-ink-dim">{page.word_count} words</span>
                        )}
                      </span>
                      {page.intent && (
                        <span className="mt-0.5 block text-[11px] leading-snug text-ink-dim">
                          {page.intent}
                        </span>
                      )}
                    </span>
                    {!isPending(page.status) &&
                    selected.has(`${section.slug}/${page.slug}`) ? (
                      <span className="tag shrink-0 border border-warn/50 bg-warn-wash px-1.5 pt-[1px] text-warn">
                        will be replaced
                      </span>
                    ) : (
                      <span className="tag shrink-0 pt-[3px] text-ink-dim">{page.status}</span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )
      })}

      {!!site.orphaned_pages?.length && (
        <section className="plate">
          <header className="flex items-center gap-2.5 border-b border-rule bg-sunk/60 px-3 py-2">
            <h3 className="text-[11.5px] font-semibold tracking-tight text-ink">Retired</h3>
            <span className="ml-auto text-[10.5px] text-ink-dim">
              analysis no longer proposes these, but they are kept and still readable
            </span>
          </header>
          <ul>
            {site.orphaned_pages.map(page => (
              <li key={page.id} className="border-b border-rule last:border-b-0">
                <button
                  onClick={() => onOpen(page.section_slug, page)}
                  className="flex w-full items-center gap-2.5 px-3 py-1.5 text-left transition-colors hover:bg-sunk/60"
                >
                  <PageMark status={page.status} />
                  <span className="text-[11.5px] text-ink-mid">{page.title}</span>
                  <span className="tag ml-auto text-ink-dim">
                    {page.section_slug}/{page.slug}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
