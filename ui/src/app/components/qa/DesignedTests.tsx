import { useMemo, useState } from 'react'
import { api, ApiError, saveBlob } from '../../lib/api'
import { highlightLines } from '../../lib/highlight'
import { useAsync } from '../../lib/hooks'
import { Icon } from '../../lib/icons'
import type { QADesignedTest } from '../../lib/types'
import { ErrorState, SkeletonPanel } from '../States'
import { Pill } from '../primitives'
import { Button } from '../ui'
import { languageOf, OUTCOME } from './look'

/* ------------------------------------------------------------------ *
 * The tests a run designed: what each one checks, what happened when
 * the sandbox ran it, and the file itself, to read and keep. A list on
 * the left and the selected test on the right, like the findings.
 * ------------------------------------------------------------------ */

const ORDER: Record<string, number> = { bug: 0, passed: 1, wrong: 2, 'did-not-run': 3 }

/** A designed test file: highlighted, with copy and download. */
export function TestFile({ path, code }: { path: string; code: string }) {
  const [copied, setCopied] = useState(false)
  const html = useMemo(() => highlightLines(code.replace(/\n$/, ''), languageOf(path)), [code, path])
  const name = path.split('/').pop() || 'test'
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      setTimeout(() => setCopied(false), 1400)
    } catch {
      /* the code is selectable */
    }
  }
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-3">
        <span className="min-w-0 truncate font-mono text-[12px] text-ink-dim" title={path}>
          {path}
        </span>
        <button type="button" onClick={copy} className="ml-auto flex items-center gap-1.5 text-[12px] text-ink-mid hover:text-hot-ink">
          <Icon name={copied ? 'check' : 'copy'} size={13} /> {copied ? 'Copied' : 'Copy'}
        </button>
        <button
          type="button"
          onClick={() => saveBlob(new Blob([code], { type: 'text/plain' }), name)}
          className="flex items-center gap-1.5 text-[12px] text-ink-mid hover:text-hot-ink"
        >
          <Icon name="download" size={13} /> Download
        </button>
      </div>
      <div className="max-h-[520px] overflow-auto rounded-lg border border-rule bg-[var(--code-bg)] py-1.5 font-mono text-[12.5px] leading-[1.6]">
        <table className="w-full border-collapse">
          <tbody>
            {html.map((line, i) => (
              <tr key={i}>
                <td className="w-[1%] px-3 text-right whitespace-nowrap text-[var(--code-gutter)] select-none">{i + 1}</td>
                <td className="pr-4 whitespace-pre text-ink" dangerouslySetInnerHTML={{ __html: line || '&nbsp;' }} />
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Detail({ test }: { test: QADesignedTest }) {
  const look = OUTCOME[test.outcome] ?? OUTCOME['did-not-run']
  const results = new Map(test.results.map(r => [r.name, r]))
  const listed = new Set(test.cases.map(c => c.name))
  // Cases the model listed, then any test the file ran that it did not list.
  const rows = [
    ...test.cases.map(c => ({ ...c, result: results.get(c.name) })),
    ...test.results.filter(r => !listed.has(r.name)).map(r => ({ name: r.name, checks: '', expect: '', result: r })),
  ]
  return (
    <article className="flex min-w-0 flex-col gap-5 rounded-xl border border-rule bg-panel p-5">
      <header className="flex flex-col gap-2.5">
        <div className="flex flex-wrap items-center gap-2">
          <span title={look.title}>
            <Pill tone={look.tone} icon={look.icon}>
              {look.label}
            </Pill>
          </span>
          <Pill>{test.reason === 'finding' ? 'To reproduce a finding' : 'Nothing tested it'}</Pill>
          {test.tries > 1 && <Pill title="Written once, then corrected after it was judged a wrong test">{`${test.tries} tries`}</Pill>}
          <span className="ml-auto font-mono text-[11.5px] text-ink-dim">{test.framework}</span>
        </div>
        <h2 className="font-mono text-[16px] leading-snug font-semibold break-all text-ink">{test.target_name}</h2>
        <p className="font-mono text-[12.5px] break-all text-ink-mid">
          {test.target_path}
          {test.target_line ? `:${test.target_line}` : ''}
        </p>
      </header>

      {test.verdict && (
        <section className="flex flex-col gap-1.5">
          <h3 className="text-[13px] font-semibold text-ink">{test.outcome === 'bug' ? 'Why the code is at fault' : 'Why the test was not kept'}</h3>
          <p className="text-[13.5px] leading-relaxed text-ink-mid">{test.verdict}</p>
        </section>
      )}

      {rows.length > 0 && (
        <section className="flex flex-col gap-1.5">
          <h3 className="text-[13px] font-semibold text-ink">The cases</h3>
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Test</th>
                  <th>Checks</th>
                  <th>Expects</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(r => {
                  const outcome = r.result?.outcome
                  const bad = outcome === 'failed' || outcome === 'error'
                  return (
                    <tr key={r.name} title={bad ? r.result?.message : undefined}>
                      <td className="font-mono text-[12px] break-all">{r.name}</td>
                      <td className="text-[12.5px] text-ink-mid">{r.checks}</td>
                      <td className="text-[12.5px] text-ink-mid">{r.expect}</td>
                      <td className="whitespace-nowrap">
                        {outcome ? (
                          <span className={`flex items-center gap-1.5 text-[12.5px] ${bad ? 'text-bad' : outcome === 'passed' ? 'text-ok' : 'text-ink-dim'}`}>
                            <Icon name={bad ? 'circle-x' : outcome === 'passed' ? 'circle-check' : 'minus'} size={13} />
                            {outcome}
                          </span>
                        ) : (
                          <span className="text-[12.5px] text-ink-dim">not run</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {test.code && (
        <section className="flex flex-col gap-1.5">
          <h3 className="text-[13px] font-semibold text-ink">The test</h3>
          <TestFile path={test.file_path} code={test.code} />
        </section>
      )}

      {test.output && (
        <details className="group flex flex-col gap-1.5">
          <summary className="flex cursor-pointer items-center gap-1.5 text-[13px] font-semibold text-ink select-none">
            <Icon name="chevron-right" size={14} className="transition-transform group-open:rotate-90" />
            What the last run printed
          </summary>
          <pre className="mt-1.5 max-h-[320px] overflow-auto rounded-lg border border-rule bg-[var(--code-bg)] px-3 py-2 font-mono text-[12px] leading-[1.55] whitespace-pre text-ink-mid">
            {test.output}
          </pre>
        </details>
      )}
    </article>
  )
}

export function DesignedTests({ projectId, runId }: { projectId: number; runId: number }) {
  const tests = useAsync(s => api.qaDesigned(projectId, runId, s), [projectId, runId])
  const [selected, setSelected] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const sorted = useMemo(
    () => [...(tests.data ?? [])].sort((a, b) => (ORDER[a.outcome] ?? 9) - (ORDER[b.outcome] ?? 9) || a.id - b.id),
    [tests.data],
  )
  if (tests.loading) return <SkeletonPanel rows={6} />
  if (tests.error) return <ErrorState message={tests.error} onRetry={tests.reload} />
  if (!sorted.length) return <p className="text-[13px] text-ink-mid">This run designed no tests.</p>
  const shown = sorted.find(t => t.id === selected) ?? sorted[0]
  const keepable = sorted.filter(t => t.outcome === 'passed' || t.outcome === 'bug').length

  const download = async () => {
    setSaving(true)
    setError(null)
    try {
      await api.qaDesignedArchive(projectId, runId)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'The tests could not be downloaded.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-[12.5px] leading-snug text-ink-mid">
          Written by the model for code nothing tested, or to reproduce a suspected finding, then run in the sandbox with no
          network. Read each before adding it to the codebase.
        </p>
        <Button onClick={() => void download()} disabled={!keepable || saving} className="ml-auto">
          <Icon name={saving ? 'loader' : 'download'} size={14} className={saving ? 'animate-spin' : ''} />
          {keepable ? `Download the ${keepable} worth keeping` : 'None worth keeping'}
        </Button>
      </div>
      {error && <ErrorState message={error} compact />}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(280px,380px)_minmax(0,1fr)]">
        <aside className="flex min-w-0 flex-col self-start overflow-hidden rounded-xl border border-rule bg-panel lg:sticky lg:top-3">
          {sorted.map(t => {
            const look = OUTCOME[t.outcome] ?? OUTCOME['did-not-run']
            const current = t.id === shown.id
            return (
              <button
                key={t.id}
                type="button"
                aria-current={current}
                onClick={() => setSelected(t.id)}
                className={`flex items-start gap-2.5 border-b border-rule px-3.5 py-2.5 text-left last:border-b-0 ${
                  current ? 'bg-hot-wash' : 'hover:bg-hover'
                }`}
              >
                <Icon name={look.icon} size={15} className="mt-0.5 shrink-0" style={{ color: look.color }} />
                <span className="min-w-0">
                  <span className="block truncate font-mono text-[12.5px] text-ink">{t.target_name}</span>
                  <span className="block truncate text-[11.5px] text-ink-dim">
                    {look.label} · {t.target_path}
                  </span>
                </span>
              </button>
            )
          })}
        </aside>
        <Detail key={shown.id} test={shown} />
      </div>
    </div>
  )
}
