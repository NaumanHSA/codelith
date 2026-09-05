import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Chip } from '../ui'
import type { Project } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * What this is, and where you start — said once, at the top of Home.
 *
 * This is the landing page's hero, moved. There is no landing page any
 * more: the application opens on the sign-in form and then the studio,
 * so the one explanation of what a knowledge base is for, and why three
 * unrelated-looking apps sit next to each other, had nowhere left to
 * live. It reads the same here — a reader who has just signed in is
 * exactly the reader it was written for.
 *
 * Two things change in the move.
 *
 * The buttons. "Open the studio" is meaningless once you are in it, and
 * "Read the source" belongs on a page for people deciding whether to
 * install this. In their place the two that matter here: nothing in this
 * product happens until a codebase has been read, and the way back to
 * one already read is the step between Home and any app.
 *
 * The terminal is marked as an example. On a marketing page a specimen
 * run reads as a specimen; on a dashboard, above a panel of the reader's
 * own jobs, "job #38" reads as one of theirs — and neurosurfer is not
 * their repository. The numbers are honest about the product and dishonest
 * about whose they are, so the header says which.
 * ------------------------------------------------------------------ */

/** The specimen run. Illustrative — see the note above. */
const TERMINAL = [
  { t: 'cmd', s: '$ codelith analyse github.com/acme/neurosurfer' },
  { t: 'ok', s: '  ✓ repo_analyzer        257 files · 45 modules          3.7s' },
  { t: 'ok', s: '  ✓ structured_extractor 45 modules · 77 facts          141ms' },
  { t: 'ok', s: '  ✓ semantic_indexer     1,103 chunks · pgvector          21s' },
  { t: 'ok', s: '  ✓ module_summarizer    40/40 summarised                 13s' },
  { t: 'ok', s: '  ✓ architecture_synth   5 components mapped              93s' },
  { t: 'live', s: '  … narrative_writer     writing 6 narratives…' },
]

export default function HomeBanner({ projects }: { projects: Project[] | null }) {
  const none = projects !== null && projects.length === 0
  const unread = (projects ?? []).filter(p => !p.apps_ready).length

  // The run types itself out. It is the only thing on Home that shows what analysis
  // actually does rather than describing it.
  const [lines, setLines] = useState(1)
  useEffect(() => {
    if (lines >= TERMINAL.length) return
    const t = setTimeout(() => setLines(v => v + 1), 480)
    return () => clearTimeout(t)
  }, [lines])

  const cta = 'tag inline-flex items-center justify-center gap-1.5 border transition-colors'

  return (
    <section className="bp-grid border-b border-rule">
      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
        <div className="border-rule px-5 py-10 lg:border-r lg:py-12">
          <div className="mb-5 flex flex-wrap gap-1.5">
            <Chip>open source</Chip>
            <Chip>MIT</Chip>
            <Chip>self-hosted</Chip>
            <Chip tone="hot">● runs fully offline</Chip>
          </div>

          <h1 className="mb-5 text-[clamp(28px,4.4vw,52px)] leading-[0.95] font-bold tracking-[-0.045em] text-ink">
            Read the codebase
            <br />
            once. Use it
            <br />
            <span className="relative inline-block">
              <span className="relative z-10 text-hot">many times.</span>
              <span className="absolute inset-x-0 bottom-[0.1em] z-0 h-[0.16em] bg-hot/20" />
            </span>
          </h1>

          <p className="mb-4 max-w-[52ch] font-sans text-[14px] leading-[1.7] text-ink-mid">
            Point Codelith at a repository. It walks every file and builds a structured
            knowledge base of routes, entry points, module boundaries and dependencies,
            pinned to the commit it read.
          </p>
          <p className="mb-6 max-w-[52ch] font-sans text-[14px] leading-[1.7] text-ink-mid">
            That knowledge base is the product. Everything else reads it:{' '}
            <strong className="font-semibold text-ink">write documentation</strong>,{' '}
            <strong className="font-semibold text-ink">ask the code questions</strong>.
            None of them open the repository again, and it all runs on your machine
            against a local LLM.{' '}
            <strong className="font-semibold text-ink">No code leaves the box.</strong>
          </p>

          <div className="flex flex-wrap items-center gap-2">
            <Link
              to="/app/projects?new=1"
              className={`${cta} border-hot bg-hot px-5 py-2.5 text-on-hot hover:border-hot-press hover:bg-hot-press`}
            >
              {none ? 'Get started' : 'Add a codebase'} →
            </Link>
            {/* The way in to work already done. Everything an app does happens on one
                codebase, so opening one is the step between Home and any of them. */}
            {!none && (
              <Link
                to="/app/projects"
                className={`${cta} border-rule bg-panel px-4 py-[10px] text-ink-mid hover:border-ink hover:text-ink`}
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
          </div>
        </div>

        <div className="flex flex-col justify-center border-t border-rule px-5 py-8 lg:border-t-0">
          <div className="border border-ink bg-term">
            <div className="tag flex items-center gap-2 border-b border-term-rule px-3 py-2 text-term-dim">
              <span className="size-[6px] rotate-45 bg-hot" />
              example run · analysis
              <span className="ml-auto">local</span>
            </div>
            <div className="px-3 py-2.5">
              {TERMINAL.slice(0, lines).map((l, i) => (
                <div
                  key={i}
                  className={`anim-rise overflow-x-auto text-[11px] leading-[1.75] whitespace-pre ${
                    l.t === 'cmd'
                      ? 'text-on-ink'
                      : l.t === 'live'
                        ? 'text-term-dim'
                        : 'text-term-ok'
                  }`}
                >
                  {l.s}
                  {l.t === 'live' && i === lines - 1 && (
                    <span className="anim-blink text-hot">▌</span>
                  )}
                </div>
              ))}
            </div>
            <div className="tag flex items-center gap-2 border-t border-term-rule px-3 py-1.5 text-term-dim">
              <span>elapsed 2m 32s</span>
              <span className="ml-auto text-hot">6/7 stages</span>
            </div>
          </div>

          <div className="mt-3 grid grid-cols-3 gap-px border border-rule bg-rule">
            {[
              ['zero', 'bytes uploaded'],
              ['20', 'local agents'],
              ['1', 'read per commit'],
            ].map(([v, k]) => (
              <div key={k} className="bg-panel px-2.5 py-2">
                <div className="text-[16px] leading-none font-bold text-ink">{v}</div>
                <div className="tag mt-1 text-ink-dim">{k}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}
