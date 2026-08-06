import { useState } from 'react'
import { formatDateTime, shortSha } from '../../lib/format'
import type { SitePageDetail } from '../../lib/types'
import { Chip, Meter } from '../ui'

/* ------------------------------------------------------------------ *
 * Where this page came from.
 *
 * "Written from these 12 files at 4065c2f" is the claim that makes
 * generated documentation trustworthy — a reader can go and check. We
 * already collect every part of it and used to throw it away.
 *
 * Collapsed by default: it is an audit trail, not the page.
 * ------------------------------------------------------------------ */

export default function PageProvenance({ page }: { page: SitePageDetail }) {
  const [open, setOpen] = useState(false)
  const files = page.source_files ?? []
  const qa = page.qa
  const claims = qa?.claims_checked ?? 0

  if (!page.commit_sha && !files.length && !qa) return null

  return (
    <section className="mt-6 border border-rule bg-panel">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex w-full flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-2 text-left transition-colors hover:bg-sunk/60"
      >
        <span className="tag text-ink-dim">Provenance</span>
        <span className="text-[11px] text-ink-mid">
          written from {files.length} file{files.length === 1 ? '' : 's'} at{' '}
          <span className="text-ink">{shortSha(page.commit_sha)}</span>
          {page.updated_at ? ` · ${formatDateTime(page.updated_at)}` : ''}
        </span>
        {page.qa_score != null && (
          <span className="ml-auto flex items-center gap-2">
            <Meter pct={page.qa_score * 10} segments={10} />
            <span className="tag text-ink-dim">QA {page.qa_score}/10</span>
          </span>
        )}
        <span className="tag shrink-0 text-ink-dim">{open ? '−' : '+'}</span>
      </button>

      {open && (
        <div className="border-t border-rule px-3 py-3">
          {files.length > 0 && (
            <>
              <span className="tag block text-ink-dim">Source</span>
              <ul className="mt-1.5 mb-3 space-y-0.5">
                {files.map(f => (
                  <li key={f} className="font-mono text-[11px] text-ink-mid">
                    {f}
                  </li>
                ))}
              </ul>
            </>
          )}

          {qa && (
            <>
              <span className="tag block text-ink-dim">Fact check</span>
              <div className="mt-1.5 flex flex-wrap items-center gap-2">
                <Chip tone={qa.approved ? 'plain' : 'warn'}>
                  {qa.approved ? 'approved' : 'flagged'}
                </Chip>
                {claims > 0 && (
                  <span className="tag text-ink-dim">
                    {qa.claims_passed ?? 0}/{claims} claims verified against source
                  </span>
                )}
              </div>
              {!!qa.issues?.length && (
                <ul className="mt-2 space-y-1">
                  {qa.issues.slice(0, 5).map(issue => (
                    <li key={issue} className="text-[11px] leading-snug text-ink-mid">
                      · {issue}
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}

          {page.job_id && (
            <p className="mt-3 text-[10.5px] text-ink-dim">
              Written by job #{page.job_id}
              {page.kb_id ? ` from knowledge base #${page.kb_id}` : ''}.
            </p>
          )}
        </div>
      )}
    </section>
  )
}
