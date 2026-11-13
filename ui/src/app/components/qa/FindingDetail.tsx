import { Fragment, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../../lib/api'
import { highlightLines } from '../../lib/highlight'
import { useAsync } from '../../lib/hooks'
import { Icon } from '../../lib/icons'
import type { QAFinding } from '../../lib/types'
import { ErrorState, SkeletonPanel } from '../States'
import { Pill } from '../primitives'
import { Button, inputClass } from '../ui'
import { TestFile } from './DesignedTests'
import { DiffView } from '../changes/DiffView'
import { CONFIDENCE, EXPOSURE, languageOf, patchRows, SEVERITY } from './look'
import { NEW_TAB } from '../layout/tabState'

/* ------------------------------------------------------------------ *
 * One finding: where it is, why it matters, what it touches, and how
 * to fix it, with the code around it as the reading kept it. Secrets
 * arrive masked from the server; nothing here unmasks them.
 * ------------------------------------------------------------------ */

/** Text with `code` spans, as the findings write it. */
export function Inline({ text }: { text: string }) {
  return (
    <>
      {text.split('`').map((part, i) =>
        i % 2 ? (
          <code key={i} className="rounded bg-sunk px-1 py-px font-mono text-[0.92em] text-ink">
            {part}
          </code>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        ),
      )}
    </>
  )
}

function Code({ context, from, to, path }: { context: [number, string][]; from: number; to: number; path: string | null }) {
  const html = useMemo(() => highlightLines(context.map(([, t]) => t).join('\n'), languageOf(path)), [context, path])
  return (
    <div className="overflow-x-auto rounded-lg border border-rule bg-[var(--code-bg)] py-1.5 font-mono text-[12.5px] leading-[1.6]">
      <table className="w-full border-collapse">
        <tbody>
          {context.map(([n], i) => {
            const flagged = n >= from && n <= to
            return (
              <tr key={n} className={flagged ? 'bg-hot-wash' : ''}>
                <td
                  className={`w-[1%] border-l-2 px-3 text-right whitespace-nowrap select-none ${
                    flagged ? 'border-hot text-hot-ink' : 'border-transparent text-[var(--code-gutter)]'
                  }`}
                >
                  {n}
                </td>
                <td className="pr-4 whitespace-pre text-ink" dangerouslySetInnerHTML={{ __html: html[i] || '&nbsp;' }} />
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/** A suggested change in the diff viewer, with what the sandbox made of it. */
function Patch({ text, path, verified, note }: { text: string; path: string | null; verified?: string | null; note?: string | null }) {
  const [copied, setCopied] = useState(false)
  const rows = useMemo(() => patchRows(text), [text])
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1400)
    } catch {
      /* the patch is selectable */
    }
  }
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[12px] font-medium text-ink-dim">Suggested change</span>
        {verified && (
          <span title={verified}>
            <Pill tone="good" icon="circle-check">
              Tests still pass
            </Pill>
          </span>
        )}
        <button type="button" onClick={copy} className="ml-auto flex items-center gap-1.5 text-[12px] text-ink-mid hover:text-hot-ink">
          <Icon name={copied ? 'check' : 'copy'} size={13} /> {copied ? 'Copied' : 'Copy the patch'}
        </button>
      </div>
      {rows.length ? (
        <div className="overflow-hidden rounded-lg border border-rule">
          <DiffView rows={rows} language={languageOf(path)} mode="unified" />
        </div>
      ) : (
        <pre className="overflow-x-auto rounded-lg border border-rule bg-[var(--code-bg)] px-3 py-1.5 font-mono text-[12.5px]">{text}</pre>
      )}
      {verified && <p className="text-[12px] leading-snug text-ink-dim">{verified}</p>}
      {note && <p className="text-[12px] leading-snug text-ink-dim">{note}</p>}
      <p className="text-[11.5px] text-ink-dim">
        Apply it with <code className="font-mono">git apply</code>; it was written against the reading&apos;s commit.
      </p>
    </div>
  )
}

function Touches({ finding, projectId }: { finding: QAFinding; projectId: number }) {
  const i = finding.impact
  const entries = Array.isArray(i.entries) ? i.entries : null
  const rows: React.ReactNode[] = []
  if (i.part)
    rows.push(
      <>
        In <span className="font-medium text-ink">{i.part}</span>
        {i.function && (
          <>
            , in <code className="font-mono text-[12px] text-ink">{i.function}</code>
          </>
        )}
      </>,
    )
  if (i.exposure)
    rows.push(
      <span className={i.exposure === 'public' ? 'font-medium text-bad' : undefined}>{EXPOSURE[i.exposure] ?? i.exposure}</span>,
    )
  if (i.routes?.length)
    rows.push(
      <>
        {i.route_count === 1 ? 'Through ' : `Through ${i.route_count} routes, among them `}
        {i.routes.slice(0, 4).map((r, k) => (
          <Fragment key={r}>
            {k > 0 && ', '}
            <code className="font-mono text-[12px] text-ink">{r}</code>
          </Fragment>
        ))}
      </>,
    )
  if (i.reach !== undefined && i.kind !== null)
    rows.push(i.reach ? `${i.reach} file${i.reach === 1 ? ' depends' : 's depend'} on this file` : 'Nothing depends on this file')
  if (i.tests !== undefined && i.kind !== null) rows.push(i.tests ? `${i.tests} test${i.tests === 1 ? '' : 's'} reach it` : 'No test reaches it')
  if (i.pages) rows.push(`Cited by ${i.pages} written page${i.pages === 1 ? '' : 's'}`)
  if (i.read_in?.length) rows.push(<>Read in {i.read_in.map(p => <code key={p} className="mr-1 font-mono text-[12px]">{p}</code>)}</>)
  return (
    <div className="flex flex-col gap-2">
      {i.chain && i.chain.length > 1 && (
        <div className="flex flex-col gap-1 rounded-lg border border-rule bg-sunk px-3 py-2">
          <span className="text-[11.5px] font-medium text-ink-dim">How a request gets here</span>
          <ol className="flex flex-wrap items-center gap-x-1.5 gap-y-1 font-mono text-[12px]">
            {i.chain.map((step, k) => (
              <li key={`${k}-${step}`} className="flex items-center gap-1.5">
                {k > 0 && <Icon name="arrow-right" size={12} className="text-ink-dim" />}
                <span className={k === 0 ? 'text-hot-ink' : k === i.chain!.length - 1 ? 'font-semibold text-ink' : 'text-ink-mid'}>{step}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
      <ul className="flex flex-col gap-1 text-[13px] text-ink-mid">
        {rows.map((r, k) => (
          <li key={k} className="flex items-start gap-2">
            <Icon name="arrow-right" size={13} className="mt-1 shrink-0 text-ink-dim" />
            <span>{r}</span>
          </li>
        ))}
      </ul>
      {entries && (
        <div className="overflow-x-auto">
          <table className="tbl">
            <tbody>
              {entries.map(e => (
                <tr key={`${e.kind}-${e.name}`}>
                  <td className="font-mono text-[12px] text-ink">{e.name}</td>
                  <td className="text-[12px] text-ink-dim">{e.ends === 'data' ? 'reaches data' : e.ends === 'outside' ? 'calls an outside service' : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {finding.path && (
        <Link
          to={`/app/projects/${projectId}/graph?file=${encodeURIComponent(finding.path)}`}
          state={NEW_TAB}
          className="flex items-center gap-1.5 self-start text-[12.5px] text-ink-mid transition-colors hover:text-hot-ink"
        >
          <Icon name="network" size={13} /> Open in the graph
        </Link>
      )}
    </div>
  )
}

function Decide({ projectId, finding, onChanged }: { projectId: number; finding: QAFinding; onChanged: () => void }) {
  const [mode, setMode] = useState<'dismissed' | 'accepted' | null>(null)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const send = async (status: 'open' | 'dismissed' | 'accepted') => {
    setBusy(true)
    setError(null)
    try {
      await api.qaSetState(projectId, finding.fingerprint, status, reason.trim())
      setMode(null)
      setReason('')
      onChanged()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not save.')
    } finally {
      setBusy(false)
    }
  }
  if (finding.status !== 'open')
    return (
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-rule bg-sunk px-3 py-2.5 text-[13px] text-ink-mid">
        <Icon name={finding.status === 'dismissed' ? 'eye-off' : 'shield'} size={15} />
        <span className="min-w-0 flex-1">
          {finding.status === 'dismissed' ? 'Dismissed: not a problem.' : 'Risk accepted.'}
          {finding.reason && <span className="text-ink"> {finding.reason}</span>}
        </span>
        <Button onClick={() => void send('open')} disabled={busy}>
          <Icon name="undo-2" size={14} /> Open it again
        </Button>
      </div>
    )
  return (
    <div className="flex flex-col gap-2">
      {mode ? (
        <>
          <textarea
            className={`${inputClass} min-h-[60px]`}
            placeholder={mode === 'dismissed' ? 'Why this is not a problem here' : 'Why it is acceptable, and until when'}
            value={reason}
            onChange={e => setReason(e.target.value)}
            autoFocus
          />
          {error && <ErrorState message={error} compact />}
          <div className="flex gap-2">
            <Button variant="solid" onClick={() => void send(mode)} disabled={busy || !reason.trim()}>
              {mode === 'dismissed' ? 'Dismiss' : 'Accept the risk'}
            </Button>
            <Button onClick={() => setMode(null)}>Cancel</Button>
          </div>
          <p className="text-[12px] text-ink-dim">Kept for this codebase: the next run recognises it, even after the line moves.</p>
        </>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => setMode('dismissed')}>
            <Icon name="eye-off" size={14} /> Not a problem
          </Button>
          <Button onClick={() => setMode('accepted')}>
            <Icon name="shield" size={14} /> Accept the risk
          </Button>
          <Link
            to={`/app/chat?project=${projectId}&thread=new&ask=${encodeURIComponent(
              `QA found this in ${finding.path ?? 'the codebase'}${finding.line ? `:${finding.line}` : ''}: "${finding.title}". Is it a real problem here, and what is the safest way to fix it?`,
            )}`}
            className="inline-flex items-center gap-2 rounded-lg border border-line-2 px-3.5 py-[7px] text-[13px] font-medium text-ink-mid transition-colors hover:border-hot-edge hover:text-hot-ink"
          >
            <Icon name="message-square" size={14} /> Ask about it
          </Link>
        </div>
      )}
    </div>
  )
}

export function FindingDetail({ projectId, findingId, onChanged }: { projectId: number; findingId: number; onChanged: () => void }) {
  const detail = useAsync(s => api.qaFinding(projectId, findingId, s), [projectId, findingId])
  if (detail.loading) return <SkeletonPanel rows={8} />
  if (detail.error) return <ErrorState message={detail.error} onRetry={detail.reload} />
  const f = detail.data
  if (!f) return null
  const sev = SEVERITY[f.severity] ?? SEVERITY.info
  const conf = CONFIDENCE[f.confidence]
  return (
    <article className="flex min-w-0 flex-col gap-5 rounded-xl border border-rule bg-panel p-5">
      <header className="flex flex-col gap-2.5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="flex items-center gap-1.5 text-[12.5px] font-semibold" style={{ color: sev.color }}>
            <Icon name={sev.icon} size={14} /> {sev.label}
          </span>
          {conf && (
            <span title={conf.title}>
              <Pill>{conf.label}</Pill>
            </span>
          )}
          {f.is_new && <Pill tone="hot">New</Pill>}
          {f.impact.raised_from && (
            <span title="A route anyone can call reaches this line, so it was raised one level">
              <Pill tone="bad" icon="arrow-up-right">
                Raised from {SEVERITY[f.impact.raised_from]?.label.toLowerCase() ?? f.impact.raised_from}
              </Pill>
            </span>
          )}
          <span className="ml-auto font-mono text-[11.5px] text-ink-dim" title="The rule or check that found it">
            {f.rule}
          </span>
        </div>
        <h2 className="text-[17px] leading-snug font-semibold text-ink">
          <Inline text={f.title} />
        </h2>
        {f.path && (
          <p className="font-mono text-[12.5px] break-all text-ink-mid">
            {f.path}
            {f.line ? `:${f.line}` : ''}
          </p>
        )}
      </header>

      {f.context.length > 0 && <Code context={f.context} from={f.line ?? 0} to={f.end_line ?? f.line ?? 0} path={f.path} />}

      <section className="flex flex-col gap-1.5">
        <h3 className="text-[13px] font-semibold text-ink">Why it matters</h3>
        <p className="text-[13.5px] leading-relaxed text-ink-mid">
          <Inline text={f.message} />
        </p>
      </section>

      <section className="flex flex-col gap-1.5">
        <h3 className="text-[13px] font-semibold text-ink">What it touches</h3>
        <Touches finding={f} projectId={projectId} />
      </section>

      <section className="flex flex-col gap-1.5">
        <h3 className="text-[13px] font-semibold text-ink">How to fix it</h3>
        <p className="text-[13.5px] leading-relaxed text-ink">
          <Inline text={f.fix} />
        </p>
        {f.patch && <Patch text={f.patch} path={f.path} verified={f.verified} note={f.fix_note} />}
      </section>

      {f.designed_test && f.designed_test.code && (
        <section className="flex flex-col gap-1.5">
          <h3 className="text-[13px] font-semibold text-ink">The test that shows it</h3>
          <p className="text-[12.5px] leading-snug text-ink-mid">
            Designed by the model and run in the sandbox, where it failed. Add it to the codebase's tests, and it passes once
            this is fixed.
          </p>
          <TestFile path={f.designed_test.file_path} code={f.designed_test.code} />
        </section>
      )}

      <Decide
        projectId={projectId}
        finding={f}
        onChanged={() => {
          detail.reload()
          onChanged()
        }}
      />
    </article>
  )
}
