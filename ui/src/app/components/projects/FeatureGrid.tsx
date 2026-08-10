import { Link } from 'react-router-dom'
import type { ProjectFeature } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * What this codebase unlocks.
 *
 * The project page used to read Source → Documentation, which said the
 * point of analysis was to produce a document. It never was: analysis
 * takes no document type, and Ask the Code grew on the same knowledge
 * base without touching the documentation pipeline.
 *
 * Locked cards are shown rather than hidden. They are how somebody
 * learns the shape of the product without reading marketing copy, and
 * the reason on each says what to do rather than what went wrong.
 * ------------------------------------------------------------------ */

/** A live number for a feature that has one — "4 documents", "3 conversations". */
export type FeatureExtras = Record<string, React.ReactNode>

function Card({ feature, extra }: { feature: ProjectFeature; extra?: React.ReactNode }) {
  const open = feature.state === 'available'

  const body = (
    <>
      <div className="flex items-baseline gap-2">
        <h3
          className={`text-[13px] font-semibold ${open ? 'text-ink' : 'text-ink-mid'}`}
        >
          {feature.label}
        </h3>
        {!open && (
          <span className="tag text-ink-dim">
            {feature.state === 'planned' ? 'soon' : 'locked'}
          </span>
        )}
        {open && <span className="tag plate-arrow ml-auto text-hot-ink">open →</span>}
      </div>

      <p
        className={`mt-1.5 font-sans text-[12px] leading-relaxed ${
          open ? 'text-ink-mid' : 'text-ink-dim'
        }`}
      >
        {feature.blurb}
      </p>

      {open && extra ? <div className="mt-2.5">{extra}</div> : null}

      {!open && feature.reason && (
        <p className="mt-2 font-sans text-[11.5px] text-ink-dim">{feature.reason}</p>
      )}

      {/* What it reads from the knowledge base. The honest answer to "why is this
          locked" is that the KB does not exist yet, so naming what it consumes is
          more use than a padlock. */}
      <p className="tag mt-2.5 text-ink-dim">reads {feature.needs.join(' · ')}</p>
    </>
  )

  const shell = 'flex min-w-0 flex-col border p-3 transition-colors'

  if (!open) {
    return (
      <div className={`${shell} border-rule bg-sunk/40`} aria-disabled>
        {body}
      </div>
    )
  }

  return (
    <Link
      to={feature.route}
      className={`${shell} group border-rule bg-panel hover:border-hot hover:bg-hot-wash/40`}
    >
      {body}
    </Link>
  )
}

export default function FeatureGrid({
  features,
  extras,
}: {
  features: ProjectFeature[]
  extras?: FeatureExtras
}) {
  if (!features.length) return null

  return (
    <section>
      <div className="mb-2 flex items-center gap-2">
        <span className="tag text-ink-dim">What you can do with this codebase</span>
        <span className="h-px flex-1 bg-rule" />
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {features.map(f => (
          <Card key={f.id} feature={f} extra={extras?.[f.id]} />
        ))}
      </div>
    </section>
  )
}
