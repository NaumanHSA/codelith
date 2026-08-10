import { useCallback, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError } from '../../lib/api'
import type { QualityFinding, QualityReport } from '../../lib/types'
import { Button, PageHead, Panel } from '../../components/ui'
import { EmptyState, ErrorState } from '../../components/States'

/* ------------------------------------------------------------------ *
 * Quality.
 *
 * The first app whose output is a worklist rather than a document or a
 * conversation — so it is the first that has to answer "what do I do
 * first", and the ranking is the answer.
 *
 * Nothing runs on load. A check clones the repository and runs two
 * whole-repository passes over it; doing that because somebody clicked
 * a nav link would be rude with their laptop.
 * ------------------------------------------------------------------ */

const SEVERITY_STYLE: Record<string, string> = {
  error: 'border-bad/40 bg-bad-wash text-bad',
  warning: 'border-warn/40 bg-warn-wash text-warn',
  info: 'border-rule bg-sunk text-ink-dim',
}

function FindingRow({ finding }: { finding: QualityFinding }) {
  return (
    <li className="flex flex-col gap-1 border-b border-rule px-3 py-2.5 last:border-b-0">
      <div className="flex flex-wrap items-baseline gap-2">
        <span
          className={`tag shrink-0 border px-1.5 py-px ${
            SEVERITY_STYLE[finding.severity] ?? SEVERITY_STYLE.info
          }`}
        >
          {finding.severity}
        </span>
        <span className="tag text-ink-dim">{finding.tool}</span>
        <span className="font-mono text-[11.5px] font-semibold text-ink">{finding.rule}</span>
        <span className="ml-auto font-mono text-[11px] text-ink-dim">
          {finding.path}:{finding.line}
        </span>
      </div>

      <p className="font-sans text-[12.5px] leading-relaxed text-ink-mid">{finding.message}</p>

      {/* The half no linter can produce. Absent when there is nothing true to say —
          "affects 0 files" is noise, and a column full of it teaches people to skip
          the column. */}
      {finding.impact && (
        <p className="text-[11.5px] text-hot-ink">↳ {finding.impact}</p>
      )}
    </li>
  )
}

