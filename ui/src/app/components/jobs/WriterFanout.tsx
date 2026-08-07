import type { JobLog } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * What the writer is actually doing, section by section.
 *
 * The writer is the longest stage of a composition run and reported one
 * line — "Writing the prose" — for the whole of it. But the headings are
 * known before it starts: the planner decided them, and now publishes
 * them on its step output. So this draws the fan-out for real.
 *
 * Sections run concurrently up to COMPOSITION_SECTION_CONCURRENCY, so
 * several are genuinely in flight at once and the shape is a fan, not a
 * list. Live state comes from the writer's own progress lines — logs the
 * UI is already streaming — rather than from a second endpoint.
 * ------------------------------------------------------------------ */

export type SectionState = 'pending' | 'writing' | 'done'

export interface WriterSection {
  page: string
  name: string
  state: SectionState
  words?: number
}

/**
 * Merge the planner's outline with whatever the writer has reported.
 *
 * The outline is the source of truth for *what* there is to write; the logs only
 * move a heading between states. A heading the writer mentions that was never
 * planned still shows — better a surprise row than a silently missing one.
 */
export function buildSections(
  outline: Record<string, string[]> | null,
  logs: JobLog[],
): WriterSection[] {
  const out: WriterSection[] = []
  const index = new Map<string, number>()

  for (const [page, names] of Object.entries(outline ?? {})) {
    for (const name of names) {
      index.set(`${page}::${name}`, out.length)
      out.push({ page, name, state: 'pending' })
    }
  }

  for (const log of logs) {
    const extra = log.extra as Record<string, unknown> | null
    const event = extra?.event
    if (event !== 'section_start' && event !== 'section_done') continue
    const page = String(extra?.page ?? '')
    const name = String(extra?.section ?? '')
    if (!name) continue

    const key = `${page}::${name}`
    let at = index.get(key)
    if (at === undefined) {
      at = out.length
      index.set(key, at)
      out.push({ page, name, state: 'pending' })
    }
    out[at].state = event === 'section_done' ? 'done' : 'writing'
    if (event === 'section_done' && typeof extra?.words === 'number') {
      out[at].words = extra.words
    }
  }

  return out
}

const DOT: Record<SectionState, string> = {
  done: 'bg-ok',
  writing: 'bg-hot anim-pulse',
  pending: 'bg-rule',
}

export default function WriterFanout({
  sections,
  multiPage,
}: {
  sections: WriterSection[]
  /** Label each heading with its page when the run spans more than one. */
  multiPage: boolean
}) {
  if (!sections.length) return null

  const done = sections.filter(s => s.state === 'done').length
  const writing = sections.filter(s => s.state === 'writing')

  return (
    <div className="border-t border-rule bg-sunk/30 px-3 py-2.5">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="tag text-ink-dim">
          {done}/{sections.length} sections written
        </span>
        {writing.length > 1 && (
          <span className="tag text-hot-ink">{writing.length} in parallel</span>
        )}
      </div>

      {/* The fan: one trunk, a branch per heading. */}
      <div className="flex gap-2">
        <svg width="14" className="shrink-0" aria-hidden>
          <line x1="7" y1="0" x2="7" y2="100%" stroke="var(--rule)" strokeWidth="1.5" />
        </svg>

        <ul className="min-w-0 flex-1 space-y-[3px]">
          {sections.map((s, i) => (
            <li key={`${s.page}::${s.name}::${i}`} className="flex items-center gap-2">
              {/* the branch out of the trunk */}
              <svg width="12" height="12" className="-ml-2 shrink-0" aria-hidden>
                <path
                  d="M0 6 H12"
                  stroke={s.state === 'pending' ? 'var(--rule)' : 'var(--hot)'}
                  strokeWidth="1.5"
                  strokeDasharray={s.state === 'pending' ? '2 2' : undefined}
                />
              </svg>
              <span className={`block size-[6px] shrink-0 rotate-45 ${DOT[s.state]}`} />
              <span
                className={`min-w-0 flex-1 truncate text-[11.5px] ${
                  s.state === 'pending'
                    ? 'text-ink-dim'
                    : s.state === 'writing'
                      ? 'font-semibold text-hot-ink'
                      : 'text-ink-mid'
                }`}
                title={multiPage ? `${s.page} — ${s.name}` : s.name}
              >
                {s.name}
              </span>
              {multiPage && (
                <span className="tag hidden shrink-0 text-ink-dim md:block">
                  {s.page.split('/').pop()}
                </span>
              )}
              {s.state === 'writing' && <span className="tag shrink-0 text-hot-ink">writing…</span>}
              {s.state === 'done' && s.words != null && (
                <span className="tag shrink-0 text-ink-dim">{s.words}w</span>
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
