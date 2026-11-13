import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useChatThreads } from '../../chat-threads'
import { relativeTime } from '../../lib/format'
import { Icon } from '../../lib/icons'
import { APP_LOOKS } from '../../lib/kinds'
import type { Project } from '../../lib/types'
import { CodebaseMark, IconTile, ListRow, Pill } from '../primitives'

/* ------------------------------------------------------------------ *
 * Where Ask the code starts: choose the codebase, then talk.
 *
 * It used to drop you into a conversation about whichever codebase came
 * first, with a drop-down to change it. That reads well with three and is
 * a hunt with thirty, so the choice comes first, with a search, and the
 * conversations you already had are one click from here too.
 * ------------------------------------------------------------------ */

export default function ChatWelcome({
  projects,
  onPick,
}: {
  projects: Project[]
  onPick: (projectId: number) => void
}) {
  const [q, setQ] = useState('')
  const { threads } = useChatThreads()
  const look = APP_LOOKS.assistant

  const byProject = useMemo(() => {
    const m = new Map<number, { count: number; last: string | null }>()
    for (const t of threads) {
      const cur = m.get(t.project_id) ?? { count: 0, last: null }
      cur.count++
      if (t.last_message_at && (!cur.last || t.last_message_at > cur.last)) cur.last = t.last_message_at
      m.set(t.project_id, cur)
    }
    return m
  }, [threads])

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return projects
      .filter(
        p =>
          !needle ||
          p.name.toLowerCase().includes(needle) ||
          (p.description ?? '').toLowerCase().includes(needle) ||
          (p.sources?.[0]?.url_or_path ?? '').toLowerCase().includes(needle),
      )
      // Ones that can be asked first, then the ones talked to most recently.
      .sort((a, b) => Number(b.apps_ready) - Number(a.apps_ready) || (byProject.get(b.id)?.last ?? '').localeCompare(byProject.get(a.id)?.last ?? ''))
  }, [projects, q, byProject])

  return (
    <div className="flex w-full flex-col gap-8 px-6 py-8">
      <header className="flex flex-wrap items-center gap-3.5">
        <IconTile icon={look.icon} color={look.color} tint size={44} />
        <div>
          <h1 className="text-[22px] leading-tight font-semibold text-ink">Ask the code</h1>
          <p className="mt-1 max-w-[70ch] text-[13.5px] text-ink-mid">
            Questions answered from a codebase's reading, with every reference checked against what was
            retrieved. Choose the codebase to ask about.
          </p>
        </div>
      </header>

      <div className="grid grid-cols-1 gap-10 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <section className="flex flex-col gap-3">
          <label className="flex h-10 items-center gap-2 rounded-lg border border-line-2 bg-sunk px-3 focus-within:border-hot">
            <Icon name="search" size={16} className="text-ink-dim" />
            <input
              autoFocus
              value={q}
              onChange={e => setQ(e.target.value)}
              onKeyDown={e => {
                const first = shown.find(p => p.apps_ready)
                if (e.key === 'Enter' && first) onPick(first.id)
              }}
              placeholder="Find a codebase by name, description or URL"
              aria-label="Find a codebase"
              className="min-w-0 flex-1 bg-transparent text-[14px] text-ink placeholder:text-ink-dim focus:outline-none"
            />
            <span className="text-[12px] text-ink-dim">{shown.length}</span>
          </label>

          {shown.length === 0 ? (
            <p className="px-1 py-3 text-[13px] text-ink-dim">No codebase matches that.</p>
          ) : (
            <ul className="flex flex-col">
              {shown.map(p => {
                const talk = byProject.get(p.id)
                const lead = (
                  <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-sunk shadow-[inset_0_0_0_1px_var(--line-2)]">
                    <CodebaseMark project={p} size={18} />
                  </span>
                )
                return (
                  <li key={p.id}>
                    {p.apps_ready ? (
                      <ListRow
                        onClick={() => onPick(p.id)}
                        lead={lead}
                        title={p.name}
                        sub={p.description || p.sources?.[0]?.url_or_path}
                        trail={
                          <span className="flex shrink-0 items-center gap-3 text-[12.5px] text-ink-dim">
                            {talk ? (
                              <span>
                                {talk.count} conversation{talk.count === 1 ? '' : 's'}
                                {talk.last ? ` · ${relativeTime(talk.last)}` : ''}
                              </span>
                            ) : (
                              <span>No conversations yet</span>
                            )}
                            <Icon name="chevron-right" size={15} />
                          </span>
                        }
                      />
                    ) : (
                      <ListRow
                        to={`/app/projects/${p.id}`}
                        lead={lead}
                        title={p.name}
                        sub="Not read yet. Analyse it, and it can be asked about."
                        trail={<Pill icon="circle-dashed">Not read yet</Pill>}
                        className="opacity-70"
                      />
                    )}
                  </li>
                )
              })}
            </ul>
          )}
        </section>

        <section className="flex flex-col gap-2">
          <h2 className="text-[15px] font-semibold text-ink">Pick up where you left off</h2>
          {threads.length === 0 ? (
            <p className="text-[13px] text-ink-dim">No conversations yet.</p>
          ) : (
            <ul className="flex flex-col">
              {threads.slice(0, 8).map(t => (
                <li key={t.id}>
                  <Link
                    to={`/app/chat?project=${t.project_id}&thread=${t.id}`}
                    className="group flex items-center gap-3 rounded-lg px-3 py-2.5 transition-colors hover:bg-hover"
                  >
                    <Icon name="message-square" size={15} className="text-ink-dim group-hover:text-hot" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13.5px] text-ink">{t.title}</span>
                      <span className="block truncate text-[12px] text-ink-dim">
                        {t.project_name}
                        {t.last_message_at ? ` · ${relativeTime(t.last_message_at)}` : ''}
                      </span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  )
}
