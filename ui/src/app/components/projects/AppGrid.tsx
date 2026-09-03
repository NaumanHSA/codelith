import { Link } from 'react-router-dom'
import type { ProjectApp } from '../../lib/types'
import { APP_ART } from '../home/AppArt'

/* ------------------------------------------------------------------ *
 * What this codebase unlocks.
 *
 * The project page used to read Source → Documentation, which said the
 * point of analysis was to produce a document. It never was: analysis
 * takes no document type, and Ask the Code grew on the same knowledge
 * base without touching the documentation pipeline.
 *
 * These are the same three things Home offers, so they carry the same
 * drawings. They were bare text blocks here and illustrated there,
 * which made the reader work out twice that they were the same
 * product — the second time on the page where they had already chosen
 * a codebase and the cards matter most.
 *
 * Locked cards are shown rather than hidden. They are how somebody
 * learns the shape of the product without reading marketing copy, and
 * the reason on each says what to do rather than what went wrong.
 * ------------------------------------------------------------------ */

/** A live number for an app that has one — "4 documents", "3 conversations". */
export type AppExtras = Record<string, React.ReactNode>

function Card({ app, extra }: { app: ProjectApp; extra?: React.ReactNode }) {
  const open = app.state === 'available'
  const Art = APP_ART[app.id]

  const body = (
    <>
      {/* Bottom-right, behind the footer line. It was top-right and collided with
          both the title row and the "open →" affordance — artwork that sits on top of
          the one control on the card is decoration charging rent. Down here it fills
          the space the short text leaves rather than competing for the space it uses. */}
      {Art && (
        <div
          className="pointer-events-none absolute -right-3 -bottom-2 h-[70px] w-[130px] opacity-[0.14] transition-all duration-300 group-hover:-bottom-1 group-hover:opacity-35"
          aria-hidden
        >
          <Art />
        </div>
      )}

      <div className="relative flex items-baseline gap-2">
        <h3 className={`text-[13px] font-semibold ${open ? 'text-ink' : 'text-ink-mid'}`}>
          {app.label}
        </h3>
        {!open && (
          <span className="tag text-ink-dim">
            {app.state === 'planned' ? 'soon' : 'locked'}
          </span>
        )}
        {open && (
          <span className="tag ml-auto text-hot-ink transition-transform duration-200 group-hover:translate-x-1">
            open →
          </span>
        )}
      </div>

      {/* The short form. `blurb` is written to lead the Home page, where it is the
          first thing anybody reads about the product; here it is one of three cards
          beside a knowledge base, and five lines of it buried the rest of the page. */}
      <p
        className={`relative mt-1.5 max-w-[88%] font-sans text-[12px] leading-relaxed ${
          open ? 'text-ink-mid' : 'text-ink-dim'
        }`}
      >
        {app.short || app.blurb}
      </p>

      {open && extra ? <div className="relative mt-2.5">{extra}</div> : null}

      {!open && app.reason && (
        <p className="relative mt-2 font-sans text-[11.5px] text-ink-dim">{app.reason}</p>
      )}

      {/* What it reads from the knowledge base. The honest answer to "why is this
          locked" is that the KB does not exist yet, so naming what it consumes is
          more use than a padlock. */}
      <p className="tag relative mt-auto pt-2.5 text-ink-dim">
        reads {app.needs.join(' · ')}
      </p>
    </>
  )

  const shell =
    'group relative flex min-w-0 flex-col overflow-hidden border p-3.5 transition-all duration-200'

  if (!open) {
    return (
      <div className={`${shell} border-rule bg-sunk/40`} aria-disabled>
        {body}
      </div>
    )
  }

  return (
    <Link
      to={app.route}
      className={`${shell} border-rule bg-panel hover:-translate-y-[2px] hover:border-hot hover:bg-hot-wash/30 hover:shadow-[3px_3px_0_0_var(--hot-edge)]`}
    >
      {body}
    </Link>
  )
}

export default function AppGrid({
  features,
  extras,
}: {
  features: ProjectApp[]
  extras?: AppExtras
}) {
  if (!features.length) return null

  return (
    <section>
      <div className="mb-2 flex items-center gap-2">
        <span className="tag text-ink-dim">What you can do with this codebase</span>
        <span className="h-px flex-1 bg-rule" />
      </div>
      {/* Three across, matching Home. Two wide left the third card alone on a second
          row, reading as an afterthought rather than as one of three equals. */}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {features.map(f => (
          <Card key={f.id} app={f} extra={extras?.[f.id]} />
        ))}
      </div>
    </section>
  )
}
