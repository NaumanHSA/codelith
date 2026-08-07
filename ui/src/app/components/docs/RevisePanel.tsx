import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../../lib/api'
import { useJob } from '../../lib/hooks'
import { agentLabel } from '../../lib/format'
import { describeStep, progressStages } from '../../lib/narrate'
import { isTerminal, type Job } from '../../lib/types'
import { Button, Meter } from '../ui'

/* ------------------------------------------------------------------ *
 * Revising one heading, conversationally.
 *
 * Scoped to a single section on purpose. The panel opens against the
 * heading you clicked, and moving to another one starts again — so the
 * model is never handed a conversation about a different part of the
 * page, and the reader never has to wonder which section "make that
 * shorter" refers to.
 *
 * The transcript is not local state. Each turn is a `revision` job
 * carrying its anchor and its instruction, so the history survives a
 * reload and is exactly what the model was given. `history` is fetched
 * when the panel opens and appended to as turns complete.
 * ------------------------------------------------------------------ */

export interface ReviseTarget {
  sectionSlug: string
  slug: string
  /** Null revises the whole page. */
  anchor: string | null
  /** What to call it in the panel header. */
  title: string
}

export default function RevisePanel({
  projectId, target, onClose, onApplied, onBusyChange, onAnchorMoved,
}: {
  projectId: number
  target: ReviseTarget
  onClose: () => void
  /** A turn finished and the page changed — reload it. */
  onApplied: () => void
  /** Whether a run is in flight, so the heading itself can say so. */
  onBusyChange?: (busy: boolean) => void
  /** The revision renamed its heading — follow it, or the next turn addresses nothing. */
  onAnchorMoved?: (anchor: string, title: string) => void
}) {
  const [turns, setTurns] = useState<Job[]>([])
  const [draft, setDraft] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [activeId, setActiveId] = useState<number | null>(null)
  const { job } = useJob(activeId)
  const box = useRef<HTMLDivElement>(null)

  const key = `${target.sectionSlug}/${target.slug}#${target.anchor ?? ''}`

  // Moving to another heading is a different conversation. Everything resets, and
  // the transcript for the new one is loaded from its jobs.
  useEffect(() => {
    let alive = true
    setTurns([])
    setDraft('')
    setError(null)
    setActiveId(null)
    api
      .pageRevisions(projectId, target.sectionSlug, target.slug, target.anchor)
      .then(rows => alive && setTurns(rows))
      .catch(() => alive && setTurns([]))
    return () => {
      alive = false
    }
  }, [projectId, key, target.sectionSlug, target.slug, target.anchor])

  // A turn finished: fold it into the transcript and reload the page underneath, so
  // the reader sees the new prose without doing anything.
  const applied = useRef<number | null>(null)
  useEffect(() => {
    if (!job || !isTerminal(job.status)) return
    if (applied.current === job.id) return
    applied.current = job.id
    setActiveId(null)
    setTurns(t => [...t.filter(x => x.id !== job.id), job])
    if (job.status === 'completed') {
      // A revision is allowed to rename a heading its own edit made inaccurate. The
      // anchor is the address, so the panel has to move with it — otherwise the next
      // turn in this very conversation addresses a heading that no longer exists.
      const out = (job.steps ?? []).find(s => s.name === 'reviser_agent')?.output_json
      const moved = typeof out?.new_anchor === 'string' ? out.new_anchor : null
      // `new_title`, not `section` — the latter is what the heading was called
      // before this turn, so labelling the panel from it shows the old name.
      const renamed = typeof out?.new_title === 'string' ? out.new_title : null
      if (moved && moved !== target.anchor) onAnchorMoved?.(moved, renamed ?? target.title)
      onApplied()
    }
    // `onApplied` is a fresh closure each render; depending on it would re-run this.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job])

  useEffect(() => {
    box.current?.scrollTo({ top: box.current.scrollHeight, behavior: 'smooth' })
  }, [turns.length, job?.status])

  const send = async () => {
    const instructions = draft.trim()
    if (!instructions || activeId) return
    setError(null)
    try {
      const started = await api.revisePage(projectId, target.sectionSlug, target.slug, {
        instructions,
        anchor: target.anchor,
      })
      setDraft('')
      setActiveId(started.id)
      setTurns(t => [...t, started])
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not start the revision.')
    }
  }

  const live = Boolean(job && !isTerminal(job.status)) || (activeId != null && !job)

  // The heading in the document shows the same state as this panel. Held in a ref so
  // the effect does not re-run every render on a fresh closure.
  const reportBusy = useRef(onBusyChange)
  reportBusy.current = onBusyChange
  useEffect(() => {
    reportBusy.current?.(live)
  }, [live])
  const steps = job?.steps ?? []
  const denominator = job ? progressStages(job.job_type).length : 0
  const done = steps.filter(s => s.status === 'completed').length
  const active = [...steps].reverse().find(s => s.status === 'running') ?? steps[steps.length - 1]

  return (
    <aside className="flex h-full w-full flex-col border-l border-rule bg-panel">
      <header className="flex items-start gap-2 border-b border-rule px-3 py-2.5">
        <div className="min-w-0 flex-1">
          <span className="tag block text-ink-dim">
            {target.anchor ? 'revising this section' : 'revising the whole page'}
          </span>
          <span className="mt-0.5 block truncate text-[12.5px] font-semibold text-ink">
            {target.title}
          </span>
        </div>
        <button
          onClick={onClose}
          aria-label="Close"
          className="tag shrink-0 px-1 text-ink-dim transition-colors hover:text-ink"
        >
          ✕
        </button>
      </header>

      <div ref={box} className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
        {turns.length === 0 && !live && (
          <p className="text-[11.5px] leading-relaxed text-ink-dim">
            Say what should change. The section is rewritten in place against the same
            evidence it was written from — everything else on the page is left alone.
          </p>
        )}

        <ul className="space-y-2.5">
          {turns.map(t => (
            <li key={t.id} className="space-y-1.5">
              {/* what was asked */}
              <div className="border border-rule bg-sunk/60 px-2.5 py-1.5">
                <span className="tag block text-ink-dim">you asked</span>
                <p className="mt-0.5 text-[11.5px] leading-relaxed text-ink">
                  {String((t.config_json ?? {}).instructions ?? '')}
                </p>
              </div>

              {/* what happened */}
              {t.id !== activeId && (
                <div className="flex items-center gap-2 pl-2">
                  {t.status === 'completed' ? (
                    <>
                      <span className="block size-[5px] shrink-0 rotate-45 bg-ok" />
                      <span className="text-[11px] text-ink-mid">
                        Rewritten and applied to the page.
                      </span>
                    </>
                  ) : (
                    <>
                      <span className="block size-[5px] shrink-0 rotate-45 bg-bad" />
                      <span className="min-w-0 text-[11px] text-bad">
                        {t.error_message || `The run ${t.status}. The page is unchanged.`}
                      </span>
                    </>
                  )}
                  <Link
                    to={`/app/projects/${projectId}/jobs/${t.id}`}
                    className="tag ml-auto shrink-0 text-hot-ink hover:underline"
                  >
                    run #{t.id} →
                  </Link>
                </div>
              )}
            </li>
          ))}
        </ul>

        {live && (
          <div className="mt-2.5 border border-hot/40 bg-hot-wash/50 px-2.5 py-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="tag flex items-center gap-1.5 text-hot-ink">
                <span className="anim-blink block size-[6px] rounded-full bg-hot" />
                rewriting
              </span>
              <Meter pct={denominator ? Math.round((done / denominator) * 100) : 0} segments={10} />
              {/* There is a moment between the API accepting the run and the first
                  poll returning it, where the panel is live but has no job to link. */}
              {job && (
                <Link
                  to={`/app/projects/${projectId}/jobs/${job.id}`}
                  className="tag ml-auto text-hot-ink hover:underline"
                >
                  run #{job.id} →
                </Link>
              )}
            </div>
            <p className="mt-1 text-[11px] text-ink-mid">
              {active ? `${agentLabel(active.name)} — ${describeStep(active) ?? 'working'}` : 'Starting…'}
            </p>
          </div>
        )}

        {error && <p className="mt-2.5 text-[11.5px] text-bad">{error}</p>}
      </div>

      <div className="border-t border-rule p-2.5">
        <textarea
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onKeyDown={e => {
            // Enter sends; Shift+Enter is a newline. Instructions are usually one
            // line, and reaching for a button every turn makes a conversation feel
            // like a form.
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              void send()
            }
          }}
          rows={3}
          disabled={Boolean(live)}
          placeholder={
            turns.length
              ? 'Anything else? e.g. “now make the second paragraph shorter”'
              : 'e.g. “lead with a numbered list of the steps, and keep the file references”'
          }
          className="w-full resize-none border border-rule bg-sunk/60 px-2.5 py-2 font-sans text-[11.5px] leading-relaxed text-ink transition-colors placeholder:text-ink-dim focus:border-hot focus:bg-panel focus:outline-none disabled:opacity-60"
        />
        <div className="mt-1.5 flex items-center gap-2">
          <span className="tag text-ink-dim">enter to send</span>
          <Button
            variant="hot"
            className="ml-auto"
            onClick={() => void send()}
            disabled={!draft.trim() || Boolean(live)}
          >
            {live ? 'rewriting…' : 'Rewrite'}
          </Button>
        </div>
      </div>
    </aside>
  )
}
