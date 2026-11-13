import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../../lib/api'
import { Icon, type IconName } from '../../lib/icons'
import type { ChatScope, ChatSource, ChatToolStep, EvidenceBody, RetrievalInspection } from '../../lib/types'
import { Markdown } from '../Markdown'
import { DECIDED_BY, VERDICT, type TraceStep } from './trace'

/* ------------------------------------------------------------------ *
 * The right pane: what one answer was built from, beside it rather than
 * under it, in three tabs.
 *
 *   Citations  the references the answer makes, each checked against what
 *              was retrieved; click one to read the lines it points at
 *   Sources    everything retrieval returned, grouped by the store it came
 *              from, and (in development builds) everything the question
 *              retrieves, with bodies and scores
 *   Thinking   the gate's verdict and reason, the route, the stores
 *              searched, each extra search the model made, the answer
 *
 * Code and prose fetch their real text on demand; it is not stored on the
 * message, because forty spans of several kilobytes would multiply a
 * conversation by the size of the code it quoted.
 * ------------------------------------------------------------------ */

export type InsightTab = 'citations' | 'sources' | 'thinking'

export interface InsightTarget {
  question: string | null
  sources: ChatSource[]
  counts: Record<string, number>
  citations: string[]
  stripped: string[]
  scope?: ChatScope
  intents?: string[]
  routedBy?: string
  tools?: ChatToolStep[]
  steps: TraceStep[]
  streaming: boolean
}

export const SOURCE_KIND: Record<string, { label: string; icon: IconName }> = {
  code: { label: 'Code', icon: 'file-code' },
  prose: { label: 'Prose', icon: 'file-text' },
  entity: { label: 'Facts', icon: 'hash' },
  graph: { label: 'Code graph', icon: 'network' },
  narrative: { label: 'Narratives', icon: 'book-open-text' },
}
const kindOf = (k: string) => SOURCE_KIND[k] ?? { label: k, icon: 'info' as IconName }

/** Only a span of a file has more to show than its own title. */
const openable = (kind: string) => kind === 'code' || kind === 'prose'

/** The path and range inside a title, ignoring a `(markdown, unverified)` suffix. */
const refKey = (title: string) => title.replace(/\s*\([^)]*\)\s*$/, '').trim()

/** `path:12-30` into the atlas link that opens that file at that line. */
function atlasLink(projectId: number, path: string, line: number | null) {
  return `/app/projects/${projectId}/graph?file=${encodeURIComponent(path)}${line != null ? `&line=${line}` : ''}`
}

function Body({ projectId, refText }: { projectId: number; refText: string }) {
  const [body, setBody] = useState<EvidenceBody | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    api
      .evidence(projectId, refText)
      .then(b => live && setBody(b))
      .catch(e => live && setError(e instanceof ApiError ? e.message : 'Could not read that source.'))
    return () => {
      live = false
    }
  }, [projectId, refText])

  if (error) return <p className="px-3 py-2 text-[12px] text-bad">{error}</p>
  if (!body) return <p className="px-3 py-2 text-[12px] text-ink-dim">Reading…</p>
  const fence = ['```' + (body.language ?? ''), body.content, '```'].join('\n')
  return (
    <div className="border-t border-rule">
      {body.partial && (
        <p className="border-b border-rule bg-warn-wash px-3 py-1.5 text-[12px] text-warn">
          Those exact lines are no longer stored; the file has been re-analysed since.
          Showing what is there now.
        </p>
      )}
      <div className="doc chat-answer max-h-[360px] overflow-auto px-2 py-1 text-[11px]">
        <Markdown>{fence}</Markdown>
      </div>
      <p className="flex items-center gap-2 border-t border-rule px-3 py-1.5 font-mono text-[11px] text-ink-dim">
        <span className="min-w-0 flex-1 truncate">
          {body.path}
          {body.start_line != null && `:${body.start_line}-${body.end_line}`}
        </span>
        <Link
          to={atlasLink(projectId, body.path, body.start_line)}
          className="flex shrink-0 items-center gap-1 font-sans text-hot-ink hover:underline"
        >
          <Icon name="waypoints" size={12} /> Open in the knowledge graph
        </Link>
      </p>
    </div>
  )
}

