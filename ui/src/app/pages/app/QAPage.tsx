import { useEffect, useMemo, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { DesignedTests } from '../../components/qa/DesignedTests'
import { FindingDetail } from '../../components/qa/FindingDetail'
import { FindingList } from '../../components/qa/FindingList'
import { areaIcon, SEVERITIES, SEVERITY } from '../../components/qa/look'
import { RunDialog } from '../../components/qa/RunDialog'
import { ErrorState, SkeletonPanel } from '../../components/States'
import { IconTile, StatBlock } from '../../components/primitives'
import { Button, inputClass } from '../../components/ui'
import { api, ApiError, saveBlob } from '../../lib/api'
import { shortSha } from '../../lib/format'
import { useAsync } from '../../lib/hooks'
import { Icon } from '../../lib/icons'
import { APP_LOOKS } from '../../lib/kinds'
import { stageIcon, stagePurpose } from '../../lib/narrate'
import type { QAFinding, QARun, QASeverity } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * QA for one codebase: run a check, watch it, read what it found.
 *
 * The findings read like the Changes page: a list on the left, most
 * severe first, and the selected one on the right with its code, why
 * it matters, what it touches and how to fix it. Filters live in the
 * URL, so a finding can be linked to.
 * ------------------------------------------------------------------ */

const LIVE = new Set(['queued', 'running'])
const POLL_MS = 1200

function when(iso: string) {
  return new Date(iso).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

function Progress({ run, onCancel }: { run: QARun; onCancel: () => void }) {
  const done = new Map(run.steps.map(s => [s.name, s.status]))
  return (
    <section className="flex max-w-[760px] flex-col gap-4 rounded-xl border border-rule bg-panel p-5">
      <div className="flex items-center gap-3">
        <Icon name="loader" size={18} className="animate-spin text-hot" />
        <h2 className="text-[15px] font-semibold text-ink">{run.status === 'queued' ? 'Waiting to start' : 'Checking'}</h2>
        <Button onClick={onCancel} className="ml-auto">
          <Icon name="x" size={14} /> Cancel
        </Button>
      </div>
      <ol className="flex flex-col gap-1.5">
        {run.stages.map(stage => {
          const status = done.get(stage)
          return (
            <li key={stage} className="flex items-center gap-3 text-[13px]">
              <span className={`grid size-[22px] place-items-center rounded-md ${status === 'completed' ? 'text-ok' : status === 'running' ? 'text-hot' : 'text-ink-dim'}`}>
                <Icon
                  name={status === 'completed' ? 'circle-check' : status === 'running' ? 'loader' : stageIcon(stage)}
                  size={15}
                  className={status === 'running' ? 'animate-spin' : ''}
                />
              </span>
              <span className={status ? 'text-ink' : 'text-ink-dim'}>{stagePurpose(stage)}</span>
            </li>
          )
        })}
      </ol>
    </section>
  )
}

function Empty({ onRun, areas }: { onRun: () => void; areas: { id: string; label: string; icon: string; blurb: string }[] }) {
  return (
    <section className="flex max-w-[900px] flex-col gap-5 rounded-xl border border-rule bg-panel p-6">
      <div className="flex flex-col gap-2">
        <h2 className="text-[17px] font-semibold text-ink">What a QA engineer checks, starting from what Codelith knows</h2>
        <p className="max-w-[72ch] text-[13.5px] leading-relaxed text-ink-mid">
          Pick what to look for. Every finding points at an exact line, says how sure it is, what it touches (the part,
          the routes that reach it, what depends on it, whether a test does) and how to fix it. Dismiss what is not a
          problem here, with a reason, and the next run remembers.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
        {areas.map(a => (
          <div key={a.id} className="flex items-start gap-3">
            <IconTile icon={areaIcon(a.icon)} size={30} />
            <div className="min-w-0">
              <p className="text-[13px] font-medium text-ink">{a.label}</p>
              <p className="text-[12.5px] leading-snug text-ink-mid">{a.blurb}</p>
            </div>
          </div>
        ))}
      </div>
      <div>
        <Button variant="hot" onClick={onRun}>
          <Icon name="play" size={14} /> Run a check
        </Button>
      </div>
    </section>
  )
}

export default function QAPage() {
  const { projectId } = useParams()
  const id = Number(projectId)
  const [params, setParams] = useSearchParams()
  const catalog = useAsync(s => api.qaCatalog(id, s), [id])
  const runs = useAsync(s => api.qaRuns(id, s), [id])
  const [dialog, setDialog] = useState(false)
  const [asked, setAsked] = useState<string[] | null>(null)
  const [exporting, setExporting] = useState<string | null>(null)
  const [live, setLive] = useState<QARun | null>(null)
  const [cancelError, setCancelError] = useState<string | null>(null)

  const setParam = (changes: Record<string, string | null>) =>
    setParams(
      p => {
        const next = new URLSearchParams(p)
        for (const [k, v] of Object.entries(changes)) {
          if (v === null || v === '') next.delete(k)
          else next.set(k, v)
        }
        return next
      },
      { replace: true },
    )

  const runId = params.get('run') ? Number(params.get('run')) : null
  const chosen = runs.data?.find(r => r.id === runId) ?? runs.data?.[0] ?? null
  const run = live && chosen && live.id === chosen.id ? live : chosen

  // A run still working is polled until it settles; then the list is read again.
  useEffect(() => {
    if (!chosen || !LIVE.has(chosen.status)) return
    let stop = false
    const tick = async () => {
      try {
        const fresh = await api.qaRun(id, chosen.id)
        if (stop) return
        setLive(fresh)
        if (!LIVE.has(fresh.status)) runs.reload()
      } catch {
        /* the next tick tries again */
      }
    }
    void tick()
    const timer = setInterval(() => void tick(), POLL_MS)
    return () => {
      stop = true
      clearInterval(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, chosen?.id, chosen?.status])

  const findings = useAsync(
    s => (run && run.status === 'completed' ? api.qaFindings(id, run.id, s) : Promise.resolve([] as QAFinding[])),
    [id, run?.id, run?.status],
  )

  const area = params.get('area')
  const designedCount = Object.values(run?.summary.designed ?? {}).reduce((a, b) => a + (b ?? 0), 0)
  const view = designedCount && params.get('view') === 'designed' ? 'designed' : 'findings'
  const severity = params.get('severity') as QASeverity | null
  const status = params.get('status') ?? 'open'
  const q = params.get('q') ?? ''
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return (findings.data ?? []).filter(
      f =>
        (!area || f.area === area) &&
        (!severity || f.severity === severity) &&
        (status === 'all' || f.status === status) &&
        (!needle || `${f.title} ${f.path ?? ''} ${f.rule}`.toLowerCase().includes(needle)),
    )
  }, [findings.data, area, severity, status, q])
  const selectedId = params.get('f') ? Number(params.get('f')) : null
  const selected = shown.find(f => f.id === selectedId) ?? shown[0] ?? null

  useEffect(() => {
    document.querySelector('[data-qa-finding][aria-current="true"]')?.scrollIntoView({ block: 'nearest' })
  }, [selected?.id])

  const look = APP_LOOKS.qa
  const areaLabel = (a: string) => catalog.data?.areas.find(x => x.id === a)?.label ?? a
  const openCounts = useMemo(() => {
    const open = (findings.data ?? []).filter(f => f.status === 'open')
    return {
      severity: Object.fromEntries(SEVERITIES.map(s => [s, open.filter(f => f.severity === s).length])) as Record<QASeverity, number>,
      area: open.reduce<Record<string, number>>((m, f) => ({ ...m, [f.area]: (m[f.area] ?? 0) + 1 }), {}),
      decided: (findings.data ?? []).length - open.length,
    }
  }, [findings.data])

  // `?check=security,tests` (from an answer in Ask) opens the dialog with those areas.
  const check = params.get('check')
  useEffect(() => {
    if (!check || !catalog.data) return
    const known = new Set(catalog.data.areas.map(a => a.id))
    setAsked(check.split(',').filter(a => known.has(a)))
    setDialog(true)
    setParam({ check: null })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [check, catalog.data])

  const exportAs = async (format: 'markdown' | 'sarif', how: 'save' | 'copy') => {
    if (!run) return
    setExporting(`${format}:${how}`)
    setCancelError(null)
    try {
      const { text, filename } = await api.qaReport(id, run.id, format)
      if (how === 'copy') await navigator.clipboard.writeText(text)
      else saveBlob(new Blob([text], { type: format === 'sarif' ? 'application/json' : 'text/markdown' }), filename)
    } catch (e) {
      setCancelError(e instanceof ApiError ? e.message : 'The report could not be written.')
    } finally {
      setTimeout(() => setExporting(null), 900)
    }
  }

  const cancel = async () => {
    if (!run) return
    setCancelError(null)
    try {
      await api.qaCancel(id, run.id)
      runs.reload()
    } catch (e) {
      setCancelError(e instanceof ApiError ? e.message : 'Could not cancel the run.')
    }
  }

  if (catalog.loading || runs.loading)
    return (
      <div className="w-full px-6 py-5">
        <SkeletonPanel rows={6} />
      </div>
    )
  if (catalog.error || runs.error)
    return (
      <div className="w-full px-6 py-5">
        <ErrorState message={catalog.error ?? runs.error ?? ''} onRetry={() => (catalog.reload(), runs.reload())} />
      </div>
    )
  const all = runs.data ?? []
  const summary = run?.summary ?? {}

  return (
    <div className="flex w-full flex-col gap-6 px-6 py-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex items-center gap-3.5">
          <IconTile icon={look.icon} color={look.color} tint size={44} />
          <div>
            <h1 className="text-[22px] leading-tight font-semibold text-ink">QA</h1>
            <p className="mt-1 text-[13px] text-ink-mid">
              {run && run.status === 'completed'
                ? `${summary.files ?? 0} files at ${shortSha(summary.commit ?? null)} · ${summary.scope ?? ''}`
                : 'Checks run against a reading of the code.'}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          {all.length > 1 && (
            <label className="flex flex-col gap-1">
              <span className="text-[11.5px] font-medium text-ink-dim">Run</span>
              <select
                className={`${inputClass} max-w-[360px]`}
                value={run?.id ?? ''}
                onChange={e => setParam({ run: e.target.value, f: null })}
              >
                {all.map(r => (
                  <option key={r.id} value={r.id}>
                    #{r.id} · {when(r.created_at)} · {r.status === 'completed' ? `${r.summary.open ?? 0} open` : r.status}
                  </option>
                ))}
              </select>
            </label>
          )}
          {run?.status === 'completed' && (
            <div className="flex items-center gap-1 rounded-lg border border-rule bg-panel p-[3px]" role="group" aria-label="Export">
              <button
                type="button"
                onClick={() => void exportAs('markdown', 'save')}
                title="The open findings as a checklist, most severe and quickest first, with every fix and patch"
                className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[12.5px] font-medium text-ink-mid transition-colors hover:bg-hover hover:text-ink"
              >
                <Icon name={exporting === 'markdown:save' ? 'check' : 'list-checks'} size={14} /> Fix plan
              </button>
              <button
                type="button"
                onClick={() => void exportAs('markdown', 'copy')}
                title="Copy the fix plan as Markdown"
                aria-label="Copy the fix plan as Markdown"
                className="flex items-center rounded-md px-2 py-1.5 text-ink-mid transition-colors hover:bg-hover hover:text-ink"
              >
                <Icon name={exporting === 'markdown:copy' ? 'check' : 'copy'} size={14} />
              </button>
              <button
                type="button"
                onClick={() => void exportAs('sarif', 'save')}
                title="SARIF 2.1.0, for GitHub code scanning and editors"
                className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[12.5px] font-medium text-ink-mid transition-colors hover:bg-hover hover:text-ink"
              >
                <Icon name={exporting === 'sarif:save' ? 'check' : 'download'} size={14} /> SARIF
              </button>
            </div>
          )}
          {all.length > 0 && (
            <Button variant="hot" onClick={() => setDialog(true)} disabled={!!run && LIVE.has(run.status)}>
              <Icon name="play" size={14} /> Run a check
            </Button>
          )}
        </div>
      </header>

      {cancelError && <ErrorState message={cancelError} compact />}

      {!run ? (
        <Empty onRun={() => setDialog(true)} areas={catalog.data?.areas ?? []} />
      ) : LIVE.has(run.status) ? (
        <Progress run={run} onCancel={() => void cancel()} />
      ) : run.status === 'failed' ? (
        <ErrorState message={run.error || 'The run failed.'} />
      ) : run.status === 'cancelled' ? (
        <p className="rounded-xl border border-rule bg-panel px-4 py-3 text-[13px] text-ink-mid">This run was cancelled before it finished.</p>
      ) : (
        <>
          <section className="flex flex-col gap-3">
            <div className="grid grid-cols-2 gap-x-6 border-y border-rule sm:grid-cols-3 xl:grid-cols-6">
              {SEVERITIES.map(s => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setParam({ severity: severity === s ? null : s, f: null })}
                  aria-pressed={severity === s}
                  className={`text-left transition-opacity ${severity && severity !== s ? 'opacity-40' : ''}`}
                >
                  <StatBlock
                    value={openCounts.severity[s] ?? 0}
                    label={SEVERITY[s].label.toLowerCase()}
                    icon={SEVERITY[s].icon}
                    color={openCounts.severity[s] ? SEVERITY[s].color : undefined}
                  />
                </button>
              ))}
              <StatBlock
                value={summary.compared_with ? `${summary.new ?? 0} / ${summary.fixed ?? 0}` : '-'}
                label={summary.compared_with ? `new / fixed since run #${summary.compared_with}` : 'new / fixed (first run)'}
                icon="git-compare-arrows"
              />
            </div>
            {!!summary.notes?.length && (
              <ul className="flex flex-col gap-1 text-[12.5px] text-ink-mid">
                {summary.notes.map(n => (
                  <li key={n} className="flex items-start gap-2">
                    <Icon name="info" size={13} className="mt-0.5 shrink-0 text-ink-dim" />
                    {n}
                  </li>
                ))}
              </ul>
            )}
          </section>

          {designedCount > 0 && (
            <div className="flex gap-0.5 self-start rounded-lg border border-rule bg-paper p-[3px]" role="tablist" aria-label="What to show">
              {(
                [
                  ['findings', 'Findings', 'list-checks', (findings.data ?? []).length],
                  ['designed', 'Designed tests', 'flask-conical', designedCount],
                ] as const
              ).map(([t, label, icon, count]) => (
                <button
                  key={t}
                  type="button"
                  role="tab"
                  aria-selected={view === t}
                  onClick={() => setParam({ view: t === 'findings' ? null : t })}
                  className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors ${
                    view === t ? 'bg-sunk text-ink shadow-[inset_0_0_0_1px_var(--line-2)]' : 'text-ink-mid hover:text-ink'
                  }`}
                >
                  <Icon name={icon} size={14} />
                  {label}
                  <span className="font-mono text-[11.5px] text-ink-dim">{count}</span>
                </button>
              ))}
            </div>
          )}

          {view === 'designed' ? (
            <DesignedTests projectId={id} runId={run.id} />
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => setParam({ area: null, f: null })}
                  aria-pressed={!area}
                  className={`rounded-full border px-3 py-1 text-[12.5px] transition-colors ${!area ? 'border-hot-edge bg-hot-wash text-hot-ink' : 'border-line-2 text-ink-mid hover:text-ink'}`}
                >
                  Every area
                </button>
                {run.areas.map(a => (
                  <button
                    key={a}
                    type="button"
                    onClick={() => setParam({ area: area === a ? null : a, f: null })}
                    aria-pressed={area === a}
                    className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-[12.5px] transition-colors ${
                      area === a ? 'border-hot-edge bg-hot-wash text-hot-ink' : 'border-line-2 text-ink-mid hover:text-ink'
                    }`}
                  >
                    <Icon name={areaIcon(catalog.data?.areas.find(x => x.id === a)?.icon)} size={13} />
                    {areaLabel(a)}
                    <span className="font-mono text-[11px] text-ink-dim">{openCounts.area[a] ?? 0}</span>
                  </button>
                ))}
                <select
                  className={`${inputClass} ml-auto max-w-[220px]`}
                  value={status}
                  onChange={e => setParam({ status: e.target.value === 'open' ? null : e.target.value, f: null })}
                  aria-label="Which findings"
                >
                  <option value="open">Open</option>
                  <option value="dismissed">Dismissed</option>
                  <option value="accepted">Risk accepted</option>
                  <option value="all">All {openCounts.decided ? `(${openCounts.decided} decided)` : ''}</option>
                </select>
              </div>

              {findings.loading ? (
                <SkeletonPanel rows={8} />
              ) : findings.error ? (
                <ErrorState message={findings.error} onRetry={findings.reload} />
              ) : !(findings.data ?? []).length ? (
                <section className="flex items-center gap-3 rounded-xl border border-rule bg-panel px-5 py-4">
                  <Icon name="circle-check" size={18} className="text-ok" />
                  <p className="text-[13.5px] text-ink">
                    Nothing found in {run.areas.map(areaLabel).join(', ').toLowerCase()} across {summary.files ?? 0} files.
                  </p>
                </section>
              ) : (
                <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(280px,380px)_minmax(0,1fr)]">
                  <aside className="flex min-w-0 flex-col gap-2 lg:sticky lg:top-3 lg:max-h-[calc(100vh-120px)] lg:self-start">
                    <input
                      className={inputClass}
                      placeholder={`Filter ${shown.length} findings`}
                      value={q}
                      onChange={e => setParam({ q: e.target.value })}
                      aria-label="Filter the findings"
                    />
                    <div className="min-h-0 overflow-y-auto rounded-xl border border-rule bg-panel">
                      <FindingList
                        findings={shown}
                        selectedId={selected?.id ?? null}
                        onSelect={fid => setParam({ f: String(fid) })}
                        searching={!!q.trim()}
                      />
                    </div>
                    {(summary.suppressed ?? 0) > 0 && (
                      <p className="px-1 text-[11.5px] text-ink-dim">
                        {summary.suppressed} silenced in the code with <code className="font-mono">codelith: ignore</code>.
                      </p>
                    )}
                  </aside>
                  {selected ? (
                    <FindingDetail key={selected.id} projectId={id} findingId={selected.id} onChanged={findings.reload} />
                  ) : (
                    <p className="text-[13px] text-ink-mid">Pick a finding.</p>
                  )}
                </div>
              )}
            </>
          )}
        </>
      )}

      {catalog.data && (
        <RunDialog
          open={dialog}
          onClose={() => {
            setDialog(false)
            setAsked(null)
          }}
          projectId={id}
          catalog={catalog.data}
          initial={asked?.length ? asked : run?.areas.length ? run.areas : catalog.data.areas.map(a => a.id)}
          onStarted={started => {
            setDialog(false)
            setLive(started)
            setParam({ run: String(started.id), f: null, area: null, severity: null, view: null })
            runs.reload()
          }}
        />
      )}
    </div>
  )
}
