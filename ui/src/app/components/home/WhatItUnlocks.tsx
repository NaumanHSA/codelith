import type { AppCatalogItem, Project } from '../../lib/types'
import { APP_ART } from './AppArt'

/* ------------------------------------------------------------------ *
 * What a codebase unlocks — described, not offered.
 *
 * These were three cards you could click, and clicking one could not
 * do what it appeared to do. Every app works on *a* codebase, and Home
 * has none selected, so the cards either guessed when exactly one was
 * ready or dropped the reader on a chooser. Both are the same mistake:
 * a control that looks like it starts the thing and instead asks which
 * thing you meant.
 *
 * The real route is Home → a codebase → the app, which is why the same
 * three cards work on the codebase page and not here. So this explains
 * rather than offers, in the order the landing page uses: the apps come
 * after the analysis that makes them possible, because that ordering is
 * the whole argument — read once, use many times.
 *
 * Every entry mirrors `apps/registry.py`. A page that describes an app
 * the studio does not have is the worst kind of lie, because the reader
 * finds out later and by then they trusted it.
 * ------------------------------------------------------------------ */

export default function WhatItUnlocks({
  features,
  projects,
}: {
  features: AppCatalogItem[] | null
  projects: Project[] | null
}) {
  if (!features?.length) return null
  const ready = (projects ?? []).filter(p => p.apps_ready)

  return (
    <section className="mb-5">
      <div className="mb-2 flex items-center gap-2">
        <span className="tag text-ink-dim">What a read codebase unlocks</span>
        <span className="h-px flex-1 bg-rule" />
        <span className="tag text-ink-dim">
          {ready.length
            ? `open any of the ${ready.length} ready`
            : 'analyse a codebase to unlock'}
        </span>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {features.map((f, i) => {
          const Art = APP_ART[f.id]
          return (
            <article
              key={f.id}
              className="flex min-w-0 flex-col border border-rule bg-panel"
            >
              {Art && (
                <div className="flex h-[104px] items-center justify-center border-b border-rule bg-sunk/40 px-6 py-3">
                  <Art />
                </div>
              )}

              <div className="flex min-w-0 flex-1 flex-col p-3.5">
                <div className="mb-1.5 flex items-baseline gap-2">
                  {/* Numbered rather than linked. The number says "one of three
                      things", where an arrow said "go here" and then did not. */}
                  <span className="tag text-hot-ink">
                    {String(i + 1).padStart(2, '0')}
                  </span>
                  <h3 className="text-[13.5px] font-semibold text-ink">{f.label}</h3>
                  {!f.built && <span className="tag ml-auto text-ink-dim">soon</span>}
                </div>

                <p className="font-sans text-[11.5px] leading-relaxed text-ink-mid">
                  {f.blurb}
                </p>

                <p className="tag mt-auto pt-2.5 text-ink-dim">
                  reads {f.needs.join(' · ')}
                </p>
              </div>
            </article>
          )
        })}
      </div>

      <p className="mt-2 font-sans text-[11.5px] text-ink-dim">
        Each of these works on one codebase at a time. Open a codebase and all three
        are there, reading the same knowledge base.
      </p>
    </section>
  )
}
