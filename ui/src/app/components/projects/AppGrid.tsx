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
 * Built to Home's measurements, deliberately: a band of artwork, a
 * rule, then the words. Two attempts went the other way first — the
 * drawing ghosted behind the text, then shrunk into a 24px badge — and
 * both were answering a question Home had already answered. A plate
 * drawing needs a plate to sit on, not a corner to hide in.
 *
 * The same card in two places is also the point. These are the same
 * three apps, and a reader who has seen Home should recognise them
 * rather than work out twice that it is one product.
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
      {Art && (
        <div
          className={`flex h-[104px] items-center justify-center border-b px-6 py-3 transition-colors ${
            open
              ? 'border-rule bg-sunk/40 group-hover:bg-hot-wash/60'
              : 'border-rule bg-sunk/50 opacity-45'
          }`}
        >
          <Art />
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col p-3.5">
        <div className="mb-1.5 flex items-baseline gap-2">
          <h3 className={`text-[13.5px] font-semibold ${open ? 'text-ink' : 'text-ink-mid'}`}>
            {app.label}
          </h3>
          {open ? (
            <span className="tag plate-arrow ml-auto text-hot-ink">open →</span>
          ) : (
            <span className="tag ml-auto text-ink-dim">
              {app.state === 'planned' ? 'soon' : 'locked'}
            </span>
          )}
        </div>

        {/* The short form. `blurb` leads Home, where it is the first thing anybody
            reads about the product and has the room to be; here it sits above a
            knowledge base somebody came to look at. */}
        <p
          className={`font-sans text-[11.5px] leading-relaxed ${
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
        <p className="tag mt-auto pt-2.5 text-ink-dim">reads {app.needs.join(' · ')}</p>
      </div>
    </>
  )

  const shell = 'group flex min-w-0 flex-col border transition-colors'

  if (!open) {
    return (
      <div className={`${shell} border-rule bg-sunk/40`} aria-disabled>
        {body}
      </div>
    )
  }

  return (
    <Link to={app.route} className={`${shell} border-rule bg-panel hover:border-hot`}>
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
      {/* Three across, as on Home. Two wide left the third card alone on a second
          row, reading as an afterthought rather than as one of three equals. */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {features.map(f => (
          <Card key={f.id} app={f} extra={extras?.[f.id]} />
        ))}
      </div>
    </section>
  )
}
