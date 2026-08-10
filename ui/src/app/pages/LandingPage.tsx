import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth'
import { Chip, GitHubMark, Logo } from '../components/ui'

const STAGES = [
  {
    num: '01',
    name: 'Analyse',
    tagline: 'Extract the facts',
    desc: 'Clones the repository and walks every file. Records what is actually there — HTTP routes, entry points, module boundaries, dependencies, config, data stores. Nothing is inferred.',
    facts: [
      ['files walked', '257'],
      ['modules mapped', '45'],
      ['HTTP routes', '28'],
      ['data stores', '2'],
    ],
  },
  {
    num: '02',
    name: 'Knowledge base',
    tagline: 'Build the index',
    desc: 'Chunks and embeds every finding into a structured store pinned to the commit SHA. The knowledge base is the product of analysis — written once, reused by every document you ask for.',
    facts: [
      ['chunks embedded', '1,103'],
      ['commit', '4865c2f'],
      ['index size', '4.2 MB'],
      ['cross-refs', '847'],
    ],
  },
  {
    num: '03',
    name: 'Unlock',
    tagline: 'See what the codebase offers',
    desc: 'Analysis has already run, so the studio knows what exists. Documentation and Ask the code become available together, and the document types offered are the ones the evidence supports — an API Reference only when routes were found, and it says how many.',
    facts: [
      ['Architecture', '90% →'],
      ['Getting Started', '70% →'],
      ['Module docs', '60% →'],
      ['API Reference', '28 routes'],
    ],
  },
  {
    num: '04',
    name: 'Use',
    tagline: 'Retrieve, then work',
    desc: 'Every feature pulls the slice of the knowledge base it needs and nothing more. Documentation retrieves per section, writes prose and runs QA against source. Ask retrieves per question and checks every citation it produces. Neither opens the repository again.',
    facts: [
      ['repo reads', '0'],
      ['retrieval', 'per section'],
      ['QA', 'against source'],
      ['citations', 'checked'],
    ],
  },
]

/**
 * What the knowledge base unlocks.
 *
 * Mirrors `app/features/registry.py` — deliberately, and only in copy: a marketing
 * page that lists a feature the studio does not offer is the worst kind of lie,
 * because the reader finds out after signing up. Anything added here must exist in
 * the registry first.
 */
const SERVICES = [
  {
    id: '01',
    name: 'Codelith Docs',
    label: 'Documentation',
    line: 'Documents written from the analysis, not from a chat session.',
    desc:
      'Architecture guides, API references, getting-started guides, module docs. Document types are offered from what the code actually contains — an API reference appears when routes were found, and it says how many. Each section retrieves its own slice of the knowledge base, gets a QA pass against source, and comes out as Markdown, DOCX, MkDocs or Docusaurus.',
    facts: [
      ['offered from', 'evidence'],
      ['QA', 'against source'],
      ['formats', '4'],
      ['re-reads repo', 'never'],
    ],
  },
  {
    id: '02',
    name: 'Codelith Ask',
    label: 'Ask the code',
    line: 'Questions answered from the source, with citations that are checked.',
    desc:
      'Ask in English and get an answer grounded in the repository. Every citation is verified against the evidence actually retrieved, and one that does not resolve is stripped rather than shown — a chat that merely sounds grounded is worse than one that obviously guesses. When one retrieval pass is not enough it looks further, using tools over the knowledge base and the code graph.',
    facts: [
      ['citations', 'checked'],
      ['unresolved', 'stripped'],
      ['escalates', 'with tools'],
      ['conversations', 'kept'],
    ],
  },
]

const TERMINAL = [
  { t: 'cmd', s: '$ codelith analyse github.com/acme/neurosurfer' },
  { t: 'ok', s: '  ✓ repo_analyzer        257 files · 45 modules          3.7s' },
  { t: 'ok', s: '  ✓ structured_extractor 45 modules · 77 facts          141ms' },
  { t: 'ok', s: '  ✓ semantic_indexer     1,103 chunks · pgvector          21s' },
  { t: 'ok', s: '  ✓ module_summarizer    40/40 summarised                 13s' },
  { t: 'ok', s: '  ✓ architecture_synth   5 components mapped              93s' },
  { t: 'live', s: '  … narrative_writer     writing 6 narratives…' },
]

