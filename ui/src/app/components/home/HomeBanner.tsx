import { Link } from 'react-router-dom'
import type { Project } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * What this is, and where you start — said once, at the top of Home.
 *
 * Home opened straight into counters and cards, which assumes the reader
 * already knows what a knowledge base is for here and why three
 * unrelated-looking apps sit next to each other. The landing page
 * explains it, and then you sign in and the explanation is gone.
 *
 * It carries the pipeline, so the pipeline is stated where it explains
 * something rather than as a legend in the last panel of the right-hand
 * column, which is where it used to live. Down one rail rather than
 * across three boxes: the order is the point, and boxes of equal weight
 * do not show order.
 *
 * It also carries the only button that starts anything. Nothing in this
 * product happens until a codebase has been read, and that step used to
 * sit in a band of its own below — one more thing to scan past. Which
 * is why this band has no collapse: an entry point you can hide is not
 * one.
 * ------------------------------------------------------------------ */

const STEPS = [
  {
    label: 'Analyse',
    desc: 'Walk every file. Routes, entry points, module boundaries, dependencies — pinned to the commit it read.',
  },
  {
    label: 'Unlock',
    desc: 'Documentation, Ask the code and Quality become available together. They read one knowledge base.',
  },
  {
    label: 'Use',
    desc: 'Each app retrieves what it needs. None of them reads the repository again.',
  },
]

export default function HomeBanner({ projects }: { projects: Project[] | null }) {
  const none = projects !== null && projects.length === 0
  const unread = (projects ?? []).filter(p => !p.apps_ready).length

  return (
    <section className="mb-5 border border-rule bg-panel">
      <div className="tag flex items-center gap-2 border-b border-rule bg-sunk/60 px-4 py-2 text-ink-dim">
        <span className="block size-[6px] shrink-0 rotate-45 bg-hot" />
        <span className="truncate">Codelith — local-first code intelligence</span>
        <span className="ml-auto flex shrink-0 items-center gap-1.5 text-ok">
          <span className="block size-[5px] rounded-full bg-ok" />
          runs fully offline
        </span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        <div className="border-b border-rule px-5 py-6 lg:border-r lg:border-b-0">
          <h2 className="mb-3.5 text-[clamp(21px,2.6vw,30px)] leading-[1.06] font-bold tracking-[-0.035em] text-ink">
            Read the codebase once.
            <br />
            Use it <span className="text-hot">many times.</span>
          </h2>

          <p className="mb-5 max-w-[58ch] font-sans text-[12.5px] leading-[1.65] text-ink-mid">
            Point Codelith at a repository. It reads every file and builds a structured
            knowledge base of what is actually there — not a summary of it.{' '}
            <strong className="font-semibold text-ink">
              That knowledge base is the product.
            </strong>{' '}
            Everything below is something you do with it, and none of it leaves your
            machine.
          </p>

          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <Link
              to="/app/projects?new=1"
              className="tag inline-flex items-center border border-hot bg-hot px-4 py-2.5 text-on-hot transition-colors hover:border-hot-press hover:bg-hot-press"
            >
              {none ? 'Get started' : 'Add a codebase'} →
            </Link>
            <span className="font-sans text-[11px] leading-snug text-ink-dim">
              {none
                ? 'Nothing happens until a codebase has been read.'
                : unread
                  ? `${unread} codebase${unread > 1 ? 's have' : ' has'} not been read yet.`
                  : 'Add another repository, or upload a folder to read.'}
            </span>
          </div>
        </div>

        {/* The pipeline, down one rail. */}
        <ol className="flex flex-col justify-center px-5 py-6">
          {STEPS.map((s, i) => (
            <li key={s.label} className="relative flex gap-3 pb-4 last:pb-0">
              {/* The rail joins a step to the next one, so the last has none. */}
              {i < STEPS.length - 1 && (
                <span
                  aria-hidden
                  className="absolute top-[19px] bottom-0 left-[9px] w-px bg-rule"
                />
              )}
              <span className="relative z-10 flex size-[19px] shrink-0 items-center justify-center border border-rule bg-panel text-[9.5px] font-bold text-ink-dim">
                {i + 1}
              </span>
              <div className="min-w-0 pt-px">
                <div className="text-[11.5px] font-semibold text-ink">{s.label}</div>
                <p className="mt-0.5 font-sans text-[11px] leading-[1.55] text-ink-dim">
                  {s.desc}
                </p>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}
