import { useEffect, useState } from 'react'
import { api, ApiError } from '../../lib/api'
import { Markdown } from '../Markdown'
import type { ChatSource, EvidenceBody } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * What one answer was built from, beside it rather than under it.
 *
 * The list used to expand inline, which pushed the answer you were
 * reading off the screen to show you the twenty-nine things it came
 * from — and the reason to open sources is almost always to check a
 * claim you can still see. Beside the answer, both stay.
 *
 * And a source now opens. `src/faceAttr/faceAttr.js:1-17` is a promise
 * that something is there; it was never the thing itself, and checking
 * it meant leaving the answer, finding the file and counting lines.
 * Code and prose fetch their real text on demand — not stored on the
 * message, because forty spans of several kilobytes each would multiply
 * a conversation by the size of the code it quoted, for material the
 * knowledge base already holds.
 *
 * The other kinds do not open, because there is nothing more to show:
 * an entity, a graph traversal or a narrative topic is entirely
 * described by the line already on screen.
 * ------------------------------------------------------------------ */

const KIND_TONE: Record<string, string> = {
  code: 'text-hot-ink border-hot-edge bg-hot-wash',
  prose: 'text-warn border-warn/40 bg-warn-wash',
  entity: 'text-ok border-ok/40 bg-ok-wash',
  graph: 'text-ink border-rule bg-sunk',
  narrative: 'text-ink-mid border-rule bg-sunk',
}

/** Only a span of a file has more to show than its own title. */
const openable = (kind: string) => kind === 'code' || kind === 'prose'

function Body({ projectId, refText }: { projectId: number; refText: string }) {
  const [body, setBody] = useState<EvidenceBody | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    api
      .evidence(projectId, refText)
      .then(b => live && setBody(b))
      .catch(e =>
        live && setError(e instanceof ApiError ? e.message : 'Could not read that source.'),
      )
    return () => {
      live = false
    }
  }, [projectId, refText])

  if (error) {
    return <p className="px-2.5 py-2 font-sans text-[11px] text-bad">{error}</p>
  }
  if (!body) {
    return <p className="px-2.5 py-2 font-sans text-[11px] text-ink-dim">reading…</p>
  }
  // Through the markdown renderer as a fenced block, so it gets the same
  // highlighting and the same copy button as code anywhere else in the product —
  // rather than a `<pre>` of grey text that happens to contain source.
  const fence = ['```' + (body.language ?? ''), body.content, '```'].join('\n')
  return (
    <div className="border-t border-rule bg-sunk/40">
      {body.partial && (
        <p className="border-b border-rule bg-warn-wash px-2.5 py-1 font-sans text-[10.5px] text-warn">
          Those exact lines are no longer stored. This file has been re-analysed since.
          Showing what is there now.
        </p>
      )}
      <div className="doc chat-answer max-h-[360px] overflow-auto px-2 py-1 text-[10.5px]">
        <Markdown>{fence}</Markdown>
      </div>
      <p className="border-t border-rule px-2.5 py-1 font-mono text-[10px] text-ink-dim">
        {body.path}
        {body.start_line != null && `:${body.start_line}-${body.end_line}`}
      </p>
    </div>
  )
}

/** The path and range inside a title, ignoring a `(markdown, unverified)` suffix.
 *  A citation in the answer is written without it, so the two only match once both
 *  are reduced to the part that identifies the span. */
const refKey = (title: string) => title.replace(/\s*\([^)]*\)\s*$/, '').trim()

function Source({
  source,
  projectId,
  focused,
}: {
  source: ChatSource
  projectId: number
  /** The clicked citation also happens to be this row. Highlighted so it can be
   *  found in the list — but not opened or scrolled to, because the pinned block
   *  above is already showing it and two copies of the same excerpt fighting over
   *  the scroll position is worse than one. */
  focused: boolean
}) {
  const [open, setOpen] = useState(false)
  const can = openable(source.kind)

  return (
    <li
      className={`border-b border-rule last:border-b-0 ${focused ? 'bg-hot-wash/50' : ''}`}
    >
      <button
        type="button"
        disabled={!can}
        onClick={() => setOpen(o => !o)}
        className={`flex w-full items-start gap-2 px-2.5 py-2 text-left transition-colors ${
          can ? 'hover:bg-sunk/70' : 'cursor-default'
        }`}
      >
        <span
          className={`tag mt-px shrink-0 border px-1 ${
            KIND_TONE[source.kind] ?? 'border-rule bg-sunk text-ink-dim'
          }`}
        >
          {source.kind}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block break-all font-mono text-[11px] text-ink">{source.title}</span>
          <span className="mt-0.5 block font-sans text-[10.5px] leading-snug text-ink-dim">
            {source.why}
          </span>
        </span>
        {can && <span className="tag mt-px shrink-0 text-ink-dim">{open ? '−' : '+'}</span>}
      </button>
      {open && can && <Body projectId={projectId} refText={source.title} />}
    </li>
  )
}

