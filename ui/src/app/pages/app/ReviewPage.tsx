import { useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../../lib/api'
import { relativeTime, shortSha } from '../../lib/format'
import { useAsync } from '../../lib/hooks'
import { Icon, type IconName } from '../../lib/icons'
import type { ReviewDetail, ReviewFinding, ReviewReport, ReviewSeverity, ReviewSummary, ReviewVerdict } from '../../lib/types'
import { Diagram, type FEdge, type FNode } from '../../components/atlas/FlowPanel'
import { TIERS } from '../../components/atlas/model'
import { Pill } from '../../components/primitives'
import { EmptyState, ErrorState, SkeletonPanel } from '../../components/States'
import { useReducedMotion } from '../../lib/motion'
import { NEW_TAB } from '../../components/layout/tabState'

/* ------------------------------------------------------------------ *
 * Review: a change, checked against what Codelith knows about the code
 * before it is merged (`knowledge/review.py`). What it touches, what
 * could break, which tests and pages it concerns, what it adds or takes
 * away, and whether it fits how the code is put together.
 *
 * Reviews come from wherever the change is: this page for a codebase read
 * from a folder on this machine, `codelith review` in a checkout, or an
 * agent calling `review_changes` before it says it is done. All of them
 * are kept and listed here.
 * ------------------------------------------------------------------ */

const VERDICT: Record<ReviewVerdict, { icon: IconName; title: string; tone: string; text: string }> = {
  stop: { icon: 'octagon-x', title: 'Stop and look before merging', tone: 'border-bad/40 bg-bad-wash', text: 'text-bad' },
  check: { icon: 'triangle-alert', title: 'Worth checking', tone: 'border-warn/40 bg-warn-wash', text: 'text-warn' },
  clear: { icon: 'shield-check', title: 'Clear', tone: 'border-ok/40 bg-ok-wash', text: 'text-ok' },
}

const SEVERITY: Record<ReviewSeverity, { icon: IconName; title: string; text: string }> = {
  stop: { icon: 'octagon-x', title: 'Stop and look', text: 'text-bad' },
  warn: { icon: 'triangle-alert', title: 'Check', text: 'text-warn' },
  note: { icon: 'info', title: 'Notes', text: 'text-ink-dim' },
}

const SOURCE: Record<ReviewSummary['source'], { icon: IconName; label: string }> = {
  studio: { icon: 'app-window', label: 'Studio' },
  cli: { icon: 'square-terminal', label: 'Terminal' },
  mcp: { icon: 'bot', label: 'Agent' },
}

const STATUS: Record<string, { mark: string; tone: string }> = {
  added: { mark: 'A', tone: 'text-ok' },
  modified: { mark: 'M', tone: 'text-warn' },
  deleted: { mark: 'D', tone: 'text-bad' },
  renamed: { mark: 'R', tone: 'text-hot-ink' },
}

const RISK_TONE: Record<string, 'good' | 'warn' | 'bad' | 'plain'> = { low: 'good', moderate: 'warn', high: 'bad' }

function sourceLabel(r: ReviewSummary) {
  return r.source === 'mcp' && r.client && r.client !== 'unknown' ? r.client : SOURCE[r.source].label
}

export default function ReviewPage() {
  const { projectId } = useParams()
  const id = Number(projectId)
  const [params, setParams] = useSearchParams()
  const list = useAsync(sig => api.reviews(id, sig), [id])
  const wanted = Number(params.get('review')) || null
  const selectedId = wanted ?? list.data?.reviews[0]?.id ?? null
  const detail = useAsync(
    sig => (selectedId ? api.review(id, selectedId, sig) : Promise.resolve(null)),
    [id, selectedId],
  )

  const [against, setAgainst] = useState('')
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = async () => {
    setRunning(true)
    setError(null)
    try {
      const made = await api.reviewWorkingCopy(id, against.trim() || undefined)
      list.reload()
      setParams({ review: String(made.id) }, { replace: true })
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'The review could not be run.')
    } finally {
      setRunning(false)
    }
  }

  if (!Number.isFinite(id)) return <ErrorState message="Not a codebase." />

  return (
    <div className="flex w-full flex-col gap-6 px-6 py-6">
      <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <h1 className="text-[22px] leading-tight font-semibold text-ink">Review</h1>
          <p className="mt-1 max-w-[78ch] text-[13.5px] leading-relaxed text-ink-mid">
            Check a change against what Codelith knows about this codebase before it is merged: what it touches,
            what could break, which tests and written pages it concerns, and whether it fits how the code is put
            together.
          </p>
        </div>
        {list.data?.can_review_working_copy && (
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex h-[34px] items-center gap-2 rounded-lg border border-rule bg-panel px-2.5 focus-within:border-hot">
              <Icon name="git-commit-horizontal" size={14} className="text-ink-dim" />
              <input
                value={against}
                onChange={e => setAgainst(e.target.value)}
                placeholder={`against ${shortSha(list.data.commit)} (the knowledge)`}
                aria-label="Compare against a commit or branch"
                className="w-[220px] bg-transparent font-mono text-[12.5px] text-ink outline-none placeholder:font-sans placeholder:text-ink-dim"
              />
            </label>
            <button
              type="button"
              onClick={() => void run()}
              disabled={running}
              className="inline-flex h-[34px] items-center gap-2 rounded-lg bg-hot px-3.5 text-[13px] font-medium text-on-hot transition-colors hover:bg-hot-ink disabled:opacity-60"
            >
              <Icon name={running ? 'loader' : 'list-checks'} size={15} className={running ? 'anim-spin' : ''} />
              {running ? 'Reviewing…' : 'Review the working copy'}
            </button>
          </div>
        )}
      </header>

      {error && <ErrorState message={error} compact />}
      {list.data && !list.data.can_review_working_copy && <WhereReviewsComeFrom />}

      {list.loading && !list.data ? (
        <SkeletonPanel rows={6} />
      ) : list.error ? (
        <ErrorState message={list.error} onRetry={list.reload} />
      ) : !list.data?.reviews.length ? (
        <EmptyState
          title="No reviews yet"
          body={
            list.data?.can_review_working_copy
              ? 'Review the working copy to check what has changed since the knowledge was read.'
              : 'Run codelith review in a checkout of this codebase, or let your agent call review_changes. Each review lands here.'
          }
        />
      ) : (
        <div className="grid min-w-0 grid-cols-1 gap-5 lg:grid-cols-[300px_minmax(0,1fr)]">
          <ReviewList
            reviews={list.data.reviews}
            selected={selectedId}
            onPick={r => setParams({ review: String(r) }, { replace: true })}
          />
          <section className="min-w-0">
            {detail.loading && !detail.data ? (
              <SkeletonPanel rows={8} />
            ) : detail.error ? (
              <ErrorState message={detail.error} onRetry={detail.reload} />
            ) : detail.data ? (
              <ReviewView projectId={id} review={detail.data} />
            ) : null}
          </section>
        </div>
      )}
    </div>
  )
}