export default function QualityPage() {
  const { projectId } = useParams()
  const id = Number(projectId)

  const [report, setReport] = useState<QualityReport | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = useCallback(async () => {
    setRunning(true)
    setError(null)
    try {
      setReport(await api.runQuality(id))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'The check could not be run.')
    } finally {
      setRunning(false)
    }
  }, [id])

  const counts = report?.counts ?? {}

  return (
    <div className="mx-auto max-w-[1180px] p-5">
      <PageHead
        index="Q"
        title="Quality"
        sub="Findings from the tools that already know, and what each one touches."
        right={
          <Button variant="hot" onClick={run} disabled={running}>
            {running ? 'checking…' : report ? '↻ Check again' : 'Check this codebase →'}
          </Button>
        }
      />

      {error && <ErrorState message={error} onRetry={run} />}

      {running && (
        <div className="mb-4 border border-hot bg-hot-wash px-4 py-3">
          <p className="text-[12.5px] text-ink">
            Cloning the repository and running the checks. This takes a while — the
            tools read every file.
          </p>
        </div>
      )}

      {!report && !running && !error && (
        <EmptyState
          title="Nothing has been checked yet"
          body="A check clones this repository and runs the linters over it, then joins every finding to what the analysis knows — which files reach it, and which written pages cite it. Nothing runs until you ask."
          action={<Button variant="hot" onClick={run}>Check this codebase →</Button>}
        />
      )}

      {report && (
        <div className="flex flex-col gap-4">
          {/* An empty list means opposite things depending on this. */}
          {!report.checked && (
            <div className="border border-warn/40 bg-warn-wash px-3 py-2.5">
              <span className="tag text-warn">nothing ran</span>
              <p className="mt-1 font-sans text-[12px] text-ink">
                No checking tool was available, so this is not a clean bill of health.
              </p>
            </div>
          )}

          {report.drift_note && (
            <div className="border border-rule bg-sunk px-3 py-2 font-sans text-[12px] text-ink-mid">
              {report.drift_note}
            </div>
          )}

          <div className="grid grid-cols-2 gap-px border border-rule bg-rule sm:grid-cols-4">
            {[
              ['errors', counts.error ?? 0],
              ['warnings', counts.warning ?? 0],
              ['untested surface', report.surface.filter(s => !s.named_in.length).length],
              ['dependency issues', report.dependencies.length],
            ].map(([label, value]) => (
              <div key={String(label)} className="bg-panel px-3 py-2.5">
                <div className="text-[18px] leading-none font-bold text-ink">{value}</div>
                <div className="tag mt-1 text-ink-dim">{label}</div>
              </div>
            ))}
          </div>

          {/* Which tools ran, and what a missing one costs. */}
          <div className="flex flex-wrap gap-2">
            {report.tools.map(t => (
              <span
                key={t.tool}
                title={t.unavailable ?? undefined}
                className={`tag border px-2 py-1 ${
                  t.unavailable
                    ? 'border-warn/40 bg-warn-wash text-warn'
                    : 'border-rule bg-panel text-ink-dim'
                }`}
              >
                {t.tool} {t.unavailable ? '· not available' : `· ${t.findings} · ${t.seconds}s`}
              </span>
            ))}
          </div>

          <Panel title={`Findings (${report.findings.length} shown, worst first)`}>
            {report.findings.length ? (
              <ul>
                {report.findings.map((f, i) => (
                  <FindingRow key={`${f.path}:${f.line}:${f.rule}:${i}`} finding={f} />
                ))}
              </ul>
            ) : (
              <p className="p-3 font-sans text-[12.5px] text-ink-mid">
                {report.checked ? 'The tools found nothing.' : 'Nothing ran.'}
              </p>
            )}
          </Panel>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Panel title="Surface with no test">
              <p className="border-b border-rule px-3 py-2 font-sans text-[12px] text-ink-mid">
                {report.coverage_summary}
              </p>
              <ul className="max-h-[280px] overflow-y-auto">
                {report.surface.map(s => (
                  <li
                    key={`${s.kind}:${s.name}`}
                    className="flex items-baseline gap-2 border-b border-rule px-3 py-1.5 last:border-b-0"
                  >
                    <span className="tag shrink-0 text-ink-dim">{s.kind}</span>
                    <span className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-ink">
                      {s.name}
                    </span>
                    <span
                      className={`tag shrink-0 ${s.named_in.length ? 'text-ok' : 'text-warn'}`}
                    >
                      {s.named_in.length ? 'named' : 'no test'}
                    </span>
                  </li>
                ))}
              </ul>
              {/* Name matching finds a route nobody mentions and never finds one
                  exercised through a fixture. Saying so is what keeps this from
                  reading as coverage. */}
              <p className="border-t border-rule px-3 py-2 text-[10.5px] leading-snug text-ink-dim">
                Measured by looking for each name in the test files. A route exercised
                through a fixture without naming it counts as untested here.
              </p>
            </Panel>

            <div className="flex flex-col gap-4">
              <Panel title="Dependencies">
                <p className="border-b border-rule px-3 py-2 font-sans text-[12px] text-ink-mid">
                  {report.dependency_summary}
                </p>
                <ul className="max-h-[200px] overflow-y-auto">
                  {report.dependencies.map(d => (
                    <li
                      key={`${d.issue}:${d.package}`}
                      className="flex items-baseline gap-2 border-b border-rule px-3 py-1.5 last:border-b-0"
                    >
                      <span className="tag shrink-0 text-warn">{d.issue}</span>
                      <span className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-ink">
                        {d.package}
                      </span>
                    </li>
                  ))}
                </ul>
              </Panel>

              <Panel title="Layering">
                <p className="border-b border-rule px-3 py-2 font-sans text-[12px] text-ink-mid">
                  {report.layering_summary}
                </p>
                <ul>
                  {report.layering.map(d => (
                    <li
                      key={`${d.source_role}:${d.target_role}`}
                      className="border-b border-rule px-3 py-2 last:border-b-0"
                    >
                      {d.is_new && <span className="tag mr-2 text-hot-ink">new</span>}
                      <span className="font-sans text-[12px] text-ink-mid">{d.summary}</span>
                      {d.examples.slice(0, 2).map(([from, to]) => (
                        <div key={from} className="mt-1 font-mono text-[10.5px] text-ink-dim">
                          {from} → {to}
                        </div>
                      ))}
                    </li>
                  ))}
                </ul>
              </Panel>
            </div>
          </div>

          <p className="text-[11px] text-ink-dim">
            Checked against knowledge base #{report.kb_id}.{' '}
            <Link to={`/app/projects/${id}`} className="text-hot-ink hover:underline">
              Back to the codebase
            </Link>
          </p>
        </div>
      )}
    </div>
  )
}
