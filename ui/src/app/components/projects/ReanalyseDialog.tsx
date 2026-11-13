import { useEffect, useState } from 'react'
import { api, ApiError } from '../../lib/api'
import { Button, Dialog } from '../ui'
import type { AnalysisPreview } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * What re-analysing would achieve, asked before it is started.
 *
 * Analysis is the expensive thing here — clone, parse, embed, summarise
 * — and the button that started it said nothing about whether it would
 * produce anything new. Re-analysing an unmoved repository costs exactly
 * as much as re-analysing a moved one and stores the same knowledge base,
 * because a knowledge base is keyed by commit and the same commit upserts.
 * It does not even give drift a second point to compare.
 *
 * So the dialog asks first, and the answer decides what it offers. When
 * the code has moved, reading it again reads only the files that changed
 * and keeps the rest of the last reading (`knowledge/incremental.py`), so
 * that is the default; reading everything from scratch is a box to tick,
 * for after a model change. When nothing moved there is nothing new to
 * read, so the only thing on offer is a deliberate rebuild from scratch.
 *
 * The check never refuses. If it cannot reach the remote, that is a
 * caveat shown above the same button — the operator asked for this, and
 * a check that could not answer has no business vetoing them.
 * ------------------------------------------------------------------ */

function Sha({ children }: { children: string }) {
  return (
    <span className="rounded-lg border border-rule bg-sunk px-1 py-px font-mono text-[12px] text-ink">
      {children.slice(0, 8)}
    </span>
  )
}

function Checking() {
  return (
    <div className="flex items-center gap-2.5 px-1 py-6">
      <span className="anim-spin block size-[11px] shrink-0 rounded-full border border-hot border-t-transparent" />
      <span className="text-[12.5px] text-ink-mid">
        Asking the repository where it is now…
      </span>
    </div>
  )
}

export default function ReanalyseDialog({
  open,
  projectId,
  onClose,
  onConfirm,
  starting,
}: {
  open: boolean
  projectId: number
  onClose: () => void
  /** `force`: read everything from scratch instead of keeping what did not change. */
  onConfirm: (force: boolean) => void
  starting: boolean
}) {
  const [preview, setPreview] = useState<AnalysisPreview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [scratch, setScratch] = useState(false)

  useEffect(() => {
    if (!open) {
      setPreview(null)
      setError(null)
      setScratch(false)
      return
    }
    let live = true
    api
      .analysisPreview(projectId)
      .then(p => live && setPreview(p))
      .catch(e =>
        live && setError(e instanceof ApiError ? e.message : 'Could not check the repository.'),
      )
    return () => {
      live = false
    }
  }, [open, projectId])

  const loading = !preview && !error
  // Unmoved is the only case worth arguing with. Everything else — moved, never read,
  // or unknown — goes ahead on one click.
  const pointless = !!preview && preview.checked && !preview.changed && !preview.never_analysed

  return (
    <Dialog open={open} onClose={onClose} title="Analyse this codebase" width={560}>
      {loading && <Checking />}

      {error && (
        <div className="rounded-lg border border-bad/40 bg-bad-wash px-3 py-2.5">
          <span className="text-[12.5px] font-medium text-bad">The check failed</span>
          <p className="mt-1 text-[13px] text-ink">{error}</p>
        </div>
      )}

      {preview && (
        <div className="flex flex-col gap-3">
          <div
            className={`rounded-lg border px-3 py-2.5 ${
              pointless
                ? 'border-warn/40 bg-warn-wash'
                : preview.checked
                  ? 'border-ok/40 bg-ok-wash'
                  : 'border-rule bg-sunk/50'
            }`}
          >
            <span
              className={`text-[12.5px] font-medium ${
                pointless ? 'text-warn' : preview.checked ? 'text-ok' : 'text-ink-dim'
              }`}
            >
              {preview.never_analysed
                ? 'First reading'
                : !preview.checked
                  ? 'Could not tell'
                  : preview.changed
                    ? 'The code has moved'
                    : 'Nothing has changed'}
            </span>
            <p className="mt-1.5 text-[12.5px] leading-relaxed text-ink">
              {preview.summary}
            </p>
            {preview.reason && (
              <p className="mt-1.5 text-[12.5px] text-ink-mid">{preview.reason}</p>
            )}
          </div>

          {/* The two commits, when there are two. A SHA is not friendly, but it is the
              thing you can go and check, which a paraphrase is not. */}
          {preview.analysed_commit && (
            <div className="flex flex-wrap items-center gap-2 px-1">
              <span className="text-[12px] text-ink-dim">Last read</span>
              <Sha>{preview.analysed_commit}</Sha>
              {preview.current_commit && (
                <>
                  <span className="text-ink-dim">→</span>
                  <span className="text-[12px] text-ink-dim">now</span>
                  <Sha>{preview.current_commit}</Sha>
                </>
              )}
              {preview.branch && <span className="text-[12px] text-ink-dim">on {preview.branch}</span>}
            </div>
          )}

          {pointless ? (
            <p className="px-1 text-[12.5px] leading-relaxed text-ink-mid">
              Reading it again from scratch rebuilds this reading with every model call
              made again: worth it after changing the models in Settings, otherwise it
              costs a full analysis and produces the same knowledge.
            </p>
          ) : (
            !preview.never_analysed && (
              <label className="flex cursor-pointer items-start gap-2.5 px-1 text-[12.5px] leading-relaxed text-ink-mid">
                <input
                  type="checkbox"
                  checked={scratch}
                  onChange={e => setScratch(e.target.checked)}
                  className="mt-[3px] accent-[var(--hot)]"
                />
                <span>
                  <span className="text-ink">Read everything from scratch.</span> Normally only the
                  files that changed are read again and the rest of the last reading is kept,
                  which usually takes a fraction of the time. Tick this after changing models.
                </span>
              </label>
            )
          )}
        </div>
      )}

      <div className="mt-4 flex items-center gap-2 border-t border-rule pt-3">
        {/* Deliberately not `ghost`. Running an analysis that will read nothing new
            is a real choice somebody may want to make — usually to re-plan the site —
            and a button with no background reads as disabled. `solid` is visible
            without being the recommended action, which `hot` would imply. */}
        <Button
          variant={pointless ? 'solid' : 'hot'}
          onClick={() => onConfirm(pointless || scratch)}
          disabled={loading || starting}
        >
          {starting
            ? 'Starting…'
            : pointless
              ? 'Read again from scratch'
              : preview?.never_analysed
                ? 'Analyse →'
                : scratch
                  ? 'Read everything again →'
                  : 'Read the changes →'}
        </Button>
        <Button variant="ghost" onClick={onClose} disabled={starting}>
          Cancel
        </Button>
      </div>
    </Dialog>
  )
}
