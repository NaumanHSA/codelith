import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth'
import { Chip, GitHubMark, Logo } from '../components/ui'

const STAGES = [
  {
    num: '01',
    name: 'Analyse',
    note: 'Every file, once',
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
    note: 'Pinned to the SHA',
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
    note: 'From the evidence',
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
    note: 'No repo reads',
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

/* ------------------------------------------------------------------ *
 * The four-stage pipeline as a live schematic.
 *
 * Drawn in the same vocabulary as the diagram on Home — rounded cards on
 * a warm ground, a pulse that draws each connector in, a flare as it
 * lands — because a visitor who signs up should recognise the studio
 * rather than meet a second product.
 *
 * The beat matters more than the shapes. Stages used to swap on a bare
 * interval, so the schematic never showed the thing it exists to show:
 * that one stage feeds the next. Now the card dwells, the connector
 * draws itself in, and only then does the next card arrive. The gap is
 * the argument.
 *
 * Connectors are normalised with pathLength, so one keyframe covers any
 * length, and drawn connectors stay drawn — the hot trail behind the
 * pulse is how far the reading has got.
 * ------------------------------------------------------------------ */

/** How long a stage holds before handing on, and how long the handover takes. */
const DWELL = 2400
const TRAVEL = 620

const CARD_W = 178
const CARD_H = 88
const CARD_Y = 24
const COLS = [16, 240, 464, 688]
const WIRE_Y = CARD_Y + 44

function FlowDiagram({
  active,
  moving,
  paused,
  onPick,
}: {
  active: number
  moving: boolean
  paused: boolean
  onPick: (i: number) => void
}) {
  return (
    <svg viewBox="0 0 880 170" className="w-full" role="img" aria-label="Four-stage pipeline: analyse, knowledge base, unlock, use.">
      <defs>
        <pattern id="fg" width="16" height="16" patternUnits="userSpaceOnUse">
          <path d="M16 0H0V16" fill="none" stroke="var(--grid-line)" />
        </pattern>
      </defs>
      <rect width="880" height="170" fill="url(#fg)" />

      {/* Connectors. Behind the pulse they stay hot; ahead of it they are bare rule. */}
      {[0, 1, 2].map(i => {
        const x1 = COLS[i] + CARD_W
        const x2 = COLS[i + 1]
        const d = `M${x1} ${WIRE_Y} H${x2 - 7}`
        const crossed = i < active
        const drawing = moving && i === active
        return (
          <g key={i}>
            <path d={d} fill="none" stroke="var(--rule)" strokeWidth="1.5" />
            {(crossed || drawing) && (
              <path
                key={drawing ? `draw-${active}` : 'done'}
                d={d}
                pathLength={100}
                fill="none"
                stroke="var(--hot)"
                strokeWidth="2"
                strokeLinecap="round"
                strokeDasharray="100"
                style={
                  drawing
                    ? { animation: `pipe-draw ${TRAVEL}ms linear forwards` }
                    : undefined
                }
              />
            )}
            <path
              d={`M${x2 - 7} ${WIRE_Y - 4.5} L${x2 - 1} ${WIRE_Y} L${x2 - 7} ${WIRE_Y + 4.5}`}
              fill="none"
              strokeLinecap="round"
              strokeLinejoin="round"
              stroke={crossed ? 'var(--hot)' : 'var(--rule)'}
              strokeWidth="1.6"
            />
          </g>
        )
      })}

      {STAGES.map((stage, i) => {
        const x = COLS[i]
        const cur = i === active
        const lit = i <= active
        return (
          <g key={stage.num} onClick={() => onPick(i)} className="cursor-pointer">
            <rect
              // Remounted on arrival so the flare replays rather than firing once.
              key={cur ? `arrive-${active}` : 'idle'}
              x={x}
              y={CARD_Y}
              width={CARD_W}
              height={CARD_H}
              rx="8"
              fill={lit ? 'var(--hot-wash)' : 'var(--panel)'}
              stroke={lit ? 'var(--hot)' : 'var(--rule)'}
              strokeWidth={cur ? 2.2 : lit ? 1.6 : 1.2}
              style={cur ? { animation: 'pipe-arrive 620ms ease-out' } : undefined}
              className="transition-[fill,stroke] duration-300"
            />
            <text
              x={x + 16} y={CARD_Y + 26} fontSize="10" letterSpacing="1"
              fill={lit ? 'var(--hot-ink)' : 'var(--ink-dim)'} fontFamily="var(--font-mono)"
            >
              {stage.num}
            </text>
            <text
              x={x + 16} y={CARD_Y + 50} fontSize="15" fontWeight="600"
              fill={lit ? 'var(--hot-ink)' : 'var(--ink)'} fontFamily="var(--font-mono)"
            >
              {stage.name}
            </text>
            <text
              x={x + 16} y={CARD_Y + 70} fontSize="10.5"
              fill="var(--ink-dim)" fontFamily="var(--font-mono)"
            >
              {stage.note}
            </text>

            {/* How long this stage has left. The rule fills over the dwell, so the
                schematic says when it will hand on instead of jumping unannounced. */}
            <rect x={x + 16} y={CARD_Y + 78} width={CARD_W - 32} height="3" rx="1.5" fill="var(--rule)" />
            {cur && !paused && (
              <rect
                key={`sweep-${active}-${moving}`}
                x={x + 16} y={CARD_Y + 78} height="3" rx="1.5" fill="var(--hot)"
                width={moving ? CARD_W - 32 : 0}
              >
                {!moving && (
                  <animate
                    attributeName="width"
                    from="0"
                    to={CARD_W - 32}
                    dur={`${DWELL}ms`}
                    fill="freeze"
                  />
                )}
              </rect>
            )}
          </g>
        )
      })}

      {/* Which half is paid for once and which is paid for every time. Brackets
          rather than a single dashed rule: a bracket has ends, so it says which
          stages it covers. The old stub fanning off the right edge was cropped by
          the viewBox and read as a rendering fault. */}
      {[
        { from: COLS[0], to: COLS[1] + CARD_W, label: 'READ ONCE', hot: false },
        { from: COLS[2], to: COLS[3] + CARD_W, label: 'WRITE MANY TIMES', hot: active >= 2 },
      ].map(b => (
        <g key={b.label} className="transition-colors">
          <path
            d={`M${b.from} 126 V134 H${b.to} V126`}
            fill="none"
            stroke={b.hot ? 'var(--hot)' : 'var(--rule)'}
            strokeWidth="1.2"
          />
          <text
            x={(b.from + b.to) / 2} y="153" fontSize="9.5" letterSpacing="1.4"
            textAnchor="middle"
            fill={b.hot ? 'var(--hot-ink)' : 'var(--ink-dim)'}
            fontFamily="var(--font-mono)"
          >
            {b.label}
          </text>
        </g>
      ))}
    </svg>
  )
}

export default function LandingPage() {
  const { user } = useAuth()
  const [active, setActive] = useState(0)
  const [moving, setMoving] = useState(false)
  const [paused, setPaused] = useState(false)
  const [lines, setLines] = useState(1)

  const enterTo = user ? '/app' : '/sign-in'
  const enterLabel = user ? 'Open the studio →' : 'Sign in →'

  // Two beats, not one. The stage holds, then the connector draws itself in, and
  // only then does the next stage arrive — so the schematic shows one stage feeding
  // the next rather than four cards taking turns.
  useEffect(() => {
    if (paused) return
    if (!moving) {
      const t = setTimeout(() => setMoving(true), DWELL)
      return () => clearTimeout(t)
    }
    const t = setTimeout(() => {
      setActive(s => (s + 1) % STAGES.length)
      setMoving(false)
    }, TRAVEL)
    return () => clearTimeout(t)
  }, [paused, moving, active])

  // Held still for anybody who has asked for less motion. The tab strip below still
  // drives the whole section by hand.
  useEffect(() => {
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) setPaused(true)
  }, [])

  useEffect(() => {
    if (lines >= TERMINAL.length) return
    const t = setTimeout(() => setLines(v => v + 1), 480)
    return () => clearTimeout(t)
  }, [lines])

  const stage = STAGES[active]

  /** Choosing a stage cancels a handover in flight, or the pulse lands on a connector
   *  nobody is watching and drags the reader forward again. */
  const pick = (i: number) => {
    setActive(i)
    setMoving(false)
    setPaused(true)
  }

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

        <div className="mb-4 overflow-hidden rounded-sm border border-rule bg-sunk/70 px-4 py-5">
          <FlowDiagram active={active} moving={moving} paused={paused} onPick={pick} />
        </div>

        <div className="grid grid-cols-2 gap-px border border-rule bg-rule lg:grid-cols-4">
          {STAGES.map((s, i) => {
            const cur = active === i
            return (
              <button
                key={s.num}
                onClick={() => pick(i)}
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
                  <span
                  className="block h-full bg-hot"
                  style={{ animation: `sweep ${DWELL + TRAVEL}ms linear` }}
                />
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
