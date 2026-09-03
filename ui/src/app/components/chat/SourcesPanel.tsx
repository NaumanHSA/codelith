import { useEffect, useState } from 'react'
import { api, ApiError } from '../../lib/api'
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
  return (
    <div className="border-t border-rule">
      {body.partial && (
        <p className="border-b border-rule bg-warn-wash px-2.5 py-1 font-sans text-[10.5px] text-warn">
          Those exact lines are no longer stored — this file has been re-analysed since.
          Showing what is there now.
        </p>
      )}
      <pre className="max-h-[320px] overflow-auto px-2.5 py-2 text-[10.5px] leading-relaxed whitespace-pre-wrap text-ink">
        {body.content}
      </pre>
    </div>
  )
}

function Source({
  source,
  projectId,
}: {
  source: ChatSource
  projectId: number
}) {
  const [open, setOpen] = useState(false)
  const can = openable(source.kind)

  return (
    <li className="border-b border-rule last:border-b-0">
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
        {can && (
          <span className="tag mt-px shrink-0 text-ink-dim">{open ? '−' : '+'}</span>
        )}
      </button>
      {open && can && <Body projectId={projectId} refText={source.title} />}
    </li>
  )
}

export default function SourcesPanel({
  projectId,
  sources,
  counts,
  unverified,
  onClose,
}: {
  projectId: number
  sources: ChatSource[]
  counts: Record<string, number>
  unverified: string[]
  onClose: () => void
}) {
  return (
    <aside className="flex h-full min-h-0 w-[380px] shrink-0 flex-col border-l border-rule bg-panel">
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

      <ul className="min-h-0 flex-1 overflow-y-auto">
        {sources.map((s, i) => (
          <Source key={`${s.title}-${i}`} source={s} projectId={projectId} />
        ))}
      </ul>

      <p className="border-t border-rule px-3 py-2 font-sans text-[10.5px] leading-snug text-ink-dim">
        Code and prose open to show the text they were read from. Entities, graph
        traversals and narratives are fully described by their titles.
      </p>
    </aside>
  )
}
