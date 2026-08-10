import { Link } from 'react-router-dom'
import type { AppCatalogItem, Project } from '../../lib/types'
import { APP_ART } from './AppArt'

/* ------------------------------------------------------------------ *
 * What Codelith does, on the way in.
 *
 * The hard part is that an app needs a codebase and Home has none
 * selected. Rather than make the reader pick first and find out what
 * they can do second, each card routes by what actually exists:
 *
 *   no analysed codebase   → locked, and says analysis is the unlock
 *   exactly one            → straight through to it
 *   several                → to a chooser
 *
 * The one-codebase case is the common one and the only one where
 * guessing is safe, which is why it is special-cased rather than always
 * sending everybody to a picker.
 *
 * One row, always. Three apps that wrapped onto two rows read as a list
 * that happens to be two wide rather than as the whole of what this
 * thing does — and the whole of it is the point.
 * ------------------------------------------------------------------ */

/** Where a card goes when more than one codebase could serve it. */
const CHOOSER: Record<string, string> = {
  // Ask already carries its own project selector, so it can take the reader
  // straight there and let them switch inside.
  ask: '/app/chat',
}

function resolve(
  app: AppCatalogItem,
  ready: Project[],
): { to: string | null; note: string } {
  if (!app.built) return { to: null, note: 'Not built yet.' }
  if (ready.length === 0) {
    return { to: null, note: 'Analyse a codebase to unlock this.' }
  }
  if (ready.length === 1) {
    return {
      to: app.route_template.replace('{id}', String(ready[0].id)),
      note: ready[0].name,
    }
  }
  return {
    to: CHOOSER[app.id] ?? '/app/projects',
    note: `${ready.length} codebases ready`,
  }
}

export default function AppCards({
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
        <span className="tag text-ink-dim">What you can do</span>
        <span className="h-px flex-1 bg-rule" />
        <span className="tag text-ink-dim">
          {ready.length ? `${ready.length} ready` : 'nothing analysed yet'}
        </span>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {features.map(f => {
          const { to, note } = resolve(f, ready)
          const Art = APP_ART[f.id]
          const shell = 'group flex min-w-0 flex-col border transition-colors'

          const body = (
            <>
              {Art && (
                <div
                  className={`flex h-[104px] items-center justify-center border-b px-6 py-3 transition-colors ${
                    to
                      ? 'border-rule bg-sunk/40 group-hover:bg-hot-wash/60'
                      : 'border-rule bg-sunk/50 opacity-45'
                  }`}
                >
                  <Art />
                </div>
              )}

              <div className="flex min-w-0 flex-1 flex-col p-3.5">
                <div className="mb-1.5 flex items-baseline gap-2">
                  <h3
                    className={`text-[13.5px] font-semibold ${to ? 'text-ink' : 'text-ink-mid'}`}
                  >
                    {f.label}
                  </h3>
                  {to ? (
                    <span className="tag plate-arrow ml-auto text-hot-ink">open →</span>
                  ) : (
                    <span className="tag ml-auto text-ink-dim">
                      {f.built ? 'locked' : 'soon'}
                    </span>
                  )}
                </div>

                <p
                  className={`font-sans text-[11.5px] leading-relaxed ${
                    to ? 'text-ink-mid' : 'text-ink-dim'
                  }`}
                >
                  {f.blurb}
                </p>

                <p className="tag mt-auto pt-2.5 text-ink-dim">{note}</p>
              </div>
            </>
          )

          return to ? (
            <Link
              key={f.id}
              to={to}
              className={`${shell} border-rule bg-panel hover:border-hot`}
            >
              {body}
            </Link>
          ) : (
            <div key={f.id} className={`${shell} border-rule bg-sunk/40`} aria-disabled>
              {body}
            </div>
          )
        })}
      </div>
    </section>
  )
}
