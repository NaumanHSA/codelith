import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../../lib/api'
import type {
  ChatScope,
  ChatSource,
  ChatThread,
  ChatToolStep,
  KnowledgeBase,
  Project,
} from '../../lib/types'
import { AssistantMessage, UserMessage } from '../../components/chat/Message'
import InsightPane, { type InsightTab, type InsightTarget } from '../../components/chat/InsightPane'
import AnswerTrace from '../../components/chat/AnswerTrace'
import { messageTrace, traceSteps } from '../../components/chat/trace'
import ChatWelcome from '../../components/chat/ChatWelcome'
import { Composer } from '../../components/chat/Composer'
import ConfirmDelete from '../../components/ConfirmDelete'
import { SkeletonPanel } from '../../components/States'
import { CodebaseMark } from '../../components/primitives'
import { useChatThreads } from '../../chat-threads'
import { useAsync } from '../../lib/hooks'
import { Icon } from '../../lib/icons'

/* ------------------------------------------------------------------ *
 * Ask the codebase.
 *
 * Three panes, as the user asked to keep them: conversations down the
 * left (the sidebar), the conversation in the middle, and beside it what
 * the answer in focus was built from — citations, sources, thinking.
 *
 * Top level rather than inside a project, because it is a way of working
 * rather than a property of one repository — but the knowledge base *is*
 * per project, so the page picks one. Deep-linkable as ?project=2, and
 * `?ask=` arrives with a question already typed (the atlas sends one).
 * ------------------------------------------------------------------ */

/** How many of the stored questions to offer on an empty conversation, and how many
 *  as follow-ups after an answer. Fourteen are written during analysis; a list that
 *  long is a menu nobody reads. */
const OPENING = 5
const FOLLOW_UPS = 3

interface Live {
  question: string
  answer: string
  sources: ChatSource[]
  counts: Record<string, number>
  intents?: string[]
  routedBy?: string
  tools: ChatToolStep[]
  retrieved: boolean
  /** What the gate made of the question. Absent until it has decided, which is the
   *  only moment the page can honestly say whether the code is being searched. */
  scope?: ChatScope
}

/** Which answer the pane shows: a stored one by id, the streaming one, or (null)
 *  whichever is newest. */
type Focus = number | 'live' | null

