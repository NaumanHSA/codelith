import type { ReactNode } from 'react'
import { Chip, GitHubMark, Logo } from '../../components/ui'

/* ------------------------------------------------------------------ *
 * The front door.
 *
 * Home's banner, with the form where the terminal sits. Somebody signs
 * in and lands on a page laid out the same way, so the door and the room
 * behind it are recognisably one place: the same identity strip along
 * the top, the same chips, the same headline, the same plate split into
 * a claim on the left and something concrete on the right.
 *
 * Two earlier attempts were wrong in opposite directions. The first was
 * a full-width split, which put the form against the right edge of a
 * wide monitor with an acre of empty grid beside it. The second centred
 * everything, including the text, which fixed the position and lost the
 * page: centred paragraphs under a centred mark read as a placeholder,
 * because nothing has a left edge to start from.
 *
 * So the plate is centred and everything inside it is not. One ragged
 * left edge runs down the mark, the chips, the headline, the paragraph
 * and the figures, which is what makes it read as a page rather than as
 * a dialog box.
 * ------------------------------------------------------------------ */

export default function AuthLayout({
  index,
  title,
  sub,
  children,
  footer,
}: {
  index: string
  title: string
  sub: string
  children: ReactNode
  footer: ReactNode
}) {
  return (
    <div className="bp-grid flex min-h-screen flex-col">
      <div className="tag flex items-center gap-2 border-b border-rule bg-panel px-4 py-2 text-ink-dim">
        <span className="block size-[6px] shrink-0 rotate-45 bg-hot" />
        <span className="truncate">Codelith, local-first code intelligence</span>
        <span className="ml-auto flex shrink-0 items-center gap-1.5 text-ok">
          <span className="block size-[5px] rounded-full bg-ok" />
          runs fully offline
        </span>
      </div>

      <div className="flex flex-1 items-center justify-center px-5 py-9">
        <div className="w-full max-w-[1040px] border border-rule bg-panel">
          <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,400px)]">
            {/* The claim. */}
            <div className="border-b border-rule px-7 py-8 lg:border-r lg:border-b-0">
              <div className="mb-6 flex items-center gap-2.5">
                <Logo size={30} />
                <span className="text-[21px] leading-none font-bold tracking-[-0.04em] text-ink">
                  code<span className="text-hot">·</span>lith
                </span>
              </div>

              <div className="mb-5 flex flex-wrap gap-1.5">
                <Chip>open source</Chip>
                <Chip>MIT</Chip>
                <Chip>self-hosted</Chip>
                <Chip tone="hot">● runs fully offline</Chip>
              </div>

              <h1 className="mb-4 text-[clamp(24px,3.2vw,36px)] leading-[0.98] font-bold tracking-[-0.045em] text-ink">
                Read the codebase
                <br />
                once. Use it{' '}
                <span className="relative inline-block">
                  <span className="relative z-10 text-hot">many times.</span>
                  <span className="absolute inset-x-0 bottom-[0.1em] z-0 h-[0.16em] bg-hot/20" />
                </span>
              </h1>

              <p className="mb-6 max-w-[46ch] font-sans text-[13px] leading-[1.7] text-ink-mid">
                Analyse a repository once, then documentation, answers and change reports
                all read the same evidence. Everything runs against a local model, and no
                code leaves this machine.
              </p>

              {/* The reason to trust the box on the right. */}
              <div className="grid max-w-[400px] grid-cols-3 gap-px border border-rule bg-rule">
                {[
                  ['zero', 'bytes uploaded'],
                  ['20', 'local agents'],
                  ['1', 'read per commit'],
                ].map(([v, k]) => (
                  <div key={k} className="bg-panel px-2.5 py-2">
                    <div className="text-[15px] leading-none font-bold text-ink">{v}</div>
                    <div className="tag mt-1 text-ink-dim">{k}</div>
                  </div>
                ))}
              </div>

              <a
                href="https://github.com/codelith"
                target="_blank"
                rel="noreferrer"
                className="tag mt-6 flex w-fit items-center gap-1.5 text-ink-dim transition-colors hover:text-ink"
              >
                <GitHubMark size={12} /> github.com/codelith
              </a>
            </div>

            {/* The form, where Home puts the specimen run. */}
            <div className="flex flex-col justify-center px-6 py-8">
              <div className="mb-5 flex items-end gap-3 border-b border-rule pb-3">
                <span className="text-[30px] leading-[0.8] font-bold tracking-tighter text-rule select-none">
                  {index}
                </span>
                <div className="min-w-0">
                  <h2 className="text-[17px] leading-tight font-bold tracking-tight text-ink">
                    {title}
                  </h2>
                  <p className="mt-1 text-[11px] text-ink-dim">{sub}</p>
                </div>
              </div>

              {children}

              <div className="mt-5 border-t border-rule pt-3 text-[11px] text-ink-mid">
                {footer}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
