import type { ReactNode } from 'react'
import { GitHubMark, Logo } from '../../components/ui'

/* ------------------------------------------------------------------ *
 * The front door.
 *
 * It used to be a split: the pitch on a blueprint ground to the left,
 * the form in a fixed 420px column pinned to the right edge. That reads
 * on a laptop and falls apart on a wide monitor, where the form ends up
 * against the far edge of a three-thousand-pixel screen with an acre of
 * empty grid beside it and nothing in the middle where the eye goes.
 *
 * So it is one column, centred, at a width that does not change. The
 * mark and the name are the first thing and they are large, because this
 * is the only screen in the product whose job is to say which
 * application you have opened. The pitch is two lines under it, the form
 * is a plate in the middle of the page, and the proof sits underneath
 * where it supports the claim rather than competing with it.
 *
 * The copy matches Home. The old lines here still said "documentation
 * studio", which was the product's first framing and has not been true
 * since analysis became the thing and documentation became one of three
 * apps reading it. Somebody should not meet one claim at the door and a
 * different one a second later.
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
      {/* The same strip Home opens with, so the door and the room behind it are
          recognisably one place. */}
      <div className="tag flex items-center gap-2 border-b border-rule bg-panel px-4 py-2 text-ink-dim">
        <span className="block size-[6px] shrink-0 rotate-45 bg-hot" />
        <span className="truncate">Codelith, local-first code intelligence</span>
        <span className="ml-auto flex shrink-0 items-center gap-1.5 text-ok">
          <span className="block size-[5px] rounded-full bg-ok" />
          runs fully offline
        </span>
      </div>

      <div className="flex flex-1 items-center justify-center px-5 py-10">
        <div className="w-full max-w-[440px]">
          <div className="mb-7 flex flex-col items-center text-center">
            <Logo size={46} />
            <span className="mt-3 text-[27px] leading-none font-bold tracking-[-0.04em] text-ink">
              code<span className="text-hot">·</span>lith
            </span>

            <h1 className="mt-5 text-[clamp(22px,3.4vw,30px)] leading-[1.05] font-bold tracking-[-0.04em] text-ink">
              Read the codebase once.
              <br />
              Use it <span className="text-hot">many times.</span>
            </h1>
            <p className="mt-3 max-w-[40ch] font-sans text-[12.5px] leading-[1.65] text-ink-mid">
              Analyse a repository once, then documentation, answers and change reports
              all read the same evidence. Everything runs against a local model, and no
              code leaves this machine.
            </p>
          </div>

          {/* The form, on a plate. The number keeps the studio's habit of counting the
              step you are on, and it is the only ornament this card gets. */}
          <div className="border border-rule bg-panel">
            <div className="flex items-end gap-3 border-b border-rule px-5 py-3.5">
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

            <div className="px-5 py-5">{children}</div>

            <div className="border-t border-rule px-5 py-3 text-[11px] text-ink-mid">
              {footer}
            </div>
          </div>

          {/* Underneath the form rather than beside it: this is the reason to trust
              the box you are about to type a password into, and it reads as support
              for the claim above only when it comes after it. */}
          <div className="mt-5 grid grid-cols-3 gap-px border border-rule bg-rule">
            {[
              ['zero', 'bytes uploaded'],
              ['20', 'local agents'],
              ['1', 'read per commit'],
            ].map(([v, k]) => (
              <div key={k} className="bg-panel px-2.5 py-2 text-center">
                <div className="text-[15px] leading-none font-bold text-ink">{v}</div>
                <div className="tag mt-1 text-ink-dim">{k}</div>
              </div>
            ))}
          </div>

          <a
            href="https://github.com/codelith"
            target="_blank"
            rel="noreferrer"
            className="tag mx-auto mt-5 flex w-fit items-center gap-1.5 text-ink-dim transition-colors hover:text-ink"
          >
            <GitHubMark size={12} /> github.com/codelith
          </a>
        </div>
      </div>
    </div>
  )
}
