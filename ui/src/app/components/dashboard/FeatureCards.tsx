import { Link } from 'react-router-dom'
import type { FeatureCatalogItem, Project } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * What Codelith does, on the way in.
 *
 * The hard part is that a feature needs a codebase and the dashboard
 * has none selected. Rather than make the reader pick first and find
 * out what they can do second, each card routes by what actually
 * exists:
 *
 *   no analysed codebase   → locked, and says analysis is the unlock
 *   exactly one            → straight through to it
 *   several                → to a chooser
 *
 * The one-codebase case is the common one and the only one where
 * guessing is safe, which is why it is special-cased rather than always
 * sending everybody to a picker.
 * ------------------------------------------------------------------ */

/** Where a card goes when more than one codebase could serve it. */
const CHOOSER: Record<string, string> = {
  // Ask already carries its own project selector, so it can take the reader
  // straight there and let them switch inside.
  ask: '/app/chat',
}

function resolve(
  feature: FeatureCatalogItem,
  ready: Project[],
): { to: string | null; note: string } {
  if (!feature.built) return { to: null, note: 'Not built yet.' }
  if (ready.length === 0) {
    return { to: null, note: 'Analyse a codebase to unlock this.' }
  }
  if (ready.length === 1) {
    return {
      to: feature.route_template.replace('{id}', String(ready[0].id)),
      note: ready[0].name,
    }
  }
  return {
    to: CHOOSER[feature.id] ?? '/app/projects',
    note: `${ready.length} codebases ready`,
  }
}

export default function FeatureCards({
  features,
  projects,
}: {
  features: FeatureCatalogItem[] | null
  projects: Project[] | null
}) {
  if (!features?.length) return null
  const ready = (projects ?? []).filter(p => p.features_ready)

  return (
    <section className="mb-5">
      <div className="mb-2 flex items-center gap-2">
        <span className="tag text-ink-dim">What you can do</span>
        <span className="h-px flex-1 bg-rule" />
        <span className="tag text-ink-dim">
          {ready.length ? `${ready.length} ready` : 'nothing analysed yet'}
        </span>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {features.map(f => {
          const { to, note } = resolve(f, ready)
          const shell = 'flex min-w-0 flex-col border p-3.5 transition-colors'

          const body = (
            <>
              <div className="mb-1.5 flex items-baseline gap-2">
                <h3 className={`text-[13.5px] font-semibold ${to ? 'text-ink' : 'text-ink-mid'}`}>
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
                className={`font-sans text-[12px] leading-relaxed ${
                  to ? 'text-ink-mid' : 'text-ink-dim'
                }`}
              >
                {f.blurb}
              </p>

              <p className="tag mt-2.5 text-ink-dim">{note}</p>
            </>
          )

          return to ? (
            <Link
              key={f.id}
              to={to}
              className={`${shell} border-rule bg-panel hover:border-hot hover:bg-hot-wash/40`}
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