/** The reference a reader clicked, shown as itself.
 *
 *  Not found in the list — looked up directly. The model cites the lines it used and
 *  the panel lists the chunks that were retrieved, and those are not the same ranges:
 *  an answer citing `livenessLoop.js:177-194` sits inside a source row that says
 *  `131-210`, and `defaults.js:39-57` inside one that says `1-57`. Matching titles
 *  worked for four of six citations in a real answer and silently did nothing for the
 *  other two.
 *
 *  So the click is honoured literally. You asked for 177-194; you get 177-194. */
function Pinned({ projectId, refText }: { projectId: number; refText: string }) {
  return (
    <div className="border-b-2 border-hot bg-hot-wash/40">
      <div className="flex items-center gap-2 px-2.5 pt-2">
        <span className="tag border border-hot-edge bg-hot-wash px-1 text-hot-ink">cited</span>
        <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-ink">{refText}</span>
      </div>
      {/* Keyed on the reference so clicking a second citation replaces this rather
          than leaving the first one's text under a new heading. */}
      <Body key={refText} projectId={projectId} refText={refText} />
    </div>
  )
}

export default function SourcesPanel({
  projectId,
  sources,
  counts,
  unverified,
  focusRef,
  onClose,
}: {
  projectId: number
  sources: ChatSource[]
  counts: Record<string, number>
  unverified: string[]
  /** A citation clicked in the answer, to open and scroll to. */
  focusRef?: string | null
  onClose: () => void
}) {
  return (
    // Overlays the conversation below 1280px and sits beside it above. A panel that
    // only ever took its own column squeezed the answer it exists to explain; one
    // that only ever floated would cover it on a wide screen for no reason.
    <aside className="absolute inset-y-0 right-0 z-30 flex h-full min-h-0 w-[460px] max-w-[92vw] shrink-0 flex-col border-l border-rule bg-panel shadow-[-8px_0_24px_-12px_rgba(0,0,0,0.35)] xl:relative xl:z-auto xl:shadow-none">
      <header className="flex items-center gap-2 border-b border-rule bg-sunk/60 px-3 py-2">
        <span className="block size-2 rotate-45 bg-hot" />
        <h2 className="text-[11.5px] font-bold tracking-tight text-ink">
          What this answer used
        </h2>
        <button
          onClick={onClose}
          aria-label="Close sources"
          className="tag ml-auto px-1 text-ink-dim transition-colors hover:text-hot-ink"
        >
          ✕
        </button>
      </header>

      <div className="flex flex-wrap items-baseline gap-x-2 border-b border-rule px-3 py-1.5">
        <span className="tag text-ink-dim">{sources.length} sources</span>
        {Object.entries(counts).map(([k, v]) => (
          <span key={k} className="tag text-ink-dim">
            {v} {k}
          </span>
        ))}
      </div>

      {!!unverified.length && (
        <p
          className="border-b border-rule bg-warn-wash px-3 py-2 font-sans text-[11px] leading-relaxed text-warn"
          title="Cited by the model but absent from everything retrieved, so they were not verified."
        >
          {unverified.length} reference{unverified.length === 1 ? '' : 's'} the model
          produced could not be checked against anything retrieved, and {unverified.length === 1 ? 'was' : 'were'}{' '}
          stripped from the answer.
        </p>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto">
        {focusRef && <Pinned projectId={projectId} refText={focusRef} />}
        <ul>
        {sources.map((s, i) => (
          <Source
            key={`${s.title}-${i}`}
            source={s}
            projectId={projectId}
            focused={!!focusRef && refKey(s.title) === refKey(focusRef)}
          />
        ))}
        </ul>
      </div>

      <p className="border-t border-rule px-3 py-2 font-sans text-[10.5px] leading-snug text-ink-dim">
        Code and prose open to show the text they were read from. Entities, graph
        traversals and narratives are fully described by their titles.
      </p>
    </aside>
  )
}
