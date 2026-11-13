import { useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../../lib/api'
import { useAsync } from '../../lib/hooks'
import { useAuth } from '../../auth'
import { useRunningJobs } from '../../running-jobs'
import { countLabel, shortSha } from '../../lib/format'
import { Icon, type IconName } from '../../lib/icons'
import { APP_LOOKS, factKindOf } from '../../lib/kinds'
import { ErrorState, SkeletonPanel } from '../../components/States'
import { Button, Dialog, inputClass } from '../../components/ui'
import { Commits } from '../../components/changes/Commits'
import { FilesChanged } from '../../components/changes/FilesChanged'
import { IconTile, Pill, StatBlock } from '../../components/primitives'
import ReanalyseDialog from '../../components/projects/ReanalyseDialog'
import type { Comparison, Drift, DriftPageAtRisk, Reading } from '../../lib/types'
import { NEW_TAB } from '../../components/layout/tabState'

/* ------------------------------------------------------------------ *
 * What changed between two readings: any two, picked at the top.
 *
 * Files first, line by line, each with what the reading knows about it
 * (its part, what depends on it, whether a test reaches it, the pages
 * that cite it), because that is what a reviewer reads. What it means
 * is the second tab: the pages now describing code that moved, the
 * parts, modules and facts, each leading back to its files.
 * ------------------------------------------------------------------ */

const CHANGE: Record<string, { tone: 'good' | 'bad' | 'hot' | 'plain'; icon: IconName }> = {
  added: { tone: 'good', icon: 'plus' },
  removed: { tone: 'bad', icon: 'minus' },
  rewritten: { tone: 'hot', icon: 'pencil' },
  grew: { tone: 'plain', icon: 'arrow-up-right' },
  shrank: { tone: 'plain', icon: 'arrow-right' },
  retyped: { tone: 'hot', icon: 'refresh-cw' },
  reworded: { tone: 'hot', icon: 'pencil' },
  renamed: { tone: 'plain', icon: 'pencil' },
}

function ChangePill({ change }: { change: string }) {
  const c = CHANGE[change] ?? { tone: 'plain' as const, icon: 'circle-dot' as IconName }
  return (
    <Pill tone={c.tone} icon={c.icon}>
      {change.charAt(0).toUpperCase() + change.slice(1)}
    </Pill>
  )
}

function Section({ title, count, children }: { title: string; count?: number; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="flex items-center gap-2 text-[17px] font-semibold text-ink">
        {title}
        {count !== undefined && <span className="font-mono text-[13px] font-normal text-ink-dim">{count}</span>}
      </h2>
      {children}
    </section>
  )
}

/** The instruction a revision is given for a page whose code moved. */
function instructionFor(p: DriftPageAtRisk, to: string | null) {
  return (
    `The code this page describes changed in the newest reading${to ? ` (${shortSha(to)})` : ''}. ` +
    `${p.reason} Files that changed: ${p.changed_files.join(', ')}. ` +
    'Bring the page in line with the code as it is now. Keep what is still true, correct what is not, and do not add claims the code does not support.'
  )
}

function RewriteDialog({
  open,
  onClose,
  projectId,
  drift,
}: {
  open: boolean
  onClose: () => void
  projectId: number
  drift: Drift
}) {
  const { track } = useRunningJobs()
  const [busy, setBusy] = useState(false)
  const [started, setStarted] = useState<number[]>([])
  const [failed, setFailed] = useState<string[]>([])

  const run = async () => {
    setBusy(true)
    const ok: number[] = []
    const bad: string[] = []
    for (const p of drift.pages_at_risk) {
      const [section, ...rest] = p.address.split('/')
      try {
        const job = await api.revisePage(projectId, section, rest.join('/'), {
          instructions: instructionFor(p, drift.to_commit),
        })
        track(job)
        ok.push(job.id)
      } catch (e) {
        bad.push(`${p.title}: ${e instanceof ApiError ? e.message : 'could not start'}`)
      }
    }
    setStarted(ok)
    setFailed(bad)
    setBusy(false)
  }

  return (
    <Dialog open={open} onClose={onClose} title="Rewrite the pages at risk" width={560}>
      {started.length || failed.length ? (
        <div className="flex flex-col gap-3 text-[13.5px] text-ink-mid">
          {started.length > 0 && (
            <p className="flex items-start gap-2">
              <Icon name="circle-check" size={16} className="mt-0.5 text-ok" />
              Started {countLabel(started.length, 'revision')}. They run one after another; the run
              panel in the corner follows them, and each page keeps its previous text until its
              revision is done.
            </p>
          )}
          {failed.map(f => (
            <p key={f} className="flex items-start gap-2 text-bad">
              <Icon name="circle-x" size={16} className="mt-0.5" /> {f}
            </p>
          ))}
          <div className="flex justify-end">
            <Button onClick={onClose}>Close</Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-4 text-[13.5px] leading-relaxed text-ink-mid">
          <p>
            Each of these {countLabel(drift.pages_at_risk.length, 'page')} is revised against the newest
            reading, with what changed under it as the instruction. One model run per page.
          </p>
          <ul className="flex flex-col gap-1">
            {drift.pages_at_risk.map(p => (
              <li key={p.address} className="flex items-center gap-2 text-ink">
                <Icon name="file-text" size={15} className="text-ink-dim" /> {p.title}
              </li>
            ))}
          </ul>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>
              Not now
            </Button>
            <Button variant="hot" onClick={run} disabled={busy}>
              <Icon name="pencil" size={14} /> {busy ? 'Starting…' : `Rewrite ${countLabel(drift.pages_at_risk.length, 'page')}`}
            </Button>
          </div>
        </div>
      )}
    </Dialog>
  )
}

/** What the change means: the pages it puts at risk, the shape, the modules and the facts. */
function Meaning({ projectId, drift: d, onFiles }: { projectId: number; drift: Drift; onFiles: (prefix: string) => void }) {
  if (!d.pages_at_risk.length && !d.services.length && !d.relations.length && !d.modules.length && !d.entities.length)
    return <p className="text-[13px] text-ink-mid">No module, fact or part changed between these readings.</p>
  return (
    <div className="flex flex-col gap-8">
      {d.pages_at_risk.length > 0 && (
        <Section title="Pages that describe code which moved" count={d.pages_at_risk.length}>
          <ul className="flex flex-col">
            {d.pages_at_risk.map(p => (
              <li key={p.address} className="flex flex-col gap-1.5 border-b border-rule px-1 py-3">
                <Link
                  to={`/app/projects/${projectId}/docs/${p.address}`}
                  state={NEW_TAB}
                  className="flex items-center gap-2 text-[14px] font-medium text-ink hover:underline"
                >
                  <Icon name="file-text" size={15} className="text-warn" />
                  {p.title}
                  <span className="font-mono text-[12px] font-normal text-ink-dim">{p.address}</span>
                </Link>
                <p className="text-[13px] leading-relaxed text-ink-mid">{p.reason}</p>
                <div className="flex flex-wrap gap-1.5">
                  {p.changed_files.map(f => (
                    <button
                      key={f}
                      type="button"
                      onClick={() => onFiles(f)}
                      title="Show this file's changes"
                      className="rounded-md border border-rule px-1.5 py-0.5 font-mono text-[11.5px] text-ink-dim transition-colors hover:border-line-2 hover:text-ink"
                    >
                      {f}
                    </button>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {d.architecture_comparable ? (
        (d.services.length > 0 || d.relations.length > 0) && (
          <Section title="Shape" count={d.services.length + d.relations.length}>
            <ul className="flex flex-col">
              {d.services.map(s => (
                <li key={s.name} className="flex flex-wrap items-center gap-3 border-b border-rule px-1 py-2.5">
                  <ChangePill change={s.change} />
                  <Icon name="boxes" size={15} className="text-ink-dim" />
                  <span className="text-[13.5px] font-medium text-ink">{s.name}</span>
                  <span className="text-[12.5px] text-ink-dim">
                    {s.change === 'renamed'
                      ? `was ${s.name_before}`
                      : s.change === 'retyped'
                        ? `${s.type_before || 'untyped'} to ${s.type_after || 'untyped'}`
                        : s.type_after || s.type_before}
                  </span>
                </li>
              ))}
              {d.relations.map(r => (
                <li key={`${r.source}->${r.target}`} className="flex flex-wrap items-center gap-3 border-b border-rule px-1 py-2.5">
                  <ChangePill change={r.change} />
                  <span className="text-[13px] text-ink">{r.source}</span>
                  <Icon name="arrow-right" size={14} className="text-ink-dim" />
                  <span className="text-[13px] text-ink">{r.target}</span>
                  <span className="text-[12.5px] text-ink-dim">
                    {r.change === 'reworded' ? `${r.kind_before} to ${r.kind}` : r.kind || r.kind_before}
                  </span>
                </li>
              ))}
            </ul>
          </Section>
        )
      ) : (
        <p className="max-w-[90ch] text-[13px] text-ink-dim">
          One of these readings has no architecture map, so the shape of the system was not compared. The next pair
          of readings will have two maps to put side by side.
        </p>
      )}

      {d.modules.length > 0 && (
        <Section title="Modules" count={d.modules.length}>
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Change</th>
                  <th>Module</th>
                  <th className="num">Lines before</th>
                  <th className="num">After</th>
                  <th className="num">Difference</th>
                </tr>
              </thead>
              <tbody>
                {d.modules.map(m => (
                  <tr key={m.path}>
                    <td>
                      <ChangePill change={m.change} />
                    </td>
                    <td>
                      <button
                        type="button"
                        onClick={() => onFiles(m.path)}
                        title="Show the changes to its files"
                        className="font-mono text-[12.5px] text-ink transition-colors hover:text-hot-ink"
                      >
                        {m.path}
                      </button>
                    </td>
                    <td className="num font-mono text-[12.5px] text-ink-dim">{m.loc_before}</td>
                    <td className="num font-mono text-[12.5px] text-ink-dim">{m.loc_after}</td>
                    <td className={`num font-mono text-[12.5px] ${m.loc_delta > 0 ? 'text-ok' : m.loc_delta < 0 ? 'text-bad' : 'text-ink-dim'}`}>
                      {m.loc_delta > 0 ? '+' : ''}
                      {m.loc_delta || '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {d.entities.length > 0 && (
        <Section title="Facts" count={d.entities.length}>
          <ul className="flex flex-col">
            {d.entities.map(e => {
              const fk = factKindOf(e.kind)
              return (
                <li key={`${e.kind}:${e.name}`} className="flex flex-wrap items-center gap-3 border-b border-rule px-1 py-2.5">
                  <ChangePill change={e.change} />
                  <Icon name={fk.icon} size={15} style={{ color: fk.color }} />
                  <span className="text-[12.5px] text-ink-dim">{fk.label}</span>
                  <span className="min-w-0 flex-1 truncate font-mono text-[12.5px] text-ink">{e.name}</span>
                  {e.source_path && (
                    <button
                      type="button"
                      onClick={() => onFiles(e.source_path!)}
                      className="font-mono text-[11.5px] text-ink-dim transition-colors hover:text-hot-ink"
                    >
                      {e.source_path}
                    </button>
                  )}
                </li>
              )
            })}
          </ul>
        </Section>
      )}
    </div>
  )
}

/** A reading as a picker shows it: its commit, its date, whether it kept its files. */
function readingLabel(r: Reading) {
  const when = new Date(r.created_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
  return `${shortSha(r.commit)} · ${when}${r.files ? '' : ' · files not kept'}`
}

function ReadingPicker({
  label,
  value,
  readings,
  onChange,
  disabledId,
}: {
  label: string
  value: number | undefined
  readings: Reading[]
  onChange: (id: number) => void
  disabledId?: number
}) {
  return (
    <label className="flex min-w-0 flex-col gap-1">
      <span className="text-[11.5px] font-medium text-ink-dim">{label}</span>
      <select
        className={`${inputClass} font-mono`}
        value={value ?? ''}
        onChange={e => onChange(Number(e.target.value))}
      >
        {readings.map(r => (
          <option key={r.id} value={r.id} disabled={r.id === disabledId}>
            {readingLabel(r)}
          </option>
        ))}
      </select>
    </label>
  )
}

function MissingFiles({
  projectId,
  comparison,
  readings,
  onFetched,
}: {
  projectId: number
  comparison: Comparison
  readings: Reading[]
  onFetched: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const missing = readings.filter(r => comparison.missing.includes(r.id))
  const fetchAll = async () => {
    setBusy(true)
    setError(null)
    try {
      for (const r of missing) {
        const result = await api.fetchReadingFiles(projectId, r.id)
        if (!result.ok) throw new Error(result.reason)
      }
      onFetched()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The files could not be fetched.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="flex max-w-[760px] flex-col gap-3 rounded-xl border border-rule bg-panel p-5">
      <div className="flex items-center gap-3">
        <IconTile icon="history" size={38} />
        <div>
          <h2 className="text-[15px] font-semibold text-ink">Line by line needs the files of both readings</h2>
          <p className="text-[13px] text-ink-mid">
            {missing.map(r => shortSha(r.commit)).join(' and ')} {missing.length === 1 ? 'was' : 'were'} read before
            Codelith kept each reading's files.
          </p>
        </div>
      </div>
      <p className="text-[13px] leading-relaxed text-ink-mid">
        They can be fetched from git at the same commit and kept, without reading the code again: nothing else about
        the reading changes. It takes a few seconds for a small repository.
      </p>
      {error && <ErrorState message={error} compact />}
      <div>
        <Button variant="hot" onClick={() => void fetchAll()} disabled={busy}>
          <Icon name={busy ? 'loader' : 'download'} size={15} className={busy ? 'animate-spin' : ''} />
          {busy ? 'Fetching the files…' : `Fetch the files of ${countLabel(missing.length, 'reading')}`}
        </Button>
      </div>
    </div>
  )
}

export default function DriftPage() {
  const { projectId } = useParams()
  const id = Number(projectId)
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const { can } = useAuth()
  const { track } = useRunningJobs()
  const before = params.get('before') ? Number(params.get('before')) : undefined
  const after = params.get('after') ? Number(params.get('after')) : undefined
  const tab = params.get('tab') === 'meaning' ? 'meaning' : params.get('tab') === 'commits' ? 'commits' : 'files'
  const selected = params.get('file')

  const readings = useAsync<Reading[]>(s => api.readings(id, s), [id])
  const drift = useAsync<Drift>(s => api.drift(id, s, before, after), [id, before, after])
  const comparison = useAsync<Comparison | null>(
    s => ((readings.data?.length ?? 0) > 1 ? api.compare(id, before, after, s) : Promise.resolve(null)),
    [id, before, after, readings.data?.length],
  )
  const project = useAsync(() => api.project(id), [id])
  const [rewriting, setRewriting] = useState(false)
  const [rereading, setRereading] = useState(false)
  const [starting, setStarting] = useState(false)
  const [startError, setStartError] = useState<string | null>(null)

  const setParam = (changes: Record<string, string | null>) =>
    setParams(
      p => {
        const next = new URLSearchParams(p)
        for (const [k, v] of Object.entries(changes)) {
          if (v === null) next.delete(k)
          else next.set(k, v)
        }
        return next
      },
      { replace: true },
    )

  const readAgain = async () => {
    setStarting(true)
    setStartError(null)
    try {
      const job = await api.analyze(id, true)
      track(job, project.data?.name)
      navigate(`/app/projects/${id}/jobs/${job.id}`)
    } catch (e) {
      setStartError(e instanceof ApiError ? e.message : 'Could not start the reading.')
      setStarting(false)
      setRereading(false)
    }
  }

  if (drift.loading || readings.loading)
    return (
      <div className="w-full px-6 py-5">
        <SkeletonPanel rows={6} />
      </div>
    )
  if (drift.error)
    return (
      <div className="w-full px-6 py-5">
        <ErrorState message={drift.error} onRetry={drift.reload} />
      </div>
    )
  const d = drift.data
  if (!d) return null
  const list = readings.data ?? []
  const cmp = comparison.data
  const beforeId = cmp?.before?.id ?? before
  const afterId = cmp?.after?.id ?? after

  return (
    <div className="flex w-full flex-col gap-7 px-6 py-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex items-center gap-3.5">
          <IconTile icon={APP_LOOKS.changes.icon} color={APP_LOOKS.changes.color} tint size={44} />
          <div>
            <h1 className="text-[22px] leading-tight font-semibold text-ink">Changes</h1>
            <p className="mt-1 text-[13px] text-ink-mid">
              {d.comparable ? 'Two readings of the code, compared line by line.' : 'Needs two readings'}
            </p>
          </div>
        </div>
        {d.comparable && list.length > 1 && (
          <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-end gap-2">
            <ReadingPicker
              label="Before"
              value={beforeId}
              readings={list}
              disabledId={afterId}
              onChange={v => setParam({ before: String(v), file: null })}
            />
            <Icon name="arrow-right" size={15} className="mb-2.5 text-ink-dim" />
            <ReadingPicker
              label="After"
              value={afterId}
              readings={list}
              disabledId={beforeId}
              onChange={v => setParam({ after: String(v), file: null })}
            />
          </div>
        )}
      </header>

      {startError && <ErrorState message={startError} compact />}

      {!d.comparable ? (
        <div className="flex max-w-[720px] flex-col gap-4 rounded-xl border border-rule bg-panel p-6">
          <div className="flex items-center gap-3">
            <IconTile icon="git-commit-horizontal" size={40} />
            <div>
              <h2 className="text-[16px] font-semibold text-ink">Only one reading so far</h2>
              <p className="text-[13px] text-ink-mid">{d.summary}</p>
            </div>
          </div>
          <p className="text-[13.5px] leading-relaxed text-ink-mid">
            Changes compares two readings of the same repository: every file that changed, line by line, and what
            each change touches, which parts moved, which facts appeared or went, and which written pages now
            describe code that is no longer there. Read the repository again once its code has moved, and this page
            fills in.
          </p>
          {can('manager') ? (
            <div>
              <Button variant="hot" onClick={() => setRereading(true)} disabled={starting}>
                <Icon name="refresh-cw" size={15} /> Read it again
              </Button>
            </div>
          ) : (
            <p className="text-[12.5px] text-ink-dim">The manager role can start a reading.</p>
          )}
        </div>
      ) : (
        <>
          <section className="flex flex-col gap-4">
            <p className="max-w-[90ch] text-[15px] leading-relaxed text-ink">{d.summary}</p>
            <div className="grid grid-cols-2 gap-x-6 border-y border-rule sm:grid-cols-3 xl:grid-cols-5">
              <StatBlock value={cmp?.available ? cmp.files.length : '-'} label="files changed" icon="file-diff" />
              <StatBlock value={cmp?.available ? `+${cmp.added.toLocaleString()}` : '-'} label="lines added" icon="plus" color={cmp?.available ? 'var(--ok)' : undefined} />
              <StatBlock value={cmp?.available ? `-${cmp.removed.toLocaleString()}` : '-'} label="lines removed" icon="minus" color={cmp?.available ? 'var(--bad)' : undefined} />
              <StatBlock value={d.pages_at_risk.length} label="pages at risk" icon="triangle-alert" color={d.pages_at_risk.length ? 'var(--warn)' : undefined} />
              <StatBlock
                value={d.architecture_comparable ? d.services.length + d.relations.length : '-'}
                label="changes to the shape"
                icon="boxes"
              />
            </div>
          </section>

          <div className="flex flex-wrap items-center gap-3">
            <div className="flex gap-0.5 rounded-lg border border-rule bg-paper p-[3px]" role="tablist" aria-label="What to show">
              {(
                [
                  ['files', 'Files', 'file-diff', cmp?.available ? cmp.files.length : undefined],
                  ['meaning', 'What it means', 'boxes', d.modules.length + d.entities.length + d.pages_at_risk.length],
                  ['commits', 'Commits', 'git-commit-horizontal', undefined],
                ] as const
              ).map(([t, label, icon, count]) => (
                <button
                  key={t}
                  type="button"
                  role="tab"
                  aria-selected={tab === t}
                  onClick={() => setParam({ tab: t === 'files' ? null : t })}
                  className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors ${
                    tab === t ? 'bg-sunk text-ink shadow-[inset_0_0_0_1px_var(--line-2)]' : 'text-ink-mid hover:text-ink'
                  }`}
                >
                  <Icon name={icon} size={14} />
                  {label}
                  {count !== undefined && <span className="font-mono text-[11.5px] text-ink-dim">{count}</span>}
                </button>
              ))}
            </div>
            {d.pages_at_risk.length > 0 && can('manager') && (
              <Button variant="hot" onClick={() => setRewriting(true)} className="ml-auto">
                <Icon name="pencil" size={15} /> Rewrite {countLabel(d.pages_at_risk.length, 'page')}
              </Button>
            )}
          </div>

          {tab === 'files' ? (
            comparison.loading ? (
              <SkeletonPanel rows={8} />
            ) : comparison.error ? (
              <ErrorState message={comparison.error} onRetry={comparison.reload} />
            ) : cmp && !cmp.available ? (
              <MissingFiles
                projectId={id}
                comparison={cmp}
                readings={list}
                onFetched={() => {
                  readings.reload()
                  comparison.reload()
                }}
              />
            ) : cmp && beforeId && afterId ? (
              <FilesChanged
                projectId={id}
                before={beforeId}
                after={afterId}
                files={cmp.files}
                selected={selected}
                onSelect={path => setParam({ file: path })}
                filter={params.get('q') ?? ''}
                onFilter={q => setParam({ q: q || null })}
              />
            ) : null
          ) : tab === 'commits' ? (
            <Commits projectId={id} before={beforeId} after={afterId} onFile={path => setParam({ tab: null, file: path, q: null })} />
          ) : (
            <Meaning projectId={id} drift={d} onFiles={prefix => setParam({ tab: null, file: null, q: prefix })} />
          )}
        </>
      )}

      {d.comparable && <RewriteDialog open={rewriting} onClose={() => setRewriting(false)} projectId={id} drift={d} />}
      <ReanalyseDialog
        open={rereading}
        projectId={id}
        starting={starting}
        onClose={() => setRereading(false)}
        onConfirm={() => void readAgain()}
      />
    </div>
  )
}