function SourceRow({
  source,
  projectId,
  focused,
}: {
  source: ChatSource
  projectId: number
  focused: boolean
}) {
  const [open, setOpen] = useState(false)
  const can = openable(source.kind)
  const kind = kindOf(source.kind)
  return (
    <li className={`overflow-hidden rounded-lg border ${focused ? 'border-hot-edge bg-hot-wash/40' : 'border-rule'}`}>
      <button
        type="button"
        disabled={!can}
        onClick={() => setOpen(o => !o)}
        className={`flex w-full items-start gap-2.5 px-3 py-2 text-left transition-colors ${can ? 'hover:bg-hover' : 'cursor-default'}`}
      >
        <Icon name={kind.icon} size={15} className="mt-0.5 text-ink-dim" />
        <span className="min-w-0 flex-1">
          <span className="block font-mono text-[12px] break-all text-ink">{source.title}</span>
          {source.why && <span className="mt-0.5 block text-[12px] leading-snug text-ink-dim">{source.why}</span>}
        </span>
        {can && <Icon name={open ? 'chevron-down' : 'chevron-right'} size={14} className="mt-0.5 text-ink-dim" />}
      </button>
      {open && can && <Body projectId={projectId} refText={source.title} />}
    </li>
  )
}

function CitationRow({ projectId, refText, pinned }: { projectId: number; refText: string; pinned: boolean }) {
  const [open, setOpen] = useState(pinned)
  useEffect(() => {
    if (pinned) setOpen(true)
  }, [pinned])
  return (
    <li className={`overflow-hidden rounded-lg border ${pinned ? 'border-hot-edge' : 'border-rule'}`}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors hover:bg-hover"
      >
        <Icon name="circle-check" size={15} className="text-ok" />
        <span className="min-w-0 flex-1 font-mono text-[12px] break-all text-ink">{refText}</span>
        <Icon name={open ? 'chevron-down' : 'chevron-right'} size={14} className="text-ink-dim" />
      </button>
      {open && <Body key={refText} projectId={projectId} refText={refText} />}
    </li>
  )
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="px-1 py-2 text-[13px] leading-relaxed text-ink-dim">{children}</p>
}

