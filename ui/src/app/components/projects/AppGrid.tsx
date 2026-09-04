import { Link } from 'react-router-dom'
import type { ProjectApp } from '../../lib/types'
import { APP_MARK } from '../home/AppMark'

/* ------------------------------------------------------------------ *
 * What this codebase unlocks.
 *
 * The project page used to read Source → Documentation, which said the
 * point of analysis was to produce a document. It never was: analysis
 * takes no document type, and Ask the Code grew on the same knowledge
 * base without touching the documentation pipeline.
 *
 * These are the same three things Home offers, so they carry a mark of
 * the same app — but drawn for this size rather than borrowed from it.
 * Home's 120×64 plate ghosted into a card corner produced clipped
 * fragments that read as a rendering fault, which is what a drawing
 * does when it is used four times smaller than it was drawn.
 *
 * Locked cards are shown rather than hidden. They are how somebody
 * learns the shape of the product without reading marketing copy, and
 * the reason on each says what to do rather than what went wrong.
 * ------------------------------------------------------------------ */

/** A live number for an app that has one — "4 documents", "3 conversations". */
export type AppExtras = Record<string, React.ReactNode>

function Card({ app, extra }: { app: ProjectApp; extra?: React.ReactNode }) {
  const open = app.state === 'available'
  const Mark = APP_MARK[app.id]

  const body = (
    <>
      <div className="flex items-center gap-2.5">
        {/* In the title row, where an icon belongs — not behind the words hoping to
            be noticed. Bordered, so it reads as a plate mark rather than a sticker. */}
        {Mark && (
          <span
            className={`flex size-7 shrink-0 items-center justify-center border p-1 transition-colors ${
              open
                ? 'border-rule bg-sunk/60 group-hover:border-hot group-hover:bg-hot-wash'
                : 'border-rule bg-sunk/40 opacity-60'
            }`}
          >
            <Mark />
          </span>
        )}
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
        className={`mt-2 font-sans text-[12px] leading-relaxed ${
          open ? 'text-ink-mid' : 'text-ink-dim'
        }`}
      >
        {app.short || app.blurb}
      </p>

      {open && extra ? <div className="mt-2.5">{extra}</div> : null}

      {!open && app.reason && (
        <p className="mt-2 font-sans text-[11.5px] text-ink-dim">{app.reason}</p>
      )}

      {/* What it reads from the knowledge base. The honest answer to "why is this
          locked" is that the KB does not exist yet, so naming what it consumes is
          more use than a padlock. */}
      <p className="tag mt-auto pt-3 text-ink-dim">
        reads {app.needs.join(' · ')}
      </p>
    </>
  )

  const shell = 'group flex min-w-0 flex-col border p-3.5 transition-all duration-200'

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