/** For a codebase the server has no working copy of: where reviews come from instead. */
function WhereReviewsComeFrom() {
  const ways: { icon: IconName; title: string; line: string; code: string }[] = [
    {
      icon: 'square-terminal',
      title: 'In a checkout',
      line: 'Reviews uncommitted changes against the commit the knowledge was read at. Exits with 1 when something needs stopping for, so it can run before a push.',
      code: 'codelith review',
    },
    {
      icon: 'bot',
      title: 'From your agent',
      line: 'Over MCP, an agent calls this after editing and before it says it is done.',
      code: 'review_changes',
    },
  ]
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
      {ways.map(w => (
        <div key={w.title} className="flex items-start gap-3 rounded-xl border border-rule bg-panel px-4 py-3.5">
          <Icon name={w.icon} size={18} className="mt-0.5 text-hot" />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[13.5px] font-semibold text-ink">{w.title}</span>
              <code className="rounded-md border border-rule bg-sunk px-1.5 py-px font-mono text-[12px] text-ink">{w.code}</code>
            </div>
            <p className="mt-1 text-[12.5px] leading-relaxed text-ink-dim">{w.line}</p>
          </div>
        </div>
      ))}
    </div>
  )
}

function ReviewList({
  reviews,
  selected,
  onPick,
}: {
  reviews: ReviewSummary[]
  selected: number | null
  onPick: (id: number) => void
}) {
  return (
    <nav aria-label="Reviews" className="flex max-h-[calc(100vh-260px)] flex-col overflow-y-auto rounded-xl border border-rule bg-panel p-1.5">
      {reviews.map(r => {
        const v = VERDICT[r.verdict]
        const on = r.id === selected
        return (
          <button
            key={r.id}
            type="button"
            onClick={() => onPick(r.id)}
            aria-current={on ? 'true' : undefined}
            className={`flex w-full items-start gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors ${
              on ? 'bg-sunk shadow-[inset_0_0_0_1px_var(--line-2)]' : 'hover:bg-hover'
            }`}
          >
            <Icon name={v.icon} size={16} className={`mt-0.5 ${v.text}`} />
            <span className="min-w-0 flex-1">
              <span className="block text-[13px] font-medium text-ink">
                {r.file_count} file{r.file_count === 1 ? '' : 's'} · {r.risk} risk
              </span>
              <span className="mt-0.5 flex items-center gap-1.5 text-[12px] text-ink-dim">
                <Icon name={SOURCE[r.source].icon} size={12} />
                {sourceLabel(r)} · {relativeTime(r.created_at)}
              </span>
            </span>
            <span className="shrink-0 font-mono text-[11px] text-ink-dim">#{r.id}</span>
          </button>
        )
      })}
    </nav>
  )
}