const AGENTS = [
  'repo_analyzer', 'structured_extractor', 'semantic_indexer', 'module_summarizer',
  'architecture_synthesizer', 'narrative_writer', 'kb_persister', 'composition_strategy',
  'composition_planner', 'composition_writer', 'diagram_agent', 'qa_agent', 'formatter',
  'publisher',
]

/** The four-stage pipeline as a live schematic. */
function FlowDiagram({ active }: { active: number }) {
  const cols = [40, 175, 310, 445]
  const on = (i: number) => i <= active

  return (
    <svg viewBox="0 0 540 150" className="w-full" role="img" aria-label="Four-stage pipeline">
      <defs>
        <pattern id="fg" width="12" height="12" patternUnits="userSpaceOnUse">
          <path d="M12 0H0V12" fill="none" stroke="var(--grid-line)" />
        </pattern>
      </defs>
      <rect width="540" height="150" fill="url(#fg)" />

      {[0, 1, 2].map(i => {
        const x1 = cols[i] + 78
        const x2 = cols[i + 1] + 2
        const live = on(i + 1)
        return (
          <g key={i}>
            <line x1={x1} y1="62" x2={x2} y2="62" stroke="var(--rule)" strokeWidth="1.5" />
            {live && (
              <line
                x1={x1} y1="62" x2={x2} y2="62"
                stroke="var(--hot)" strokeWidth="1.5" className="anim-flow"
              />
            )}
            <path
              d={`M${x2 - 6} 58 L${x2} 62 L${x2 - 6} 66`}
              fill="none"
              stroke={live ? 'var(--hot)' : 'var(--rule)'}
              strokeWidth="1.5"
            />
          </g>
        )
      })}

      {STAGES.map((s, i) => {
        const x = cols[i]
        const cur = i === active
        const past = i < active
        return (
          <g key={s.num} style={{ transition: 'opacity .2s' }} opacity={past || cur ? 1 : 0.4}>
            {cur && (
              <rect
                x={x - 3} y="27" width="86" height="70"
                fill="none" stroke="var(--hot)" strokeWidth="1" strokeDasharray="3 3"
              />
            )}
            <rect
              x={x} y="30" width="80" height="64"
              fill={cur ? 'var(--hot-wash)' : 'var(--panel)'}
              stroke={cur ? 'var(--hot)' : 'var(--ink)'}
              strokeWidth={cur ? 2 : 1.2}
            />
            <text
              x={x + 7} y="45" fontSize="8" fontWeight="700" letterSpacing="0.1em"
              fill={cur ? 'var(--hot-ink)' : 'var(--ink-dim)'} fontFamily="var(--font-mono)"
            >
              {s.num}
            </text>
            <text
              x={x + 7} y="62" fontSize="11" fontWeight="700"
              fill="var(--ink)" fontFamily="var(--font-mono)"
            >
              {s.name.split(' ')[0]}
            </text>
            {s.name.includes(' ') && (
              <text
                x={x + 7} y="75" fontSize="11" fontWeight="700"
                fill="var(--ink)" fontFamily="var(--font-mono)"
              >
                {s.name.split(' ')[1]}
              </text>
            )}
            <rect
              x={x + 7} y="82" width={cur ? 40 : 18} height="3"
              fill={cur ? 'var(--hot)' : 'var(--rule)'}
              style={{ transition: 'width .3s' }}
            />
            {cur && (
              <circle cx={x + 74} cy="38" r="3" fill="var(--hot)">
                <animate attributeName="opacity" values="1;.2;1" dur="1.3s" repeatCount="indefinite" />
              </circle>
            )}
          </g>
        )
      })}

      <line x1="525" y1="62" x2="533" y2="62" stroke="var(--rule)" strokeWidth="1.5" />
      {[0, 1, 2].map(i => (
        <path
          key={i}
          d={`M533 62 V${34 + i * 28} H540`}
          fill="none"
          stroke={active === 3 ? 'var(--hot)' : 'var(--rule)'}
          strokeWidth="1.2"
        />
      ))}

      <line x1="40" y1="118" x2="500" y2="118" stroke="var(--rule)" strokeDasharray="2 4" />
      <text x="40" y="132" fontSize="8" letterSpacing="0.12em" fill="var(--ink-dim)" fontFamily="var(--font-mono)">
        READ ONCE
      </text>
      <text x="310" y="132" fontSize="8" letterSpacing="0.12em" fill="var(--hot-ink)" fontFamily="var(--font-mono)">
        WRITE MANY TIMES
      </text>
    </svg>
  )
}

