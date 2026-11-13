import { Link } from 'react-router-dom'
import { BrandMark } from '../../lib/brands'
import { Icon } from '../../lib/icons'
import { APP_LOOKS } from '../../lib/kinds'
import { useReducedMotion } from '../../lib/motion'

/* ------------------------------------------------------------------ *
 * What Codelith does, drawn as what happens: a repository is read once,
 * what was learned is kept, and four things read it. Icons and motion,
 * not boxes: the repository's hosts take turns, the reading sweeps, the
 * knowledge base glows as it fills, and dots run along every link the
 * way the data goes.
 * ------------------------------------------------------------------ */

const APPS = [
  { look: APP_LOOKS.graph, to: '/app/projects', line: 'How the parts connect, and what breaks' },
  { look: APP_LOOKS.assistant, to: '/app/chat', line: 'Answers with checked citations' },
  { look: APP_LOOKS.changes, to: '/app/projects', line: 'What moved between two readings' },
  { look: APP_LOOKS.documentation, to: '/app/documentation', line: 'Pages written from the code' },
]

/** A link between two stages, with a dot travelling along it. */
function Hop({ delay = 0 }: { delay?: number }) {
  return (
    <>
      <div className="relative hidden h-16 min-w-[44px] flex-1 items-center lg:flex" aria-hidden>
        <span className="h-px w-full bg-[linear-gradient(90deg,var(--line-2),var(--hot-edge))]" />
        <span
          className="absolute top-1/2 size-[6px] -translate-y-1/2 rounded-full bg-hot shadow-[0_0_10px_var(--hot)]"
          style={{ animation: `pipe-travel-x 2.4s ${delay}s cubic-bezier(.4,0,.2,1) infinite` }}
        />
        <Icon name="chevron-right" size={14} className="-ml-1.5 shrink-0 text-hot-edge" />
      </div>
      <div className="relative ml-[31px] h-6 w-px bg-line-2 lg:hidden" aria-hidden>
        <span
          className="absolute left-1/2 size-[5px] -translate-x-1/2 rounded-full bg-hot"
          style={{ animation: `pipe-travel-y 1.8s ${delay}s ease-in-out infinite` }}
        />
      </div>
    </>
  )
}

function Stage({ art, title, line }: { art: React.ReactNode; title: string; line: string }) {
  return (
    // On a wide screen the caption hangs under the icon, so the links run through the
    // icons' centres rather than past them.
    <div className="relative flex shrink-0 items-center gap-4 lg:w-[176px] lg:justify-center">
      <div className="relative grid size-16 shrink-0 place-items-center">{art}</div>
      <div className="min-w-0 lg:absolute lg:top-full lg:left-0 lg:mt-2 lg:w-full lg:text-center">
        <div className="text-[14px] font-semibold text-ink">{title}</div>
        <div className="text-[12.5px] leading-snug text-ink-dim">{line}</div>
      </div>
    </div>
  )
}

/** The repository's hosts, each lighting in turn. */
function Sources() {
  const cell = (k: number) => ({ animation: `pipe-cycle 4.8s ${k * 1.2}s ease-in-out infinite` })
  return (
    <div className="grid grid-cols-2 gap-2.5">
      <span style={cell(0)} className="grid place-items-center">
        <BrandMark name="github" size={21} decorative />
      </span>
      <span style={cell(1)} className="grid place-items-center">
        <BrandMark name="gitlab" size={21} decorative />
      </span>
      <span style={cell(3)} className="grid place-items-center">
        <Icon name="folder" size={21} className="text-ink-mid" />
      </span>
      <span style={cell(2)} className="grid place-items-center">
        <BrandMark name="bitbucket" size={21} decorative />
      </span>
    </div>
  )
}

/** One reading: a radar's sweep over the files. */
function Reading() {
  return (
    <>
      <span
        className="absolute inset-0 rounded-full"
        style={{
          background: 'conic-gradient(from 0deg, transparent 0 70%, color-mix(in srgb, var(--hot) 40%, transparent) 100%)',
          animation: 'spin 2.8s linear infinite',
          maskImage: 'radial-gradient(circle, black 62%, transparent 70%)',
        }}
        aria-hidden
      />
      <Icon name="radar" size={30} className="relative text-hot-ink" />
    </>
  )
}

/** The knowledge base, glowing as it fills. */
function Store() {
  return (
    <>
      <span
        className="absolute size-11 rounded-full bg-hot blur-xl"
        style={{ animation: 'pipe-glow 3.2s ease-in-out infinite' }}
        aria-hidden
      />
      <Icon name="database" size={30} className="relative text-ink" />
    </>
  )
}

/** The fan from the knowledge base to the four apps, dots running out along it. */
function Fan() {
  const reduced = useReducedMotion()
  const rows = APPS.map((_, k) => 24 + k * 58)
  const mid = (rows[0] + rows[rows.length - 1]) / 2
  return (
    <svg width="72" height={rows[rows.length - 1] + 24} className="hidden shrink-0 lg:block" aria-hidden>
      {rows.map((y, k) => {
        const d = `M0,${mid} C40,${mid} 32,${y} 72,${y}`
        return (
          <g key={k}>
            <path d={d} fill="none" stroke="var(--line-2)" strokeWidth="1.2" />
            {!reduced && (
              <circle r="2.8" fill={APPS[k].look.color} style={{ filter: `drop-shadow(0 0 4px ${APPS[k].look.color})` }}>
                <animateMotion dur="2.4s" begin={`-${k * 0.6}s`} repeatCount="indefinite" path={d} />
              </circle>
            )}
          </g>
        )
      })}
    </svg>
  )
}

export default function Pipeline() {
  return (
    <section aria-label="How Codelith works" className="flex flex-col gap-0 border-t border-rule pt-8 lg:flex-row lg:items-center lg:gap-1">
      <Stage art={<Sources />} title="Your repository" line="GitHub, GitLab, Bitbucket or a folder" />
      <Hop />
      <Stage art={<Reading />} title="One reading" line="Every file, once, pinned to its commit" />
      <Hop delay={0.8} />
      <Stage art={<Store />} title="Knowledge base" line="Files, imports, calls, facts and prose" />
      <Hop delay={1.6} />
      <div className="flex items-center">
        <Fan />
        <ul className="grid grid-cols-1 gap-y-2.5 pl-[18px] sm:grid-cols-2 sm:gap-x-6 lg:flex lg:flex-col lg:gap-[10px] lg:pl-1">
          {APPS.map(a => (
            <li key={a.look.label}>
              <Link
                to={a.to}
                className="group flex h-12 items-center gap-3 rounded-lg px-2 transition-colors hover:bg-hover"
              >
                <Icon
                  name={a.look.icon}
                  size={20}
                  style={{ color: a.look.color, filter: `drop-shadow(0 0 6px color-mix(in srgb, ${a.look.color} 55%, transparent))` }}
                />
                <span className="min-w-0">
                  <span className="block text-[14px] font-medium text-ink">{a.look.label}</span>
                  <span className="block truncate text-[12px] text-ink-dim">{a.line}</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}