function ReviewView({ projectId, review }: { projectId: number; review: ReviewDetail }) {
  const report = review.report
  const v = VERDICT[review.verdict]
  const [copied, setCopied] = useState(false)
  const fileHref = (path: string) => `/app/projects/${projectId}/graph?file=${encodeURIComponent(path)}`

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(report.brief ?? report.summary)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* the text is selectable below */
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <div className={`flex items-start gap-3 rounded-xl border px-4 py-3.5 ${v.tone}`}>
        <Icon name={v.icon} size={22} className={`mt-0.5 shrink-0 ${v.text}`} />
        <div className="min-w-0 flex-1">
          <div className={`text-[15px] font-semibold ${v.text}`}>{v.title}</div>
          <p className="mt-1 text-[13px] leading-relaxed text-ink">{review.summary}</p>
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-ink-dim">
            <span className="flex items-center gap-1.5">
              <Icon name={SOURCE[review.source].icon} size={13} />
              {sourceLabel(review)}
            </span>
            <span className="font-mono">
              {review.base.length >= 32 ? shortSha(review.base) : review.base} → {review.head ?? 'working copy'}
            </span>
            <span>{relativeTime(review.created_at)}</span>
          </div>
        </div>
      </div>

      <Findings findings={report.findings} fileHref={fileHref} />
      <ShapeChange report={report} />

      <section className="flex flex-col gap-2">
        <h2 className="text-[14px] font-semibold text-ink">What it touches</h2>
        <div className="overflow-x-auto rounded-xl border border-rule bg-panel">
          <table className="tbl">
            <thead>
              <tr>
                <th className="w-8" />
                <th>File</th>
                <th>Part</th>
                <th>Changes</th>
                <th className="text-right">Reach</th>
                <th className="text-right">Tests</th>
                <th>Risk</th>
              </tr>
            </thead>
            <tbody>
              {report.files.map(f => {
                const s = STATUS[f.status] ?? STATUS.modified
                return (
                  <tr key={f.path}>
                    <td className={`font-mono text-[12px] font-semibold ${s.tone}`} title={f.status}>
                      {s.mark}
                    </td>
                    <td className="max-w-[340px]">
                      <Link to={fileHref(f.old_path ?? f.path)} className="block truncate font-mono text-[12.5px] text-ink hover:text-hot-ink" title={f.path}>
                        {f.path}
                      </Link>
                      {f.old_path && <span className="block truncate font-mono text-[11.5px] text-ink-dim">from {f.old_path}</span>}
                    </td>
                    <td className="text-[12.5px] text-ink-mid">{f.part ?? '—'}</td>
                    <td className="max-w-[260px] truncate font-mono text-[12px] text-ink-mid" title={f.symbols.join(', ')}>
                      {f.symbols.join(', ') || '—'}
                    </td>
                    <td className="text-right font-mono text-[12.5px] text-ink-mid">{f.reach || '—'}</td>
                    <td className="text-right font-mono text-[12.5px] text-ink-mid">{f.tests.length || '—'}</td>
                    <td>{f.risk !== 'unknown' ? <Pill tone={RISK_TONE[f.risk] ?? 'plain'}>{f.risk}</Pill> : <span className="text-[12px] text-ink-dim">new</span>}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        {report.skipped > 0 && (
          <p className="text-[12.5px] text-ink-dim">{report.skipped} more file(s) were left out: the change is larger than a review reads.</p>
        )}
      </section>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <ListBox title="Tests to run" icon="flask-conical" empty="No test reaches what this changes.">
          {report.tests.map(t => (
            <li key={t} className="truncate font-mono text-[12.5px] text-ink-mid" title={t}>
              {t}
            </li>
          ))}
        </ListBox>
        <ListBox title="Written pages to check" icon="book-open-text" empty="No written page describes what this changes.">
          {report.pages.map(p => (
            <li key={p.address}>
              <Link to={`/app/projects/${projectId}/docs/${p.address}`} state={NEW_TAB} className="text-[13px] text-ink-mid hover:text-hot-ink">
                {p.title}
              </Link>
            </li>
          ))}
        </ListBox>
        {(report.facts_added.length > 0 || report.facts_removed.length > 0) && (
          <ListBox title="What it adds and takes away" icon="git-compare-arrows" empty="">
            {report.facts_added.map(f => (
              <li key={`+${f}`} className="flex items-baseline gap-2 text-[12.5px] text-ink-mid">
                <span className="font-mono text-ok">+</span>
                {f}
              </li>
            ))}
            {report.facts_removed.map(f => (
              <li key={`-${f}`} className="flex items-baseline gap-2 text-[12.5px] text-ink-mid">
                <span className="font-mono text-bad">−</span>
                {f}
              </li>
            ))}
          </ListBox>
        )}
      </div>

      <details className="group rounded-xl border border-rule bg-panel">
        <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-[13px] font-medium text-ink-mid hover:text-ink">
          <Icon name="chevron-right" size={14} className="transition-transform group-open:rotate-90" />
          As text, for a pull request or a chat
          <button
            type="button"
            onClick={e => {
              e.preventDefault()
              void copy()
            }}
            className="ml-auto inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[12px] text-ink-dim transition-colors hover:bg-hover hover:text-ink"
          >
            <Icon name={copied ? 'check' : 'copy'} size={13} />
            {copied ? 'Copied' : 'Copy'}
          </button>
        </summary>
        <pre className="overflow-x-auto border-t border-rule px-4 py-3 font-mono text-[12px] leading-relaxed whitespace-pre-wrap text-ink-mid">
          {report.brief ?? report.summary}
        </pre>
      </details>
    </div>
  )
}

function Findings({ findings, fileHref }: { findings: ReviewFinding[]; fileHref: (p: string) => string }) {
  if (!findings.length)
    return (
      <p className="flex items-center gap-2 text-[13px] text-ink-mid">
        <Icon name="shield-check" size={15} className="text-ok" /> Nothing to flag.
      </p>
    )
  return (
    <section className="flex flex-col gap-4">
      {(['stop', 'warn', 'note'] as ReviewSeverity[]).map(sev => {
        const rows = findings.filter(f => f.severity === sev)
        if (!rows.length) return null
        const s = SEVERITY[sev]
        return (
          <div key={sev} className="flex flex-col gap-1.5">
            <h2 className={`flex items-center gap-2 text-[14px] font-semibold ${s.text}`}>
              <Icon name={s.icon} size={15} />
              {s.title}
              <span className="font-mono text-[12px] font-normal text-ink-dim">{rows.length}</span>
            </h2>
            <ul className="flex flex-col divide-y divide-rule rounded-xl border border-rule bg-panel">
              {rows.map((f, k) => (
                <li key={k} className="flex flex-col gap-1 px-4 py-2.5 sm:flex-row sm:items-baseline sm:gap-4">
                  {f.path ? (
                    <Link
                      to={fileHref(f.path)}
                      className="shrink-0 font-mono text-[12.5px] text-ink hover:text-hot-ink sm:w-[260px] sm:truncate"
                      title={f.path}
                    >
                      {f.path}
                      {f.line ? <span className="text-ink-dim">:{f.line}</span> : null}
                    </Link>
                  ) : (
                    <span className="hidden shrink-0 sm:block sm:w-[260px]" />
                  )}
                  <span className="min-w-0 text-[13px] leading-relaxed text-ink-mid">{f.message}</span>
                </li>
              ))}
            </ul>
          </div>
        )
      })}
    </section>
  )
}

/** The links between parts this change creates, in the knowledge graph's columns. */
function ShapeChange({ report }: { report: ReviewReport }) {
  const reduced = useReducedMotion()
  const { columns, edges } = useMemo(() => {
    const cols: FNode[][] = TIERS.map(() => [])
    for (const p of report.parts) {
      if (p.tier < 0 || p.tier >= cols.length) continue
      cols[p.tier].push({
        key: `p${p.index}`,
        title: p.name,
        sub: p.touched ? 'changed here' : 'linked to',
        icon: 'boxes',
        color: p.touched ? 'var(--hot)' : 'var(--ink-dim)',
        current: p.touched,
      })
    }
    const label: Record<string, string> = {
      new: 'new link',
      backwards: 'against the columns',
      loop: 'makes a loop',
      existing: 'adds to a link',
    }
    const out: FEdge[] = report.links.map(l => ({
      from: `p${l.source}`,
      to: `p${l.target}`,
      label: label[l.kind],
      hoverLabel: `${l.file} → ${l.imports}`,
      strong: l.kind === 'new',
      bad: l.kind === 'loop' || l.kind === 'backwards',
    }))
    return { columns: cols, edges: out }
  }, [report])

  if (!report.links.length) return null
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-[14px] font-semibold text-ink">How it changes the shape</h2>
      <p className="text-[12.5px] text-ink-dim">
        The parts it changes and the parts they now depend on, in the knowledge graph's columns. Red runs against
        the way the code is put together.
      </p>
      <div className="rounded-xl border border-rule bg-panel py-1">
        <Diagram columns={columns} edges={edges} heads={[...TIERS]} reduced={reduced} />
      </div>
    </section>
  )
}

function ListBox({ title, icon, empty, children }: { title: string; icon: IconName; empty: string; children: React.ReactNode }) {
  const items = Array.isArray(children) ? children.flat().filter(Boolean) : children ? [children] : []
  return (
    <section className="flex flex-col gap-2 rounded-xl border border-rule bg-panel px-4 py-3.5">
      <h2 className="flex items-center gap-2 text-[13.5px] font-semibold text-ink">
        <Icon name={icon} size={15} className="text-ink-dim" />
        {title}
        {items.length > 0 && <span className="font-mono text-[12px] font-normal text-ink-dim">{items.length}</span>}
      </h2>
      {items.length ? (
        <ul className="flex max-h-[220px] flex-col gap-1 overflow-y-auto">{children}</ul>
      ) : (
        <p className="text-[12.5px] text-ink-dim">{empty}</p>
      )}
    </section>
  )
}
