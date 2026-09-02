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
 * So the dialog asks first, and the answer decides what it offers: a
 * plain "Analyse" when there is something new to read, and a warning
 * with a deliberate "Analyse anyway" when there is not.
 *
 * The check never refuses. If it cannot reach the remote, that is a
 * caveat shown above the same button — the operator asked for this, and
 * a check that could not answer has no business vetoing them.
 * ------------------------------------------------------------------ */

function Sha({ children }: { children: string }) {
  return (
    <span className="border border-rule bg-sunk px-1 py-px font-mono text-[11px] text-ink">
      {children.slice(0, 8)}
    </span>
  )
}

function Checking() {
  return (
    <div className="flex items-center gap-2.5 px-1 py-6">
      <span className="anim-spin block size-[11px] shrink-0 rounded-full border border-hot border-t-transparent" />
      <span className="font-sans text-[12.5px] text-ink-mid">
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
  onConfirm: () => void
  starting: boolean
}) {
  const [preview, setPreview] = useState<AnalysisPreview | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) {
      setPreview(null)
      setError(null)
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
        <div className="border border-bad/40 bg-bad-wash px-3 py-2.5">
          <span className="tag text-bad">the check failed</span>
          <p className="mt-1 font-sans text-[12px] text-ink">{error}</p>
        </div>
      )}

      {preview && (
        <div className="flex flex-col gap-3">
          <div
            className={`border px-3 py-2.5 ${
              pointless
                ? 'border-warn/40 bg-warn-wash'
                : preview.checked
                  ? 'border-ok/40 bg-ok-wash'
                  : 'border-rule bg-sunk/50'
            }`}
          >
            <span
              className={`tag ${
                pointless ? 'text-warn' : preview.checked ? 'text-ok' : 'text-ink-dim'
              }`}
            >
              {preview.never_analysed
                ? 'first reading'
                : !preview.checked
                  ? 'could not tell'
                  : preview.changed
                    ? 'the code has moved'
                    : 'nothing has changed'}
            </span>
            <p className="mt-1.5 font-sans text-[12.5px] leading-relaxed text-ink">
              {preview.summary}
            </p>
            {preview.reason && (
              <p className="mt-1.5 font-sans text-[11.5px] text-ink-mid">{preview.reason}</p>
            )}
          </div>

          {/* The two commits, when there are two. A SHA is not friendly, but it is the
              thing you can go and check, which a paraphrase is not. */}
          {preview.analysed_commit && (
            <div className="flex flex-wrap items-center gap-2 px-1">
              <span className="tag text-ink-dim">last read</span>
              <Sha>{preview.analysed_commit}</Sha>
              {preview.current_commit && (
                <>
                  <span className="text-ink-dim">→</span>
                  <span className="tag text-ink-dim">now</span>
                  <Sha>{preview.current_commit}</Sha>
                </>
              )}
              {preview.branch && <span className="tag text-ink-dim">on {preview.branch}</span>}
            </div>
          )}

          {pointless && (
            <p className="px-1 font-sans text-[11.5px] leading-relaxed text-ink-mid">
              Running it anyway is not harmful — it refreshes the existing reading and
              re-plans the documentation site. It just costs the same as a real analysis
              and leaves you with one reading rather than two.
            </p>
          )}
        </div>
      )}

      <div className="mt-4 flex items-center gap-2 border-t border-rule pt-3">
        <Button
          variant={pointless ? 'ghost' : 'hot'}
          onClick={onConfirm}
          disabled={loading || starting}
        >
          {starting
            ? 'starting…'
            : pointless
              ? 'Analyse anyway'
              : preview?.never_analysed
                ? 'Analyse →'
                : 'Re-analyse →'}
        </Button>
        <Button variant="ghost" onClick={onClose} disabled={starting}>
          Cancel
        </Button>
      </div>
    </Dialog>
  )
}
