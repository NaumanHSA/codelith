import { Link } from 'react-router-dom'
import type { Project } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * The entry point, stated as one.
 *
 * Nothing in this product happens until a codebase has been added and
 * read. The dashboard used to open with counters and a Quick Access
 * list, which is a summary of work already done — useless on the first
 * visit, when there is none, and it left the actual first step buried in
 * a sub-page.
 * ------------------------------------------------------------------ */

export default function StartHere({ projects }: { projects: Project[] | null }) {
  const none = projects !== null && projects.length === 0
  const unanalysed = (projects ?? []).filter(p => !p.apps_ready)

  // First visit: the whole band is the invitation, because there is nothing else
  // true to say yet.
  if (none) {
    return (
      <section className="mb-5 border border-hot bg-hot-wash p-6">
        <p className="tag mb-2 text-hot-ink">Start here</p>
        <h2 className="mb-2 max-w-[30ch] text-[22px] leading-tight font-bold tracking-tight text-ink">
          Add a codebase. Everything else follows from reading it.
        </h2>
        <p className="mb-5 max-w-[62ch] font-sans text-[13px] leading-relaxed text-ink-mid">
          Point Codelith at a repository or upload a folder. It walks every file and
          builds a knowledge base — and once that exists, documentation and Ask the
          code unlock together. Nothing leaves your machine.
        </p>
        <Link
          to="/app/projects?new=1"
          className="tag inline-flex items-center border border-hot bg-hot px-4 py-2.5 text-on-hot transition-colors hover:border-hot-press hover:bg-hot-press"
        >
          Add a codebase →
        </Link>
      </section>
    )
  }

  // Afterwards it stays reachable, but stops shouting.
  return (
    <section className="mb-5 flex flex-wrap items-center gap-x-4 gap-y-2 border border-rule bg-panel px-4 py-3">
      <span className="tag text-ink-dim">Start here</span>
      <span className="min-w-0 flex-1 font-sans text-[12.5px] text-ink-mid">
        {unanalysed.length
          ? `${unanalysed.length} codebase${unanalysed.length > 1 ? 's have' : ' has'} not been read yet — analysis is what unlocks everything else.`
          : 'Add another repository, or upload a folder to read.'}
      </span>
      <Link
        to="/app/projects?new=1"
        className="tag shrink-0 border border-hot bg-hot px-3 py-[7px] text-on-hot transition-colors hover:border-hot-press hover:bg-hot-press"
      >
        Add a codebase →
      </Link>
    </section>
  )
}
