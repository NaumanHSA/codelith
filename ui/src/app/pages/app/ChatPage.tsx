import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../../lib/api'
import type { ChatMessage, ChatSource, ChatThread, Project } from '../../lib/types'
import { AssistantMessage, UserMessage } from '../../components/chat/Message'
import { Composer } from '../../components/chat/Composer'
import ConfirmDelete from '../../components/ConfirmDelete'
import { SkeletonPanel } from '../../components/States'

/* ------------------------------------------------------------------ *
 * Ask the codebase.
 *
 * Top level rather than inside a project, because it is a way of
 * working rather than a property of one repository — but the knowledge
 * base *is* per project, so the page picks one. Deep-linkable as
 * ?project=2 so a conversation can be shared or bookmarked.
 *
 * The layout follows the reference: input centred in an empty room,
 * and the moment there is something to read it moves to the bottom and
 * gets out of the way.
 * ------------------------------------------------------------------ */

/** Real questions, taken from the set this substrate was measured against. */
const SUGGESTIONS = [
  'How is the database initialised?',
  'Where is data stored?',
  'How does a request flow through the system?',
  'What external services does it talk to?',
]

interface Live {
  question: string
  answer: string
  sources: ChatSource[]
  counts: Record<string, number>
}

export default function ChatPage() {
  const [params, setParams] = useSearchParams()
  const [projects, setProjects] = useState<Project[] | null>(null)
  const [thread, setThread] = useState<ChatThread | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [draft, setDraft] = useState('')
  const [live, setLive] = useState<Live | null>(null)
  const abort = useRef<AbortController | null>(null)
  const [confirming, setConfirming] = useState(false)
  const bottom = useRef<HTMLDivElement>(null)

  const projectId = Number(params.get('project')) || projects?.[0]?.id || null
  const project = projects?.find(p => p.id === projectId) ?? null

  useEffect(() => {
    api
      .projects()
      .then(setProjects)
      .catch(() => setProjects([]))
  }, [])

  // Load whatever conversation this project already had.
  useEffect(() => {
    if (!projectId) {
      setLoading(false)
      return
    }
    let live = true
    setLoading(true)
    setError(null)
    api
      .chatThread(projectId)
      .then(t => live && setThread(t))
      .catch(() => live && setThread(null))
      .finally(() => live && setLoading(false))
    return () => {
      live = false
    }
  }, [projectId])

  const messages = thread?.messages ?? []
  const empty = messages.length === 0 && !live

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: live ? 'auto' : 'smooth' })
  }, [messages.length, live?.answer])

  const used = useMemo(() => {
    const stored = thread?.token_count ?? 0
    // The draft is counted at roughly four characters a token. It is an estimate
    // and labelled as one — the authoritative number arrives with each answer.
    return stored + Math.ceil(draft.length / 4)
  }, [thread?.token_count, draft])

  const send = useCallback(
    async (text: string) => {
      const question = text.trim()
      if (!question || !projectId || live) return

      setDraft('')
      setError(null)
      setLive({ question, answer: '', sources: [], counts: {} })

      const controller = new AbortController()
      abort.current = controller

      try {
        await api.askStream(
          projectId,
          { question, thread_id: thread?.id ?? null },
          event => {
            switch (event.type) {
              case 'thread':
                setThread(t =>
                  t ?? { id: event.thread_id, title: event.title, messages: [], token_count: 0, context_window: 0 },
                )
                break
              case 'evidence':
                setLive(l => (l ? { ...l, sources: event.sources, counts: event.counts } : l))
                break
              case 'token':
                setLive(l => (l ? { ...l, answer: l.answer + event.text } : l))
                break
              case 'error':
                setError(event.message)
                break
            }
          },
          controller.signal,
        )
      } catch (e) {
        // An abort is the stop button working, not a failure.
        if (!controller.signal.aborted) {
          setError(e instanceof ApiError ? e.message : 'The answer could not be completed.')
        }
      } finally {
        abort.current = null
        setLive(null)
        // Reload rather than splice: the server holds the checked citations and
        // the authoritative token counts, and guessing them here would show the
        // reader something different from what was kept.
        if (projectId) {
          api.chatThread(projectId).then(setThread).catch(() => undefined)
        }
      }
    },
    [projectId, thread?.id, live],
  )

  const clear = useCallback(async () => {
    if (!projectId || !thread) return
    await api.clearChat(projectId, thread.id)
    const fresh = await api.chatThread(projectId).catch(() => null)
    setThread(fresh)
  }, [projectId, thread])

  if (projects === null) return <SkeletonPanel rows={6} />

  if (!projects.length) {
    return (
      <Empty title="No projects yet">
        Analyse a repository first — there is nothing to ask about until one has been
        read. <Link to="/app/projects" className="text-hot-ink underline">Add a project</Link>.
      </Empty>
    )
  }

  return (
    <div className="flex h-[calc(100vh-4rem)] min-h-0 flex-col">
      <header className="flex shrink-0 items-center justify-between gap-3 border-b border-rule px-1 pb-3">
        <div className="flex min-w-0 items-center gap-3">
          <h1 className="truncate text-[15px] text-ink">Ask the codebase</h1>
          <select
            value={projectId ?? ''}
            onChange={e => {
              setParams({ project: e.target.value })
              setThread(null)
            }}
            className="max-w-[220px] truncate border border-rule bg-panel px-2 py-1 text-[12px] text-ink-mid outline-none focus:border-hot"
          >
            {projects.map(p => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>

        {!!messages.length && (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            className="shrink-0 text-[11px] text-ink-dim hover:text-hot-ink"
          >
            clear conversation
          </button>
        )}
      </header>

      <ConfirmDelete
        open={confirming}
        onClose={() => setConfirming(false)}
        onConfirm={clear}
        actionLabel="Clear"
        title="Clear this conversation?"
        body="Every message in it is deleted. Documentation that was generated from these answers is untouched."
      />

      {loading ? (
        <div className="pt-6">
          <SkeletonPanel rows={5} />
        </div>
      ) : empty ? (
        /* Nothing said yet: the composer sits in the middle of the room. */
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center px-4">
          <div className="w-full max-w-[720px]">
            <h2 className="mb-1 text-center text-[22px] text-ink">
              What do you want to know about{' '}
              <span className="text-hot-ink">{project?.name ?? 'this codebase'}</span>?
            </h2>
            <p className="mb-6 text-center text-[12px] text-ink-dim">
              Answers are grounded in the analysed source, and every reference is
              checked against what was actually retrieved.
            </p>

            <Composer
              value={draft}
              onChange={setDraft}
              onSend={() => send(draft)}
              onStop={() => abort.current?.abort()}
              busy={false}
              used={used}
              total={thread?.context_window ?? 0}
              autoFocus
            />

            <div className="mt-4 flex flex-wrap justify-center gap-2">
              {SUGGESTIONS.map(s => (
                <button
                  key={s}
                  type="button"
                  onClick={() => send(s)}
                  className="rounded-full border border-rule px-3 py-1.5 text-[11px] text-ink-mid transition-colors hover:border-hot hover:text-hot-ink"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <>
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6">
            <div className="mx-auto flex max-w-[760px] flex-col gap-6">
              {messages.map(m =>
                m.role === 'user' ? (
                  <UserMessage key={m.id} content={m.content} />
                ) : (
                  <AssistantMessage key={m.id} message={m} />
                ),
              )}

              {live && (
                <>
                  <UserMessage content={live.question} />
                  {live.answer ? (
                    <AssistantMessage
                      streaming
                      message={{
                        content: live.answer,
                        citations: [],
                        stripped: [],
                        evidence: { sources: live.sources, counts: live.counts },
                      }}
                    />
                  ) : (
                    <Retrieving counts={live.counts} />
                  )}
                </>
              )}

              {error && (
                <p className="rounded-lg border border-bad/40 bg-bad/5 px-3 py-2 text-[12px] text-bad">
                  {error}
                </p>
              )}
              <div ref={bottom} />
            </div>
          </div>

          <div className="shrink-0 px-4 pb-4">
            <div className="mx-auto max-w-[760px]">
              <Composer
                value={draft}
                onChange={setDraft}
                onSend={() => send(draft)}
                onStop={() => abort.current?.abort()}
                busy={!!live}
                used={used}
                total={thread?.context_window ?? 0}
              />
            </div>
          </div>
        </>
      )}
    </div>
  )
}

/**
 * The gap between asking and the first token is real — retrieval routes the
 * question with a model, then embeds, then traverses. Saying what is happening
 * is better than a spinner that could mean anything.
 */
function Retrieving({ counts }: { counts: Record<string, number> }) {
  const found = Object.entries(counts)
  return (
    <p className="flex items-center gap-2 text-[12px] text-ink-dim">
      <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-hot" />
      {found.length
        ? `Reading ${found.map(([k, v]) => `${v} ${k}`).join(', ')}…`
        : 'Searching the codebase…'}
    </p>
  )
}

function Empty({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="plate mx-auto mt-10 max-w-[520px] p-6 text-center">
      <h2 className="text-[14px] text-ink">{title}</h2>
      <p className="mt-2 text-[12px] leading-relaxed text-ink-mid">{children}</p>
    </section>
  )
}