export default function LandingPage() {
  const { user } = useAuth()
  const [active, setActive] = useState(0)
  const [paused, setPaused] = useState(false)
  const [lines, setLines] = useState(1)

  const enterTo = user ? '/app' : '/sign-in'
  const enterLabel = user ? 'Open the studio →' : 'Sign in →'

  useEffect(() => {
    if (paused) return
    const t = setInterval(() => setActive(s => (s + 1) % STAGES.length), 3200)
    return () => clearInterval(t)
  }, [paused])

  useEffect(() => {
    if (lines >= TERMINAL.length) return
    const t = setTimeout(() => setLines(v => v + 1), 480)
    return () => clearTimeout(t)
  }, [lines])

  const stage = STAGES[active]

  const cta = 'tag inline-flex items-center justify-center gap-1.5 border transition-colors'

  return (
    <div className="min-h-screen bg-paper">
      <nav className="sticky top-0 z-50 flex items-center gap-3 border-b border-rule bg-paper/95 px-4 py-2 backdrop-blur">
        <Logo size={17} />
        <span className="text-[11.5px] font-bold tracking-tight text-ink">
          code<span className="text-hot">·</span>lith
        </span>
        <Chip>v0.4.1</Chip>
        <div className="ml-auto flex items-center gap-3">
          <a href="#features" className="tag hidden text-ink-dim transition-colors hover:text-ink sm:block">
            Features
          </a>
          <a href="#pipeline" className="tag hidden text-ink-dim transition-colors hover:text-ink sm:block">
            Pipeline
          </a>
          <a
            href="https://github.com/codelith"
            target="_blank"
            rel="noreferrer"
            className="tag flex items-center gap-1.5 text-ink-dim transition-colors hover:text-ink"
          >
            <GitHubMark size={12} /> Source
          </a>
          <Link
            to={enterTo}
            className={`${cta} border-ink bg-ink px-3 py-[7px] text-paper hover:border-hot hover:bg-hot`}
          >
            {enterLabel}
          </Link>
        </div>
      </nav>

      {/* hero */}
      <section className="bp-grid border-b border-rule">
        <div className="mx-auto grid max-w-[1180px] grid-cols-1 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
          <div className="border-rule px-5 py-10 lg:border-r lg:py-14">
            <div className="mb-5 flex flex-wrap gap-1.5">
              <Chip>open source</Chip>
              <Chip>MIT</Chip>
              <Chip>self-hosted</Chip>
              <Chip tone="hot">● runs fully offline</Chip>
            </div>

            <h1 className="mb-5 text-[clamp(30px,5.4vw,58px)] leading-[0.95] font-bold tracking-[-0.045em] text-ink">
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
              knowledge base — routes, entry points, module boundaries, dependencies, data
              stores — pinned to the commit it read.
            </p>
            <p className="mb-4 max-w-[52ch] font-sans text-[14px] leading-[1.7] text-ink-mid">
              That knowledge base is the product. Everything else is something you do with
              it: <strong className="font-semibold text-ink">write documentation</strong>,{' '}
              <strong className="font-semibold text-ink">ask the code questions</strong>, and
              more as they land. None of them read the repository again.
            </p>
            <p className="mb-6 max-w-[52ch] font-sans text-[14px] leading-[1.7] text-ink-mid">
              Everything runs on your machine against a local LLM.{' '}
              <strong className="font-semibold text-ink">No code leaves the box.</strong>
            </p>

            <div className="flex flex-wrap items-center gap-2">
              <Link
                to={enterTo}
                className={`${cta} border-hot bg-hot px-5 py-2.5 text-on-hot hover:border-hot-press hover:bg-hot-press`}
              >
                {enterLabel}
              </Link>
              <a
                href="https://github.com/codelith"
                target="_blank"
                rel="noreferrer"
                className={`${cta} border-rule bg-panel px-3 py-[10px] text-ink-mid hover:border-ink hover:text-ink`}
              >
                <GitHubMark size={12} /> Read the source
              </a>
            </div>
          </div>

          {/* terminal */}
          <div className="flex flex-col justify-center border-t border-rule px-5 py-8 lg:border-t-0">
            <div className="border border-ink bg-term">
              <div className="tag flex items-center gap-2 border-b border-term-rule px-3 py-2 text-term-dim">
                <span className="size-[6px] rotate-45 bg-hot" />
                job #38 — analysis
                <span className="ml-auto">local</span>
              </div>
              <div className="px-3 py-2.5">
                {TERMINAL.slice(0, lines).map((l, i) => (
                  <div
                    key={i}
                    className={`anim-rise overflow-x-auto text-[11px] leading-[1.75] whitespace-pre ${
                      l.t === 'cmd' ? 'text-on-ink' : l.t === 'live' ? 'text-term-dim' : 'text-term-ok'
                    }`}
                  >
                    {l.s}
                    {l.t === 'live' && i === lines - 1 && <span className="anim-blink text-hot">▌</span>}
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
                ['14', 'local agents'],
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

      {/* ticker */}
      <div className="overflow-hidden border-b border-rule bg-term py-1.5">
        <div className="flex w-max gap-6 whitespace-nowrap" style={{ animation: 'ticker 38s linear infinite' }}>
          {[...AGENTS, ...AGENTS].map((a, i) => (
            <span key={i} className="tag flex items-center gap-2 text-term-dim">
              <span className="size-[4px] rotate-45 bg-hot" />
              {a}
            </span>
          ))}
        </div>
      </div>

      {/* pipeline */}
      <section id="pipeline" className="mx-auto max-w-[1180px] px-5 py-12">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-4 border-b border-rule pb-4">
          <div>
            <p className="tag mb-2 text-hot-ink">How it works</p>
            <h2 className="text-[clamp(20px,3vw,34px)] leading-[1.05] font-bold tracking-[-0.035em] text-ink">
              Analyse once.
              <br />
              Use it as many times as you need.
            </h2>
          </div>
          <button
            onClick={() => setPaused(p => !p)}
            className="tag border border-rule bg-panel px-3 py-2 text-ink-dim transition-colors hover:border-ink hover:text-ink"
          >
            {paused ? '▶ resume' : '❚❚ pause'}
          </button>
        </div>

        <div className="mb-4 border border-rule bg-panel p-4">
          <FlowDiagram active={active} />
        </div>

        <div className="grid grid-cols-2 gap-px border border-rule bg-rule lg:grid-cols-4">
          {STAGES.map((s, i) => {
            const cur = active === i
            return (
              <button
                key={s.num}
                onClick={() => {
                  setActive(i)
                  setPaused(true)
                }}
                className={`relative px-3 py-2.5 text-left transition-colors ${
                  cur ? 'bg-hot-wash' : 'bg-panel hover:bg-sunk'
                }`}
              >
                {cur && <span className="absolute inset-x-0 top-0 h-[2px] bg-hot" />}
                <span className={`tag block ${cur ? 'text-hot-ink' : 'text-ink-dim'}`}>{s.num}</span>
                <span className="mt-1.5 block text-[14px] font-bold tracking-tight text-ink">{s.name}</span>
                <span className="mt-0.5 block text-[10.5px] text-ink-dim">{s.tagline}</span>
              </button>
            )
          })}
        </div>

        <div
          key={active}
          className="anim-rise grid grid-cols-1 gap-5 border border-t-0 border-rule bg-panel p-4 lg:grid-cols-[minmax(0,1fr)_300px]"
        >
          <div>
            <p className="tag mb-2.5 text-hot-ink">{stage.tagline}</p>
            <p className="mb-4 max-w-[56ch] font-sans text-[13.5px] leading-[1.75] text-ink-mid">
              {stage.desc}
            </p>
            {!paused && (
              <div className="flex items-center gap-2.5">
                <span className="h-[2px] w-40 overflow-hidden bg-rule">
                  <span className="block h-full bg-hot" style={{ animation: 'sweep 3.2s linear' }} />
                </span>
                <span className="tag text-ink-dim">
                  {active + 1} / {STAGES.length}
                </span>
              </div>
            )}
          </div>
          <div className="grid grid-cols-2 gap-px self-start border border-rule bg-rule">
            {stage.facts.map(([k, v]) => (
              <div key={k} className="bg-paper px-2.5 py-2">
                <div className="tag mb-1 text-ink-dim">{k}</div>
                <div className="text-[14px] leading-none font-bold text-ink">{v}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* services — what the knowledge base unlocks */}
      <section id="features" className="border-t border-rule bg-panel">
        <div className="mx-auto max-w-[1180px] px-5 py-12">
          <div className="mb-6 border-b border-rule pb-4">
            <p className="tag mb-2 text-hot-ink">What it unlocks</p>
            <h2 className="max-w-[24ch] text-[clamp(20px,3vw,34px)] leading-[1.05] font-bold tracking-[-0.035em] text-ink">
              One analysis. Everything else grows on it.
            </h2>
            <p className="mt-3 max-w-[62ch] font-sans text-[13.5px] leading-[1.7] text-ink-mid">
              Each of these reads the same knowledge base and none of them reads the
              repository again. That is the whole architecture, and it is why the second
              thing you ask for is cheap.
            </p>
          </div>

          <div className="grid grid-cols-1 gap-px border border-rule bg-rule lg:grid-cols-2">
            {SERVICES.map(s => (
              <div key={s.id} className="group flex flex-col bg-panel p-5 transition-colors hover:bg-hot-wash/40">
                <div className="mb-3 flex items-baseline gap-2">
                  <span className="tag text-rule transition-colors group-hover:text-hot">{s.id}</span>
                  <h3 className="text-[15px] font-bold tracking-tight text-ink">{s.name}</h3>
                  <span className="tag ml-auto text-ink-dim">{s.label}</span>
                </div>

                <p className="mb-3 font-sans text-[13px] leading-relaxed font-semibold text-ink">
                  {s.line}
                </p>
                <p className="mb-4 font-sans text-[12.5px] leading-[1.7] text-ink-mid">{s.desc}</p>

                <div className="mt-auto grid grid-cols-2 gap-px border border-rule bg-rule sm:grid-cols-4">
                  {s.facts.map(([k, v]) => (
                    <div key={k} className="bg-paper px-2.5 py-2">
                      <div className="tag mb-1 text-ink-dim">{k}</div>
                      <div className="text-[12px] leading-none font-bold text-ink">{v}</div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>

          <p className="mt-4 font-sans text-[12px] leading-relaxed text-ink-dim">
            A feature is defined by what it needs from the knowledge base — which is why
            adding one never means analysing your code differently.
          </p>
        </div>
      </section>

      {/* claims */}
      <section className="border-y border-rule bg-panel">
        <div className="mx-auto grid max-w-[1180px] grid-cols-1 gap-px bg-rule md:grid-cols-3">
          {[
            ['Evidence, not vibes', 'A section on authentication only appears if the analyser actually found auth, and an answer that cites a file it never retrieved has the citation stripped. Everything traces back to a file and a line.'],
            ['Local by construction', 'Point the endpoint at LM Studio or Ollama and the process never opens a socket to the internet. Your source stays yours.'],
            ['Cheap to re-run', 'The expensive read happens once per commit. A fifth document, or a hundred questions, cost a retrieval pass — not another full analysis.'],
          ].map(([t, d], i) => (
            <div key={t} className="group bg-panel px-5 py-8 transition-colors hover:bg-hot-wash/50">
              <div className="tag mb-3 text-rule transition-colors group-hover:text-hot">
                {String(i + 1).padStart(2, '0')}
              </div>
              <h3 className="mb-2 text-[15px] font-bold tracking-tight text-ink">{t}</h3>
              <p className="font-sans text-[12.5px] leading-relaxed text-ink-mid">{d}</p>
            </div>
          ))}
        </div>
      </section>

      {/* cta */}
      <section className="bp-hatch border-b border-rule px-5 py-14 text-center">
        <h2 className="mb-3 text-[clamp(20px,3.4vw,34px)] leading-tight font-bold tracking-[-0.035em] text-ink">
          Stop writing docs your code
          <br />
          already knows.
        </h2>
        <p className="mx-auto mb-6 max-w-[48ch] font-sans text-[13.5px] leading-relaxed text-ink-mid">
          Clone it, point it at a repository, and read what comes out.
        </p>
        <Link
          to={enterTo}
          className={`${cta} border-hot bg-hot px-6 py-3 text-on-hot hover:border-hot-press hover:bg-hot-press`}
        >
          {enterLabel}
        </Link>
      </section>

      <footer className="mx-auto flex max-w-[1180px] flex-wrap items-center gap-3 px-5 py-5">
        <Logo size={15} />
        <span className="tag text-ink-dim">codelith · MIT licence · free forever</span>
        <a
          href="https://github.com/codelith"
          target="_blank"
          rel="noreferrer"
          className="tag ml-auto flex items-center gap-1.5 text-ink-dim transition-colors hover:text-ink"
        >
          <GitHubMark size={12} /> github.com/codelith
        </a>
      </footer>
    </div>
  )
}
