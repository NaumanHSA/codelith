import { Link } from 'react-router-dom'
import type { Project } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * Where you start.
 *
 * This band used to explain the product as well: the same identity
 * strip, the same offline pill, "Read the codebase once. Use it many
 * times.", the same opening paragraph, and the pipeline down a rail of
 * three numbered steps. All of it now sits below in the schematic, which
 * says it in a form a paragraph cannot — so keeping it here would only
 * mean Home saying everything twice, a hundred pixels apart.
 *
 * What is left is the part the schematic does not carry and must not:
 * the only button that starts anything. Nothing in this product happens
 * until a codebase has been read, and that has to be reachable without
 * scrolling past an explanation — which is also why this band has no
 * collapse. An entry point you can hide is not one.
 * ------------------------------------------------------------------ */

export default function HomeBanner({ projects }: { projects: Project[] | null }) {
  const none = projects !== null && projects.length === 0
  const unread = (projects ?? []).filter(p => !p.apps_ready).length

  return (
    <section className="mb-5 flex flex-wrap items-center gap-x-3 gap-y-2 border border-rule bg-panel px-4 py-3">
      <Link
        to="/app/projects?new=1"
        className="tag inline-flex items-center border border-hot bg-hot px-4 py-2.5 text-on-hot transition-colors hover:border-hot-press hover:bg-hot-press"
      >
        {none ? 'Get started' : 'Add a codebase'} →
      </Link>

      {/* The way in to work already done. Everything an app does happens on one
          codebase, so opening one is the step between Home and any of them. */}
      {!none && (
        <Link
          to="/app/projects"
          className="tag inline-flex items-center border border-rule bg-panel px-4 py-2.5 text-ink-mid transition-colors hover:border-ink hover:text-ink"
        >
          Open a codebase →
        </Link>
      )}

      <span className="font-sans text-[11.5px] leading-snug text-ink-dim">
        {none
          ? 'Nothing happens until a codebase has been read.'
          : unread
            ? `${unread} codebase${unread > 1 ? 's have' : ' has'} not been read yet.`
            : 'Add another repository, or upload a folder to read.'}
      </span>
    </section>
  )
}