function Citations({ projectId, target, focusRef }: { projectId: number; target: InsightTarget; focusRef: string | null }) {
  // A clicked reference is shown as itself, even when it is not in the checked list:
  // the model cites the lines it used, and those need not match a stored range.
  const refs = useMemo(() => {
    const out = [...target.citations]
    if (focusRef && !out.some(r => refKey(r) === refKey(focusRef))) out.unshift(focusRef)
    return out
  }, [target.citations, focusRef])

  return (
    <div className="flex flex-col gap-3">
      {!!target.stripped.length && (
        <div className="rounded-lg border border-warn/35 bg-warn-wash px-3 py-2 text-[12.5px] leading-relaxed text-warn">
          <p className="flex items-center gap-1.5 font-medium">
            <Icon name="triangle-alert" size={14} />
            {target.stripped.length} reference{target.stripped.length === 1 ? '' : 's'} could not be checked
          </p>
          <p className="mt-1 text-warn/90">
            The model cited {target.stripped.length === 1 ? 'it' : 'them'}, but nothing retrieved contains{' '}
            {target.stripped.length === 1 ? 'it' : 'them'}, so {target.stripped.length === 1 ? 'it was' : 'they were'}{' '}
            removed from the answer:
          </p>
          <ul className="mt-1 font-mono text-[11.5px] break-all">
            {target.stripped.map(s => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </div>
      )}
      {refs.length ? (
        <ul className="flex flex-col gap-1.5">
          {refs.map(r => (
            <CitationRow
              key={r}
              projectId={projectId}
              refText={r}
              pinned={!!focusRef && refKey(r) === refKey(focusRef)}
            />
          ))}
        </ul>
      ) : (
        <Empty>
          {target.streaming
            ? 'Citations are checked when the answer finishes.'
            : target.scope && target.scope.verdict !== 'code'
              ? 'Nothing was searched for this answer, so it cites nothing.'
              : 'This answer cites nothing.'}
        </Empty>
      )}
    </div>
  )
}

function Inspect({ projectId, question }: { projectId: number; question: string }) {
  const [state, setState] = useState<
    { status: 'idle' } | { status: 'loading' } | { status: 'error'; message: string } | { status: 'done'; data: RetrievalInspection }
  >({ status: 'idle' })
  const [open, setOpen] = useState<number | null>(null)

  const run = () => {
    setState({ status: 'loading' })
    api
      .inspectRetrieval(projectId, question)
      .then(data => setState({ status: 'done', data }))
      .catch(e =>
        setState({
          status: 'error',
          message:
            e instanceof ApiError && e.status === 404
              ? 'The retrieval inspector is part of development builds only.'
              : e instanceof ApiError
                ? e.message
                : 'The inspector could not run.',
        }),
      )
  }

  if (state.status === 'idle')
    return (
      <button
        type="button"
        onClick={run}
        className="flex items-center gap-2 self-start rounded-lg border border-line-2 bg-sunk px-3 py-1.5 text-[12.5px] font-medium text-ink transition-colors hover:bg-hover"
      >
        <Icon name="search" size={14} /> Show everything this question retrieves
      </button>
    )
  if (state.status === 'loading')
    return (
      <p className="flex items-center gap-2 text-[12.5px] text-ink-dim">
        <Icon name="loader" size={14} className="anim-spin" /> Retrieving again, without answering…
      </p>
    )
  if (state.status === 'error') return <p className="text-[12.5px] text-ink-dim">{state.message}</p>

  const { data } = state
  return (
    <div className="flex flex-col gap-2">
      <p className="text-[12.5px] text-ink-mid">
        {data.items.length} items · intents {data.intents.join(', ') || 'none'}
        {data.symbols.length ? ` · symbols ${data.symbols.join(', ')}` : ''}
      </p>
      <ul className="flex flex-col gap-1.5">
        {data.items.map((it, i) => (
          <li key={i} className="overflow-hidden rounded-lg border border-rule">
            <button
              type="button"
              onClick={() => setOpen(o => (o === i ? null : i))}
              className="flex w-full items-start gap-2.5 px-3 py-2 text-left transition-colors hover:bg-hover"
            >
              <Icon name={kindOf(it.kind).icon} size={15} className="mt-0.5 text-ink-dim" />
              <span className="min-w-0 flex-1">
                <span className="block font-mono text-[12px] break-all text-ink">{it.title}</span>
                <span className="mt-0.5 block text-[12px] text-ink-dim">{it.why}</span>
              </span>
              {it.score != null && (
                <span className="shrink-0 font-mono text-[11px] text-ink-dim tabular-nums">{it.score.toFixed(2)}</span>
              )}
            </button>
            {open === i && (
              <pre className="max-h-[280px] overflow-auto border-t border-rule bg-sunk px-3 py-2 font-mono text-[11px] whitespace-pre-wrap text-ink-mid">
                {it.body}
              </pre>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

function Sources({ projectId, target, focusRef }: { projectId: number; target: InsightTarget; focusRef: string | null }) {
  const groups = useMemo(() => {
    const m = new Map<string, ChatSource[]>()
    for (const s of target.sources) m.set(s.kind, [...(m.get(s.kind) ?? []), s])
    const order = Object.keys(SOURCE_KIND)
    return [...m].sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0]))
  }, [target.sources])

  return (
    <div className="flex flex-col gap-4">
      {groups.length === 0 ? (
        <Empty>
          {target.scope && target.scope.verdict !== 'code'
            ? 'The gate decided this was not a question about the code, so nothing was retrieved.'
            : target.streaming
              ? 'Retrieving…'
              : 'Nothing was retrieved for this answer.'}
        </Empty>
      ) : (
        groups.map(([kind, items]) => (
          <section key={kind} className="flex flex-col gap-1.5">
            <h4 className="tag flex items-center gap-1.5 text-ink-dim">
              <Icon name={kindOf(kind).icon} size={13} />
              {kindOf(kind).label}
              <span className="ml-auto">{items.length}</span>
            </h4>
            <ul className="flex flex-col gap-1.5">
              {items.map((s, i) => (
                <SourceRow
                  key={`${s.title}-${i}`}
                  source={s}
                  projectId={projectId}
                  focused={!!focusRef && refKey(s.title) === refKey(focusRef)}
                />
              ))}
            </ul>
          </section>
        ))
      )}
      {target.question && !target.streaming && (!target.scope || target.scope.verdict === 'code') && (
        <section className="flex flex-col gap-2 border-t border-rule pt-4">
          <h4 className="tag text-ink-dim">Everything retrieval returns</h4>
          <p className="text-[12.5px] leading-relaxed text-ink-dim">
            The list above is what the answer was given. This runs the same retrieval again and
            shows every item with its body and score, without asking the model anything.
          </p>
          <Inspect key={target.question} projectId={projectId} question={target.question} />
        </section>
      )}
    </div>
  )
}

const STEP_TONE = {
  done: 'border-line-2 text-ink',
  active: 'border-hot-edge text-hot-ink',
  pending: 'border-rule text-ink-dim',
  skipped: 'border-dashed border-rule text-ink-dim',
} as const

function Thinking({ target }: { target: InsightTarget }) {
  const detail: Record<TraceStep['id'], React.ReactNode> = {
    gate: target.scope ? (
      <>
        <p className="text-ink">{VERDICT[target.scope.verdict]}</p>
        {target.scope.reason && <p className="mt-1">{target.scope.reason}</p>}
        {target.scope.decided_by && (
          <p className="mt-1 text-ink-dim">Decided because {DECIDED_BY[target.scope.decided_by] ?? target.scope.decided_by}.</p>
        )}
      </>
    ) : target.sources.length ? (
      <p>Recorded before the gate existed; the code was searched.</p>
    ) : null,
    route: target.intents?.length ? (
      <>
        <div className="flex flex-wrap gap-1">
          {target.intents.map(i => (
            <span key={i} className="rounded-md border border-rule px-1.5 py-0.5 font-mono text-[11.5px] text-ink">
              {i}
            </span>
          ))}
        </div>
        {target.routedBy && <p className="mt-1 text-ink-dim">Routed by {target.routedBy}.</p>}
      </>
    ) : null,
    retrieve: Object.keys(target.counts).length ? (
      <>
        <ul className="flex flex-wrap gap-x-3 gap-y-1">
          {Object.entries(target.counts).map(([k, v]) => (
            <li key={k} className="flex items-center gap-1.5">
              <Icon name={kindOf(k).icon} size={13} className="text-ink-dim" />
              <span className="text-ink tabular-nums">{v}</span> {kindOf(k).label.toLowerCase()}
            </li>
          ))}
        </ul>
        {!!target.tools?.length && (
          <ol className="mt-2 flex flex-col gap-1">
            {target.tools.map(t => (
              <li key={t.step} className="font-mono text-[11.5px] break-all text-ink-mid">
                <span className="text-ink-dim">{t.step}.</span> {t.name}({Object.entries(t.args)
                  .map(([k, v]) => `${k}: ${JSON.stringify(v)}`)
                  .join(', ')})
              </li>
            ))}
          </ol>
        )}
      </>
    ) : null,
    answer: null,
  }

  return (
    <ol className="flex flex-col">
      {target.steps.map((s, i) => (
        <li key={s.id} className="relative flex gap-3 pb-4 last:pb-0">
          {i < target.steps.length - 1 && <span className="absolute top-8 bottom-0 left-[15px] w-px bg-rule" aria-hidden />}
          <span className={`grid size-8 shrink-0 place-items-center rounded-full border bg-panel ${STEP_TONE[s.state]}`}>
            <Icon name={s.state === 'active' ? 'loader' : s.icon} size={15} className={s.state === 'active' ? 'anim-spin' : ''} />
          </span>
          <div className="min-w-0 flex-1 pt-1 text-[12.5px] leading-relaxed text-ink-mid">
            <p className="flex items-center gap-2">
              <span className="font-medium text-ink">{s.label}</span>
              <span className="text-ink-dim">{s.state === 'skipped' ? 'skipped' : s.detail}</span>
            </p>
            {s.state !== 'skipped' && detail[s.id] && <div className="mt-1.5">{detail[s.id]}</div>}
          </div>
        </li>
      ))}
    </ol>
  )
}

const TABS: { id: InsightTab; label: string; icon: IconName }[] = [
  { id: 'citations', label: 'Citations', icon: 'quote' },
  { id: 'sources', label: 'Sources', icon: 'database' },
  { id: 'thinking', label: 'Thinking', icon: 'brain' },
]

export default function InsightPane({
  projectId,
  target,
  tab,
  onTab,
  focusRef,
  onClose,
}: {
  projectId: number
  target: InsightTarget | null
  tab: InsightTab
  onTab: (t: InsightTab) => void
  focusRef: string | null
  /** Shown below the wide breakpoint, where the pane overlays the conversation. */
  onClose: () => void
}) {
  const count = (t: InsightTab) =>
    !target ? undefined : t === 'citations' ? target.citations.length : t === 'sources' ? target.sources.length : undefined
  return (
    <aside className="absolute inset-y-0 right-0 z-30 flex h-full min-h-0 w-[420px] max-w-[92vw] shrink-0 flex-col border-l border-rule bg-panel shadow-[-12px_0_32px_-16px_var(--shadow)] xl:relative xl:z-auto xl:shadow-none">
      <div className="flex items-center gap-2 border-b border-rule p-2">
        <div className="flex flex-1 gap-0.5 rounded-lg border border-rule bg-paper p-[3px]" role="tablist">
          {TABS.map(t => (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={tab === t.id}
              onClick={() => onTab(t.id)}
              className={`flex flex-1 items-center justify-center gap-1.5 rounded-md py-1.5 text-[12.5px] font-medium transition-colors ${
                tab === t.id ? 'bg-sunk text-ink shadow-[inset_0_0_0_1px_var(--line-2)]' : 'text-ink-mid hover:text-ink'
              }`}
            >
              <Icon name={t.icon} size={14} />
              {t.label}
              {!!count(t.id) && <span className="font-mono text-[11px] text-ink-dim">{count(t.id)}</span>}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="grid size-8 place-items-center rounded-md text-ink-dim transition-colors hover:bg-hover hover:text-ink xl:hidden"
        >
          <Icon name="x" size={16} />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {!target ? (
          <Empty>Ask something, and what the answer was built from appears here: the citations it makes, every source it was given, and each step that led to it.</Empty>
        ) : tab === 'citations' ? (
          <Citations projectId={projectId} target={target} focusRef={focusRef} />
        ) : tab === 'sources' ? (
          <Sources projectId={projectId} target={target} focusRef={focusRef} />
        ) : (
          <Thinking target={target} />
        )}
      </div>
    </aside>
  )
}