export default function ChatPage() {
  const [params, setParams] = useSearchParams()
  const [projects, setProjects] = useState<Project[] | null>(null)
  const [thread, setThread] = useState<ChatThread | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [draft, setDraft] = useState('')
  const [focus, setFocus] = useState<Focus>(null)
  const [tab, setTab] = useState<InsightTab>('citations')
  /** Below the wide breakpoint the pane overlays the conversation, so it opens on
   *  request. Above it the pane is always there. */
  const [paneOpen, setPaneOpen] = useState(false)
  /** A citation clicked in an answer. The pane opens at it rather than making the
   *  reader find the same reference again in a list of twenty-nine. */
  const [focusRef, setFocusRef] = useState<string | null>(null)
  const [live, setLive] = useState<Live | null>(null)
  const abort = useRef<AbortController | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [copied, setCopied] = useState(false)
  const bottom = useRef<HTMLDivElement>(null)
  const { refresh: refreshThreads } = useChatThreads()

  // No default: without a codebase in the URL the page asks for one first.
  const projectId = Number(params.get('project')) || null
  const project = projects?.find(p => p.id === projectId) ?? null

  /** What the selected reading actually contains. The name alone does not say what
   *  you are asking about, and most projects carry no description. */
  const kb = useAsync<KnowledgeBase | null>(
    sig => (projectId ? api.knowledgeBase(projectId, sig) : Promise.resolve(null)),
    [projectId],
  )

  /** Written during analysis, about this repository. Shuffled once per thread so a
   *  second conversation does not offer the same five of fourteen. */
  const suggestions = useMemo(() => {
    const all = kb.data?.suggested_questions ?? []
    return [...all].sort(() => Math.random() - 0.5)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kb.data, thread?.id])

  // `new` is a real state, not the absence of one. Without it, pressing New chat
  // and reloading would silently resume the conversation it was meant to leave.
  const threadParam = params.get('thread')
  const wantsNew = threadParam === 'new'
  const wantedId = Number(threadParam) || null

  // A question handed over by another page: typed in, not sent. Sending on arrival
  // would spend a model call on a link somebody only meant to look at.
  useEffect(() => {
    const ask = params.get('ask')
    if (!ask) return
    setDraft(ask)
    setParams(
      p => {
        const next = new URLSearchParams(p)
        next.delete('ask')
        return next
      },
      { replace: true },
    )
  }, [params, setParams])

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
    setFocus(null)
    setFocusRef(null)
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

  const messages = useMemo(() => thread?.messages ?? [], [thread])

  /** Questions this conversation has not covered, from the same stored set. */
  const unasked = useMemo(() => {
    const asked = new Set(messages.filter(m => m.role === 'user').map(m => m.content.trim().toLowerCase()))
    return suggestions.filter(q => !asked.has(q.trim().toLowerCase()))
  }, [suggestions, messages])

  /** Whether the question being answered is already in `messages`: streaming puts
   *  the new thread id in the URL, which re-fetches the thread with the question. */
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
  }, [messages.length, live?.answer, live?.retrieved])

  const used = useMemo(() => {
    const stored = thread?.token_count ?? 0
    // The draft is counted at roughly four characters a token, an estimate labelled
    // as one; the authoritative number arrives with each answer.
    return stored + Math.ceil(draft.length / 4)
  }, [thread?.token_count, draft])

  const liveSteps = useMemo(
    () =>
      live
        ? traceSteps({
            scope: live.scope,
            intents: live.intents,
            routedBy: live.routedBy,
            counts: live.counts,
            sources: live.sources,
            tools: live.tools,
            retrieved: live.retrieved,
            answering: !!live.answer,
            done: false,
          })
        : [],
    [live],
  )

  const send = useCallback(
    async (text: string) => {
      const question = text.trim()
      if (!question || !projectId || live) return

      setDraft('')
      setError(null)
      setFocus(null)
      setFocusRef(null)
      setLive({ question, answer: '', sources: [], counts: {}, tools: [], retrieved: false })

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
                // makes reload, the back button and the rail's highlight agree.
                if (wantsNew || !wantedId) {
                  setParams({ project: String(projectId), thread: String(event.thread_id) }, { replace: true })
                }
                break
              case 'scope':
                setLive(l =>
                  l ? { ...l, scope: { verdict: event.verdict, reason: event.reason, decided_by: event.decided_by } } : l,
                )
                break
              case 'evidence':
                setLive(l =>
                  l
                    ? {
                        ...l,
                        sources: event.sources,
                        counts: event.counts,
                        intents: event.intents,
                        routedBy: event.routed_by,
                        retrieved: true,
                      }
                    : l,
                )
                break
              case 'tool':
                setLive(l => (l ? { ...l, tools: [...l.tools, { name: event.name, args: event.args, step: event.step }] } : l))
                break
              case 'reset':
                // The model spoke before reaching for a tool; that was a preamble.
                setLive(l => (l ? { ...l, answer: '' } : l))
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
        setFocus(f => (f === 'live' ? null : f))
        // Reload rather than splice: the server holds the checked citations and the
        // authoritative token counts.
        if (projectId) {
          api.chatThread(projectId, thread?.id).then(setThread).catch(() => undefined)
        }
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
    setFocus(null)
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

  /* The answer the pane shows, and everything it needs about it. */
  const effective: Focus = focus ?? (live ? 'live' : lastAnswerId)
  const target: InsightTarget | null = useMemo(() => {
    if (effective === 'live' && live) {
      return {
        question: live.question,
        sources: live.sources,
        counts: live.counts,
        citations: [],
        stripped: [],
        scope: live.scope,
        intents: live.intents,
        routedBy: live.routedBy,
        tools: live.tools,
        steps: liveSteps,
        streaming: true,
      }
    }
    const ix = messages.findIndex(m => m.id === effective)
    if (ix < 0) return null
    const m = messages[ix]
    const asked = [...messages.slice(0, ix)].reverse().find(x => x.role === 'user')
    return {
      question: asked?.content ?? null,
      sources: m.evidence?.sources ?? [],
      counts: m.evidence?.counts ?? {},
      citations: m.citations ?? [],
      stripped: m.stripped ?? [],
      scope: m.evidence?.scope,
      intents: m.evidence?.intents,
      routedBy: m.evidence?.routed_by,
      tools: m.evidence?.tools,
      steps: messageTrace(m),
      streaming: false,
    }
  }, [effective, live, liveSteps, messages])

  const open = (id: Focus, t: InsightTab, ref: string | null = null) => {
    setFocus(id)
    setTab(t)
    setFocusRef(ref)
    setPaneOpen(true)
  }

  if (projects === null)
    return (
      <div className="w-full px-6 py-5">
        <SkeletonPanel rows={6} />
      </div>
    )

  if (!projects.length) {
    return (
      <div className="grid h-full place-items-center px-6">
        <div className="max-w-[460px] text-center">
          <Icon name="folder-plus" size={28} className="mx-auto text-ink-dim" />
          <h2 className="mt-3 text-[17px] font-semibold text-ink">No codebases yet</h2>
          <p className="mt-2 text-[13.5px] leading-relaxed text-ink-mid">
            Analyse a repository first: there is nothing to ask about until one has been read.
          </p>
          <Link
            to="/app/projects"
            className="mt-4 inline-flex items-center gap-2 rounded-lg bg-hot px-3.5 py-2 text-[13px] font-medium text-on-hot hover:bg-hot-ink"
          >
            <Icon name="plus" size={15} /> Add a codebase
          </Link>
        </div>
      </div>
    )
  }

  if (!projectId) {
    return (
      <ChatWelcome
        projects={projects}
        onPick={id => {
          setParams({ project: String(id), thread: 'new' })
          setThread(null)
        }}
      />
    )
  }

  const stats = kb.data?.knowledge_base

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex shrink-0 items-center gap-4 border-b border-rule px-4 py-3 md:px-6">
        {messages.length > 0 && project && (
          <div className="hidden min-w-0 shrink-0 items-center gap-2.5 md:flex">
            <CodebaseMark project={project} size={18} />
            <div className="min-w-0">
              <div className="truncate text-[13.5px] font-medium text-ink">{project.name}</div>
              <div className="flex flex-wrap gap-x-2 text-[11.5px] text-ink-dim">
                <span className={project.kb_status === 'stale' ? 'text-warn' : 'text-ok'}>
                  {project.kb_status === 'stale' ? 'Reading is stale' : 'Analysed'}
                </span>
                {kb.data && <span>{kb.data.module_count} modules</span>}
                {kb.data && <span>{kb.data.entity_count} facts</span>}
                {stats?.commit_sha && <span className="font-mono">{stats.commit_sha.slice(0, 7)}</span>}
              </div>
            </div>
          </div>
        )}
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-[15px] leading-snug font-semibold text-ink">
            {thread && messages.length ? thread.title : 'New conversation'}
          </h1>
        </div>
        {!!messages.length && (
          <div className="flex shrink-0 items-center gap-1.5">
            <button
              type="button"
              onClick={share}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line-2 px-3 text-[12.5px] font-medium text-ink-mid transition-colors hover:bg-hover hover:text-ink"
            >
              <Icon name={copied ? 'check' : 'link'} size={14} />
              <span className="hidden sm:inline">{copied ? 'Link copied' : 'Copy link'}</span>
            </button>
            <button
              type="button"
              onClick={() => setConfirming(true)}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line-2 px-3 text-[12.5px] font-medium text-ink-mid transition-colors hover:border-bad/50 hover:bg-bad-wash hover:text-bad"
            >
              <Icon name="trash" size={14} />
              <span className="hidden sm:inline">Clear</span>
            </button>
            <button
              type="button"
              onClick={() => setPaneOpen(o => !o)}
              aria-label="Citations, sources and thinking"
              className="grid size-8 place-items-center rounded-lg border border-line-2 text-ink-mid transition-colors hover:bg-hover hover:text-ink xl:hidden"
            >
              <Icon name="panel-right" size={15} />
            </button>
          </div>
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
        <div className="px-6 pt-6">
          <SkeletonPanel rows={5} />
        </div>
      ) : empty ? (
        /* Nothing said yet: the composer sits in the middle of the room. */
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center overflow-y-auto px-6 py-8">
          <div className="w-full max-w-[820px]">
            <div className="mb-8 flex flex-col gap-2">
              <div className="flex items-center gap-3 rounded-xl border border-rule bg-panel px-4 py-3">
                {project && (
                  <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-sunk shadow-[inset_0_0_0_1px_var(--line-2)]">
                    <CodebaseMark project={project} size={18} />
                  </span>
                )}
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[14px] font-medium text-ink">{project?.name ?? 'Codebase'}</span>
                  <span className="block truncate font-mono text-[11.5px] text-ink-dim">
                    {project?.sources?.[0]?.url_or_path ?? project?.slug}
                  </span>
                </span>
                <Link
                  to="/app/chat"
                  className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-line-2 bg-sunk px-3 py-1.5 text-[12.5px] font-medium text-ink-mid transition-colors hover:bg-hover hover:text-ink"
                >
                  <Icon name="folder-git-2" size={14} /> Change codebase
                </Link>
              </div>
              {kb.data && (
                <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 px-1 text-[12.5px] text-ink-dim">
                  <span className="text-ink-mid">{kb.data.module_count} modules</span>
                  <span>{kb.data.entity_count} facts</span>
                  {!!stats?.stats?.indexed_chunks && <span>{stats.stats.indexed_chunks.toLocaleString()} indexed</span>}
                  {stats?.commit_sha && <span className="font-mono">{stats.commit_sha.slice(0, 7)}</span>}
                  {!!kb.data.entrypoints?.length && (
                    <span className="min-w-0 truncate font-mono">entry: {kb.data.entrypoints.slice(0, 2).join(', ')}</span>
                  )}
                </div>
              )}
            </div>

            <h2 className="mb-2 text-center text-[26px] font-semibold text-ink">
              What do you want to know about <span className="text-hot-ink">{project?.name ?? 'this codebase'}</span>?
            </h2>
            <p className="mb-6 text-center text-[13.5px] text-ink-mid">
              Answers are grounded in the analysed source, and every reference is checked against what was
              actually retrieved.
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

            {!!suggestions.length && (
              <ul className="mt-6 flex flex-col">
                <li className="tag mb-1 px-2 text-ink-dim">Questions analysis wrote for this codebase</li>
                {suggestions.slice(0, OPENING).map(q => (
                  <li key={q}>
                    <button
                      type="button"
                      onClick={() => send(q)}
                      className="group flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-left text-[13.5px] text-ink-mid transition-colors hover:bg-hover hover:text-ink"
                    >
                      <Icon name="message-square" size={15} className="text-ink-dim group-hover:text-hot" />
                      {q}
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
            <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6">
              <div className="mx-auto flex max-w-[900px] flex-col gap-7">
                {messages.map(m =>
                  m.role === 'user' ? (
                    <UserMessage key={m.id} content={m.content} />
                  ) : (
                    <AssistantMessage
                      key={m.id}
                      message={m}
                      steps={messageTrace(m)}
                      focused={effective === m.id}
                      openTab={tab}
                      followUps={m.id === lastAnswerId && !live ? unasked.slice(0, FOLLOW_UPS) : []}
                      onAsk={send}
                      projectId={projectId ?? undefined}
                      onOpen={t => open(m.id, t)}
                      onCitation={ref => open(m.id, 'citations', ref)}
                    />
                  ),
                )}

                {live && (
                  <>
                    {!questionAlreadyStored && <UserMessage content={live.question} />}
                    {live.answer ? (
                      <AssistantMessage
                        streaming
                        steps={liveSteps}
                        focused={effective === 'live'}
                        onCitation={ref => open('live', 'citations', ref)}
                        message={{
                          content: live.answer,
                          citations: [],
                          stripped: [],
                          evidence: { sources: live.sources, counts: live.counts, scope: live.scope },
                        }}
                      />
                    ) : (
                      <div className="flex flex-col gap-3">
                        <AnswerTrace steps={liveSteps} onOpen={() => open('live', 'thinking')} />
                        <p className="flex items-center gap-2 text-[13px] text-ink-dim">
                          <span className="flex items-center gap-1">
                            {[0, 1, 2].map(i => (
                              <span
                                key={i}
                                className="block size-[5px] rounded-full bg-hot"
                                style={{ animation: `chat-bounce 1.05s ease-in-out ${i * 0.16}s infinite` }}
                              />
                            ))}
                          </span>
                          {liveSteps.find(s => s.state === 'active')?.detail ?? 'Working'}…
                        </p>
                      </div>
                    )}
                  </>
                )}

                {error && (
                  <p className="flex items-start gap-2 rounded-lg border border-bad/40 bg-bad-wash px-3 py-2 text-[13px] text-bad">
                    <Icon name="circle-x" size={15} className="mt-0.5" />
                    {error}
                  </p>
                )}
                <div ref={bottom} />
              </div>
            </div>

            <div className="shrink-0 px-6 pb-5">
              <div className="mx-auto max-w-[900px]">
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

          {projectId !== null && (
            <div className={`${paneOpen ? 'contents' : 'hidden'} xl:contents`}>
              <InsightPane
                projectId={projectId}
                target={target}
                tab={tab}
                onTab={setTab}
                focusRef={focusRef}
                onClose={() => setPaneOpen(false)}
              />
            </div>
          )}
        </div>
      )}
    </div>
  )
}
