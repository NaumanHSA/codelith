import { useState } from 'react'
import { api, ApiError } from '../../lib/api'
import { useAsync } from '../../lib/hooks'
import { Button, Panel } from '../ui'
import type { Job, JobReview, ReviewPage } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * The review gate.
 *
 * Shown only while a composition is held. Everything above the fold is
 * the reason it stopped: which pages the fact check doubted, and what it
 * said about them. The approved pages are listed underneath, collapsed,
 * because a reviewer who reads only the flagged ones has still seen
 * every page that is actually in question.
 * ------------------------------------------------------------------ */

function Verdict({ page }: { page: ReviewPage }) {
  const claims =
    page.claims_total > 0 ? `${page.claims_passed ?? 0}/${page.claims_total} claims verified` : null

  return (
    <li className="border-b border-rule px-3 py-2.5 last:border-b-0">
      <div className="flex items-start gap-2">
        <span
          className={`tag mt-0.5 shrink-0 ${page.approved ? 'text-ink-dim' : 'text-[var(--warn)]'}`}
        >
          {page.approved ? 'passed' : 'flagged'}
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[12.5px] font-semibold text-ink">{page.title}</div>
          <div className="tag mt-0.5 text-ink-dim">
            {[claims, page.score != null ? `score ${page.score}` : null]
              .filter(Boolean)
              .join(' · ') || page.key}
          </div>
          {page.notes && !page.approved && (
            <p className="mt-1.5 font-sans text-[12px] leading-relaxed text-ink-mid">
              {page.notes}
            </p>
          )}
        </div>
      </div>
    </li>
  )
}

export default function ReviewGate({
  projectId,
  jobId,
  onResolved,
}: {
  projectId: number
  jobId: number
  /** Hand back the updated job so the page can switch out of the hold immediately,
   *  rather than waiting for the next slow poll to notice. */
  onResolved: (job: Job) => void
}) {
  const review = useAsync<JobReview>(s => api.jobReview(projectId, jobId, s), [projectId, jobId])
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showPassed, setShowPassed] = useState(false)

  const decide = async (approved: boolean) => {
    setBusy(approved ? 'approve' : 'reject')
    setError(null)
    try {
      const next = await api.approveJob(projectId, jobId, approved)
      onResolved(next)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not record the decision.')
      setBusy(null)
    }
  }

  const data = review.data
  if (!data) return null

  const flagged = data.pages.filter(p => !p.approved)
  const passed = data.pages.filter(p => p.approved)

  return (
    <Panel title="Waiting for your review" index="!!">
      <div className="border-b border-rule bg-warn-wash px-3 py-2.5">
        <p className="font-sans text-[12.5px] leading-relaxed text-ink">
          <strong>{data.pages_written}</strong>{' '}
          {data.pages_written === 1 ? 'page was written' : 'pages were written'} and{' '}
          <strong>{data.flagged_count}</strong>{' '}
          {data.flagged_count === 1 ? 'did not pass' : 'did not pass'} the fact check.
          Nothing has been published yet.
        </p>
        <p className="tag mt-1 text-ink-dim">
          Approve to publish all of them · Reject to discard the run
        </p>
      </div>

      <ul>
        {flagged.map(p => (
          <Verdict key={p.key} page={p} />
        ))}
      </ul>

      {passed.length > 0 && (
        <div className="border-t border-rule">
          <button
            onClick={() => setShowPassed(v => !v)}
            className="tag w-full px-3 py-2 text-left text-ink-dim transition-colors hover:text-hot-ink"
          >
            {showPassed ? '−' : '+'} {passed.length} page{passed.length === 1 ? '' : 's'} passed
          </button>
          {showPassed && (
            <ul className="border-t border-rule">
              {passed.map(p => (
                <Verdict key={p.key} page={p} />
              ))}
            </ul>
          )}
        </div>
      )}

      {error && (
        <p className="border-t border-rule px-3 py-2 text-[12px] text-[var(--bad)]">{error}</p>
      )}

      <footer className="flex flex-wrap items-center gap-2 border-t border-rule bg-sunk/60 px-3 py-2.5">
        <Button variant="hot" disabled={busy !== null} onClick={() => void decide(true)}>
          {busy === 'approve' ? 'publishing…' : 'Approve and publish →'}
        </Button>
        <Button disabled={busy !== null} onClick={() => void decide(false)}>
          {busy === 'reject' ? 'discarding…' : 'Reject'}
        </Button>
        <span className="tag ml-auto text-ink-dim">
          approving publishes the pages above; it does not rewrite them
        </span>
      </footer>
    </Panel>
  )
}
