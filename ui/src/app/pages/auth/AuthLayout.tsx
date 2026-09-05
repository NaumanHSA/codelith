import type { ReactNode } from 'react'
import { GitHubMark, Logo } from '../../components/ui'

/* Split front door: evidence on the left, the form on the right. */
export default function AuthLayout({
  index, title, sub, children, footer,
}: {
  index: string
  title: string
  sub: string
  children: ReactNode
  footer: ReactNode
}) {
  return (
    <div className="grid min-h-screen grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,420px)]">
      {/* left: the pitch, on the blueprint ground */}
      <section className="bp-grid hidden flex-col justify-between border-r border-rule p-8 lg:flex">
        <div className="flex w-fit items-center gap-2">
          <Logo size={17} />
          <span className="text-[11.5px] font-bold tracking-tight text-ink">
            code<span className="text-hot">·</span>lith
          </span>
        </div>

        <div className="max-w-[46ch]">
          <p className="tag mb-3 text-hot-ink">Local documentation studio</p>
          <h1 className="mb-4 text-[clamp(26px,3.6vw,42px)] leading-[0.98] font-bold tracking-[-0.04em] text-ink">
            Documentation that
            <br />
            reads your code first.
          </h1>
          <p className="font-sans text-[13.5px] leading-[1.7] text-ink-mid">
            Analyse a repository once, then write as many documents as you need from the same
            evidence. Everything runs against a local model. No code leaves this machine.
          </p>

          <div className="mt-6 grid max-w-[380px] grid-cols-3 gap-px border border-rule bg-rule">
            {[
              ['zero', 'bytes uploaded'],
              ['14', 'local agents'],
              ['1', 'read per commit'],
            ].map(([v, k]) => (
              <div key={k} className="bg-panel px-2.5 py-2">
                <div className="text-[15px] leading-none font-bold text-ink">{v}</div>
                <div className="tag mt-1 text-ink-dim">{k}</div>
              </div>
            ))}
          </div>
        </div>

        <a
          href="https://github.com/codelith"
          target="_blank"
          rel="noreferrer"
          className="tag flex w-fit items-center gap-1.5 text-ink-dim transition-colors hover:text-ink"
        >
          <GitHubMark size={12} /> github.com/codelith
        </a>
      </section>

      {/* right: the form */}
      <section className="flex flex-col justify-center bg-panel px-5 py-10 sm:px-8">
        <div className="mb-8 flex w-fit items-center gap-2 lg:hidden">
          <Logo size={17} />
          <span className="text-[11.5px] font-bold tracking-tight text-ink">
            code<span className="text-hot">·</span>lith
          </span>
        </div>

        <div className="mb-5 flex items-end gap-3 border-b border-rule pb-3">
          <span className="text-[30px] leading-[0.8] font-bold tracking-tighter text-rule select-none">
            {index}
          </span>
          <div>
            <h2 className="text-[17px] leading-tight font-bold tracking-tight text-ink">{title}</h2>
            <p className="mt-1 text-[11px] text-ink-dim">{sub}</p>
          </div>
        </div>

        {children}

        <div className="mt-5 border-t border-rule pt-3 text-[11px] text-ink-mid">{footer}</div>
      </section>
    </div>
  )
}
