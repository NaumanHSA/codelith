import type { ReactNode } from 'react'
import { Logo } from '../../components/ui'
import { BrandMark } from '../../lib/brands'
import { Icon, type IconName } from '../../lib/icons'

/* ------------------------------------------------------------------ *
 * The front door, in the studio's own look: what Codelith is on the
 * left, the form on the right, one panel centred on the page.
 *
 * It used to quote figures ("20 local agents") and a licence ("MIT")
 * that were not true of the repository; the licence is Apache-2.0, and
 * the three points below are claims the product makes good on.
 * ------------------------------------------------------------------ */

const POINTS: { icon: IconName; title: string; line: string }[] = [
  { icon: 'shield-check', title: 'Stays on this machine', line: 'Code, readings and answers never leave it.' },
  { icon: 'radar', title: 'Read once per commit', line: 'Every app reads the same stored reading.' },
  { icon: 'quote', title: 'Answers you can check', line: 'Every citation is verified against what was retrieved.' },
]

export default function AuthLayout({
  title,
  sub,
  children,
  footer,
}: {
  /** Accepted for the old call sites; no longer drawn. */
  index?: string
  title: string
  sub: string
  children: ReactNode
  footer: ReactNode
}) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-paper px-5 py-10">
      <div className="anim-rise w-full max-w-[980px] overflow-hidden rounded-2xl border border-line-2 bg-panel shadow-[0_40px_100px_-40px_var(--shadow)]">
        <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,400px)]">
          <div className="flex flex-col gap-6 border-b border-rule p-8 lg:border-r lg:border-b-0">
            <div className="flex items-center gap-2.5">
              <Logo size={28} />
              <span className="font-head text-[19px] font-semibold tracking-[-0.01em] text-ink">Codelith</span>
            </div>
            <div className="flex flex-col gap-3">
              <h1 className="max-w-[16ch] text-[32px] leading-[1.1] font-semibold text-ink">
                Read a codebase once. <span className="text-hot-ink">Use it many times.</span>
              </h1>
              <p className="max-w-[46ch] text-[14px] leading-relaxed text-ink-mid">
                Analyse a repository once, then a map of what breaks, answers with citations, change
                reports and documentation all read the same evidence.
              </p>
            </div>
            <ul className="flex flex-col gap-3">
              {POINTS.map(p => (
                <li key={p.title} className="flex items-start gap-3">
                  <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-sunk shadow-[inset_0_0_0_1px_var(--line-2)]">
                    <Icon name={p.icon} size={16} className="text-hot-ink" />
                  </span>
                  <span>
                    <span className="block text-[13.5px] font-medium text-ink">{p.title}</span>
                    <span className="block text-[12.5px] text-ink-mid">{p.line}</span>
                  </span>
                </li>
              ))}
            </ul>
            <div className="mt-auto flex flex-wrap items-center gap-x-4 gap-y-1 text-[12.5px] text-ink-dim">
              <a
                href="https://github.com/NaumanHSA/codelith"
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-1.5 transition-colors hover:text-ink"
              >
                <BrandMark name="github" size={13} decorative /> NaumanHSA/codelith
              </a>
              <span>Open source, Apache-2.0</span>
            </div>
          </div>

          <div className="flex flex-col justify-center p-8">
            <div className="mb-6">
              <h2 className="text-[20px] leading-tight font-semibold text-ink">{title}</h2>
              <p className="mt-1 text-[13px] text-ink-mid">{sub}</p>
            </div>
            {children}
            <div className="mt-6 border-t border-rule pt-4 text-[13px] text-ink-mid">{footer}</div>
          </div>
        </div>
      </div>
    </div>
  )
}
