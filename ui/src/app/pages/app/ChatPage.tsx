import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../../lib/api'
import type { ChatMessage, ChatSource, ChatThread, KnowledgeBase, Project } from '../../lib/types'
import { AssistantMessage, UserMessage } from '../../components/chat/Message'
import SourcesPanel from '../../components/chat/SourcesPanel'
import RepositoryPicker from '../../components/chat/RepositoryPicker'
import { Composer } from '../../components/chat/Composer'
import ConfirmDelete from '../../components/ConfirmDelete'
import { SkeletonPanel } from '../../components/States'
import { useChatThreads } from '../../chat-threads'
import { useAsync } from '../../lib/hooks'

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
/** How many of the stored questions to offer on an empty conversation, and how many
 *  to offer as follow-ups after an answer. Fourteen are written during analysis; a
 *  list that long is a menu nobody reads. */
const OPENING = 5
const FOLLOW_UPS = 3

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
  /** Which answer's sources are open in the side panel, by message id. `-1` is the
   *  one still streaming, which has no id yet. Null closes the panel. */
  const [openSources, setOpenSources] = useState<number | null>(null)
  /** A citation clicked in an answer. The panel opens at it rather than making the
   *  reader find the same reference again in a list of twenty-nine. */
  const [focusRef, setFocusRef] = useState<string | null>(null)
  const [live, setLive] = useState<Live | null>(null)
  const abort = useRef<AbortController | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [copied, setCopied] = useState(false)
  const bottom = useRef<HTMLDivElement>(null)
  const { refresh: refreshThreads } = useChatThreads()

  const projectId = Number(params.get('project')) || projects?.[0]?.id || null
  const project = projects?.find(p => p.id === projectId) ?? null

  /** What the selected reading actually contains. The name alone does not say what
   *  you are asking about, and most projects carry no description — this is the
   *  substance that is always there. */
  const kb = useAsync<KnowledgeBase | null>(
    sig => (projectId ? api.knowledgeBase(projectId, sig) : Promise.resolve(null)),
    [projectId],
  )

  /** Written during analysis, about this repository. Empty for a reading taken
   *  before that existed — in which case nothing is offered, because a generic
   *  suggestion on this page advertises that the code has not been read. */
  const suggestions = useMemo(() => {
    const all = kb.data?.suggested_questions ?? []
    // Shuffled, so opening a second conversation does not offer the same five.
    // Fourteen are written and five are shown; always taking the first five would
    // mean nine of them were never seen. Fixed for the life of this thread —
    // re-drawing on every keystroke would move a row out from under the cursor.
    return [...all].sort(() => Math.random() - 0.5)
  }, [kb.data, thread?.id])

  // `new` is a real state, not the absence of one. Without it, pressing New chat
  // and reloading would silently resume the conversation it was meant to leave.
  const threadParam = params.get('thread')
  const wantsNew = threadParam === 'new'
  const wantedId = Number(threadParam) || null

  useEffect(() => {
    api
      .projects()
      .then(setProjects)
      .catch(() => setProjects([]))
  }, [])

  // Load the conversation the URL names, or the most recent one.
  useEffect(() => {
    if (!projectId) {
      setLoading(false)
      return
    }
    if (wantsNew) {
      setThread(null)
      setLive(null)
      setLoading(false)
      return
    }
    let alive = true
    setLoading(true)
    setError(null)
    api
      .chatThread(projectId, wantedId ?? undefined)
      .then(t => alive && setThread(t))
      .catch(() => alive && setThread(null))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [projectId, wantedId, wantsNew])

  const messages = thread?.messages ?? []

  /** Questions this conversation has not covered. Drawn from the same stored set
   *  rather than generated per answer: it costs nothing, adds no latency, and every
   *  one of them is still about this repository. A genuinely contextual follow-up
   *  would need another model call after every reply, which is a lot to pay for a
   *  suggestion somebody may not click. */
  const unasked = useMemo(() => {
    const asked = new Set(
      messages.filter(m => m.role === 'user').map(m => m.content.trim().toLowerCase()),
    )
    return suggestions.filter(q => !asked.has(q.trim().toLowerCase()))
  }, [suggestions, messages])

  /** Whether the question being answered is already in `messages`. See where it is
   *  used: the same question would otherwise be rendered twice mid-stream. */
  const questionAlreadyStored = useMemo(() => {
    const last = messages[messages.length - 1]
    return !!live && !!last && last.role === 'user' && last.content === live.question
  }, [messages, live])

  const lastAnswerId = useMemo(() => {
    const answers = messages.filter(m => m.role === 'assistant')
    return answers.length ? answers[answers.length - 1].id : null
  }, [messages])
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
                // A new conversation now has an id. Putting it in the URL is what
                // makes reload, the back button and the rail's highlight all agree
                // about which conversation is open.
                if (wantsNew || !wantedId) {
                  setParams(
                    { project: String(projectId), thread: String(event.thread_id) },
                    { replace: true },
                  )
                }
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
          api.chatThread(projectId, thread?.id).then(setThread).catch(() => undefined)
        }
        // The rail shows titles and orders by recency; both just changed.
        void refreshThreads()
      }
    },
    [projectId, thread?.id, live, wantsNew, wantedId, setParams, refreshThreads],
  )

  const clear = useCallback(async () => {
    if (!projectId || !thread) return
    await api.clearChat(projectId, thread.id)
    const fresh = await api.chatThread(projectId, thread.id).catch(() => null)
    setThread(fresh)
    void refreshThreads()
  }, [projectId, thread, refreshThreads])

  /** Copying the link is the honest version of "share" for something that never
   *  leaves the machine. Anyone who can reach this studio can open it. */
  const share = useCallback(async () => {
    if (!projectId || !thread) return
    const url = `${window.location.origin}/app/chat?project=${projectId}&thread=${thread.id}`
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1600)
    } catch {
      setError('The link could not be copied. Your browser blocked clipboard access.')
    }
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
    /* `h-full` rather than a viewport calculation: the outlet's container is a
       flex item with a definite height, so this stays right when the running-job
       bar appears above it and changes what "the rest of the screen" means. */
    <div className="flex h-full min-h-0 flex-col">
      {/* The bar had no ground of its own and its one control read as body text.
          A panel background, a rule under it and real padding give it a shelf to
          sit on; the actions are bordered so they look like things you press. */}
      <header className="shrink-0 border-b border-rule bg-panel px-4 py-2.5">
        {/* Full width, not centred on 980px. The picker was the first thing on the
            line and still landed in the middle of the screen, floating away from the
            edge everything else in the studio is anchored to. */}
        <div className="flex items-center gap-4">
          {/* Empty until there is a conversation. On a new one the picker is in
              the middle of the page, where the reader is looking, and repeating it
              up here would be two controls for one choice. */}
          {messages.length > 0 && (
            <div className="flex min-w-0 shrink-0 flex-col gap-1">
              <div className="flex items-center gap-2">
                <span className="tag shrink-0 text-ink-dim">asking</span>
                {/* Shown, not offered. Changing the repository mid-thread would leave
                    every answer above grounded in a codebase no longer selected — the
                    citations would still resolve, against a knowledge base nobody is
                    looking at. */}
                <span className="max-w-[260px] truncate text-[12px] font-semibold text-ink">
                  {project?.name ?? '—'}
                </span>
              </div>
              <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5 pl-[52px] text-[10.5px] text-ink-dim">
                {project?.kb_status && (
                  <span className={project.kb_status === 'stale' ? 'text-warn' : 'text-ok'}>
                    {project.kb_status === 'stale' ? 'reading is stale' : 'analysed'}
                  </span>
                )}
                {kb.data?.knowledge_base && (
                  <>
                    <span>{kb.data.module_count} modules</span>
                    <span>{kb.data.entity_count} entities</span>
                    {kb.data.knowledge_base.commit_sha && (
                      <span className="font-mono">
                        @{kb.data.knowledge_base.commit_sha.slice(0, 8)}
                      </span>
                    )}
                  </>
                )}
              </div>
            </div>
          )}

          {/* Left-aligned to the conversation column, not centred on the window.
              A title centred on the screen sits over the middle of the messages; the
              same 760px column the answers are in is the line the eye is following,
              so the title starts where they start. */}
          <div className="min-w-0 flex-1 px-4">
            <div className="mx-auto max-w-[760px]">
            <h1 className="truncate text-[13.5px] leading-snug text-ink">
              {thread && messages.length ? thread.title : 'New conversation'}
            </h1>
            {project?.description ? (
              <p
                className="truncate font-sans text-[11px] text-ink-mid"
                title={project.description}
              >
                {project.description}
              </p>
            ) : (
              project?.sources?.[0]?.url_or_path && (
                <p
                  className="truncate font-mono text-[10.5px] text-ink-dim"
                  title={project.sources[0].url_or_path}
                >
                  {project.sources[0].url_or_path}
                </p>
              )
            )}
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            {!!messages.length && (
              <button
                type="button"
                onClick={share}
                className="border border-rule px-2.5 py-[5px] text-[11px] text-ink-mid transition-colors hover:border-hot hover:text-hot-ink"
              >
                {copied ? 'link copied' : 'share'}
              </button>
            )}
            {!!messages.length && (
              <button
                type="button"
                onClick={() => setConfirming(true)}
                className="border border-hot bg-hot-wash px-2.5 py-[5px] text-[11px] font-semibold text-hot-ink transition-colors hover:bg-hot hover:text-paper"
              >
                clear conversation
              </button>
            )}
          </div>
        </div>
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
          <div className="w-full max-w-[820px]">
            {/* The choice belongs where the eye already is, and it needs to be
                readable before it is made — in the header it was a name in a
                drop-down that told you nothing about what you were choosing
                between. */}
            <div className="mb-6">
              <RepositoryPicker
                projects={projects}
                selectedId={projectId}
                onSelect={id => {
                  setParams({ project: String(id), thread: 'new' })
                  setThread(null)
                }}
              />

              {/* What was found in it. The same material the codebase page leads
                  with, so the reader recognises it rather than parsing something
                  new — a name alone does not distinguish two analysed repositories. */}
              {kb.data && (
                <div className="border border-t-0 border-rule bg-sunk/40 px-3 py-2.5">
                  <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-[11px] text-ink-dim">
                    <span className="text-ink">{kb.data.module_count} modules</span>
                    <span>{kb.data.entity_count} entities</span>
                    {!!kb.data.knowledge_base.stats?.indexed_chunks && (
                      <span>
                        {kb.data.knowledge_base.stats.indexed_chunks.toLocaleString()} indexed
                      </span>
                    )}
                    {kb.data.knowledge_base.commit_sha && (
                      <span className="font-mono">
                        @{kb.data.knowledge_base.commit_sha.slice(0, 8)}
                      </span>
                    )}
                    {!!kb.data.languages?.length && (
                      <span className="ml-auto flex flex-wrap gap-1">
                        {kb.data.languages.map(l => (
                          <span
                            key={l}
                            className="tag border border-hot-edge bg-hot-wash px-1.5 py-px text-hot-ink"
                          >
                            {l}
                          </span>
                        ))}
                      </span>
                    )}
                  </div>

                  {/* The largest module's own summary. Not the project's
                      `description`, which is empty on every project created without
                      one — an accurate sentence about the biggest thing in the
                      repository beats a blank line where a description should be. */}
                  {kb.data.top_modules?.[0]?.summary && (
                    <p className="mt-2 font-sans text-[11.5px] leading-relaxed text-ink-mid">
                      {kb.data.top_modules[0].summary.split('. ').slice(0, 2).join('. ')}
                    </p>
                  )}

                  {!!kb.data.entrypoints?.length && (
                    <p className="mt-1.5 truncate font-mono text-[10.5px] text-ink-dim">
                      entry: {kb.data.entrypoints.slice(0, 3).join('  ·  ')}
                    </p>
                  )}
                </div>
              )}
            </div>

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

            {/* One per line. As pills they wrapped into a paragraph of fragments —
                readable only as shapes, and a question is a sentence you read. */}
            {!!suggestions.length && (
              <ul className="mt-5 border-t border-rule pt-3">
                {suggestions.slice(0, OPENING).map(q => (
                  <li key={q}>
                    <button
                      type="button"
                      onClick={() => send(q)}
                      className="group flex w-full items-baseline gap-2 py-[5px] text-left text-[12px] text-ink-mid transition-colors hover:text-hot-ink"
                    >
                      <span className="text-hot opacity-60 group-hover:opacity-100">→</span>
                      <span className="underline-offset-4 group-hover:underline">{q}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      ) : (
        <div className="relative flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6">
            <div className="mx-auto flex max-w-[760px] flex-col gap-6">
              {messages.map(m =>
                m.role === 'user' ? (
                  <UserMessage key={m.id} content={m.content} />
                ) : (
                  <AssistantMessage
                    key={m.id}
                    message={m}
                    followUps={
                      // Only under the newest answer: three suggestions after every
                      // message in a long thread is a page of them.
                      m.id === lastAnswerId ? unasked.slice(0, FOLLOW_UPS) : []
                    }
                    onAsk={send}
                    sourcesOpen={openSources === m.id}
                    onOpenSources={() => {
                      setFocusRef(null)
                      setOpenSources(o => (o === m.id ? null : m.id))
                    }}
                    onCitation={ref => {
                      setOpenSources(m.id)
                      setFocusRef(ref)
                    }}
                  />
                ),
              )}

              {live && (
                <>
                  {/* The optimistic copy, only while the stored one has not arrived.
                      Streaming puts the new thread id in the URL, which re-fetches the
                      thread — and that fetch already contains the question, so both
                      were on screen until the answer finished and the live block was
                      cleared. */}
                  {!questionAlreadyStored && <UserMessage content={live.question} />}
                  {live.answer ? (
                    <AssistantMessage
                      streaming
                      sourcesOpen={openSources === -1}
                      onOpenSources={() => {
                        setFocusRef(null)
                        setOpenSources(o => (o === -1 ? null : -1))
                      }}
                      onCitation={ref => {
                        setOpenSources(-1)
                        setFocusRef(ref)
                      }}
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
        </div>

        {/* Beside the conversation, so the claim being checked stays on screen.
            Only for the answer whose button was pressed — a panel showing "the
            sources", unqualified, would be the sources of whichever answer
            happened to be last. */}
        {openSources !== null && projectId !== null && (() => {
          const target =
            openSources === -1
              ? live && {
                  evidence: { sources: live.sources, counts: live.counts },
                  stripped: [] as string[],
                }
              : messages.find(m => m.id === openSources)
          if (!target) return null
          return (
            <SourcesPanel
              projectId={projectId}
              sources={target.evidence?.sources ?? []}
              counts={target.evidence?.counts ?? {}}
              unverified={target.stripped ?? []}
              focusRef={focusRef}
              onClose={() => {
                setOpenSources(null)
                setFocusRef(null)
              }}
            />
          )
        })()}
        </div>
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
    <div className="flex items-center gap-2.5">
      {/* Three dots out of phase. One pulsing dot is indistinguishable from a
          rendering artefact, and this stage can run for several seconds before a
          token appears — long enough that "is it working?" is a real question. */}
      <span className="flex items-center gap-1">
        {[0, 1, 2].map(i => (
          <span
            key={i}
            className="block size-[5px] rounded-full bg-hot"
            style={{ animation: `chat-bounce 1.05s ease-in-out ${i * 0.16}s infinite` }}
          />
        ))}
      </span>
      <span className="text-[12px] text-ink-dim">
        {found.length
          ? `Reading ${found.map(([k, v]) => `${v} ${k}`).join(', ')}…`
          : 'Searching the codebase…'}
      </span>
      {/* The counts arrive before the answer does, so this line changes as evidence
          lands — the movement above says "running", this says what it is doing. */}
    </div>
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
