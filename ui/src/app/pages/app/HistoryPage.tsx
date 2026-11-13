import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import CodeView from '../../components/projects/CodeView'
import { IconTile, Pill } from '../../components/primitives'
import { ErrorState, SkeletonPanel } from '../../components/States'
import { Button, Dialog, inputClass } from '../../components/ui'
import { api, ApiError } from '../../lib/api'
import { countLabel, formatDateTime, relativeTime, shortSha } from '../../lib/format'
import { useAsync } from '../../lib/hooks'
import { Icon } from '../../lib/icons'
import type { HistoryStep, Reading } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * Every reading of a codebase, newest first, each against the one
 * before it: what changed, in which parts, and the commits between.
 * From each: compare it with any other, or browse its files as they
 * were. `?file=` narrows it to one file's own history.
 * ------------------------------------------------------------------ */

const CHANGED_ORDER = ['added', 'modified', 'renamed', 'removed']

function Browse({ projectId, reading, path, onClose }: { projectId: number; reading: Reading; path: string | null; onClose: () => void }) {
  const tree = useAsync(s => api.files(projectId, s, reading.id), [projectId, reading.id])
  const [q, setQ] = useState('')
  const [picked, setPicked] = useState<string | null>(path)
  const file = useAsync(s => (picked ? api.file(projectId, picked, s, reading.id) : Promise.resolve(null)), [projectId, picked, reading.id])
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return (tree.data?.files ?? []).filter(f => f.has_source && (!needle || f.path.toLowerCase().includes(needle)))
  }, [tree.data, q])
  return (
    <Dialog open onClose={onClose} title={`The files at ${shortSha(reading.commit)}`} width={1200} bodyClass="px-5 py-4">
      <div className="grid h-[70vh] grid-cols-1 gap-4 md:grid-cols-[minmax(240px,320px)_minmax(0,1fr)]">
        <div className="flex min-h-0 flex-col gap-2">
          <input className={inputClass} placeholder={`Filter ${shown.length} files`} value={q} onChange={e => setQ(e.target.value)} aria-label="Filter the files" />
          <div className="min-h-0 flex-1 overflow-y-auto rounded-lg border border-rule">
            {tree.loading ? (
              <SkeletonPanel rows={8} />
            ) : tree.error ? (
              <ErrorState message={tree.error} onRetry={tree.reload} compact />
            ) : (
              shown.slice(0, 800).map(f => (
                <button
                  key={f.path}
                  type="button"
                  aria-current={picked === f.path}
                  onClick={() => setPicked(f.path)}
                  className={`block w-full truncate px-3 py-1.5 text-left font-mono text-[12px] transition-colors ${
                    picked === f.path ? 'bg-hot-wash text-ink' : 'text-ink-mid hover:bg-hover hover:text-ink'
                  }`}
                  title={f.path}
                >
                  {f.path}
                </button>
              ))
            )}
          </div>
        </div>
        <div className="min-h-0 min-w-0">
          {!picked ? (
            <p className="text-[13px] text-ink-mid">Pick a file to read it as it was at this reading.</p>
          ) : file.loading ? (
            <SkeletonPanel rows={10} />
          ) : file.error ? (
            <ErrorState message={file.error} onRetry={file.reload} />
          ) : file.data ? (
            <CodeView file={file.data} range={null} onPickLine={() => undefined} fill />
          ) : null}
        </div>
      </div>
    </Dialog>
  )
}

function StepRow({
  projectId,
  step,
  latest,
  readings,
  onBrowse,
  onFetched,
}: {
  projectId: number
  step: HistoryStep
  latest: boolean
  readings: Reading[]
  onBrowse: () => void
  onFetched: () => void
}) {
  const navigate = useNavigate()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const r = step.reading
  const files = Object.values(step.changed).reduce((a, b) => a + b, 0)
  const fetchFiles = async () => {
    setBusy(true)
    setError(null)
    try {
      const done = await api.fetchReadingFiles(projectId, r.id)
      if (!done.ok) setError(done.reason)
      else onFetched()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'The files could not be fetched.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <li className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 border-b border-rule px-4 py-3.5 last:border-b-0">
      <span className="mt-1 flex flex-col items-center">
        <span className={`size-2.5 rounded-full ${latest ? 'bg-hot' : 'bg-ink-dim'}`} />
      </span>
      <div className="flex min-w-0 flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-[13.5px] font-medium text-ink">{shortSha(r.commit)}</span>
          <span className="text-[12.5px] text-ink-dim" title={formatDateTime(r.created_at)}>
            read {relativeTime(r.created_at)}
          </span>
          {latest && <Pill tone="hot">Latest</Pill>}
          {r.status === 'degraded' && <Pill tone="warn">Partly read</Pill>}
          <span className="text-[12.5px] text-ink-dim">{r.files ? `${r.files.toLocaleString()} files kept` : 'files not kept'}</span>
        </div>

        {step.previous === null ? (
          <p className="text-[12.5px] text-ink-mid">The first reading kept.</p>
        ) : step.missing.length ? (
          <p className="text-[12.5px] text-ink-mid">
            No line counts: {step.missing.includes(r.id) ? 'this reading' : 'the one before'} was taken before Codelith kept
            each reading&apos;s files.
          </p>
        ) : (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[12.5px] text-ink-mid">
            <span>
              {countLabel(files, 'file')} changed
              {files > 0 &&
                ` (${CHANGED_ORDER.filter(k => step.changed[k])
                  .map(k => `${step.changed[k]} ${k}`)
                  .join(', ')})`}
            </span>
            <span className="font-mono">
              <span className="text-ok">+{step.added.toLocaleString()}</span>{' '}
              <span className="text-bad">−{step.removed.toLocaleString()}</span>
            </span>
            {step.commits !== null && (
              <span>
                {step.commits}
                {step.commits_complete ? '' : '+'} commit{step.commits === 1 ? '' : 's'} between
              </span>
            )}
            {step.parts.map(p => (
              <span key={p} className="rounded-full border border-line-2 px-2 py-0.5 text-[11.5px] text-ink-mid">
                {p}
              </span>
            ))}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2">
          {step.previous !== null && (
            <Link
              to={`/app/projects/${projectId}/drift?before=${step.previous}&after=${r.id}`}
              className="inline-flex items-center gap-1.5 rounded-md border border-line-2 px-2.5 py-1 text-[12.5px] text-ink transition-colors hover:bg-hover"
            >
              <Icon name="file-diff" size={13} /> Compare with the one before
            </Link>
          )}
          {readings.length > 2 && (
            <select
              className={`${inputClass} h-[28px] max-w-[220px] py-0 text-[12.5px]`}
              value=""
              aria-label="Compare with another reading"
              onChange={e => {
                const other = Number(e.target.value)
                const [b, a] = other < r.id ? [other, r.id] : [r.id, other]
                navigate(`/app/projects/${projectId}/drift?before=${b}&after=${a}`)
              }}
            >
              <option value="">Compare with…</option>
              {readings
                .filter(o => o.id !== r.id)
                .map(o => (
                  <option key={o.id} value={o.id}>
                    {shortSha(o.commit)} · {new Date(o.created_at).toLocaleDateString()}
                  </option>
                ))}
            </select>
          )}
          {r.files > 0 ? (
            <button
              type="button"
              onClick={onBrowse}
              className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[12.5px] text-ink-mid transition-colors hover:bg-hover hover:text-ink"
            >
              <Icon name="folder-open" size={13} /> Browse its files
            </button>
          ) : (
            <button
              type="button"
              onClick={() => void fetchFiles()}
              disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[12.5px] text-ink-mid transition-colors hover:bg-hover hover:text-ink disabled:opacity-60"
              title="Fetch this reading's files from git: a blobless clone, or git archive for a local folder"
            >
              <Icon name={busy ? 'loader' : 'download'} size={13} className={busy ? 'animate-spin' : ''} /> Fetch its files
            </button>
          )}
        </div>
        {error && <ErrorState message={error} compact />}
      </div>
    </li>
  )
}

function FileHistory({ projectId, path, onBrowse, onClear }: { projectId: number; path: string; onBrowse: (r: Reading) => void; onClear: () => void }) {
  const data = useAsync(s => api.fileHistory(projectId, path, s), [projectId, path])
  return (
    <section className="flex flex-col gap-3 rounded-xl border border-rule bg-panel p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Icon name="file-code" size={16} className="text-ink-dim" />
        <h2 className="min-w-0 truncate font-mono text-[14px] font-medium text-ink">{path}</h2>
        <button type="button" onClick={onClear} className="ml-auto text-[12.5px] text-ink-mid hover:text-ink">
          Every reading
        </button>
      </div>
      {data.loading ? (
        <SkeletonPanel rows={3} />
      ) : data.error ? (
        <ErrorState message={data.error} onRetry={data.reload} compact />
      ) : !data.data?.length ? (
        <p className="text-[13px] text-ink-mid">No kept reading has this file.</p>
      ) : (
        <ul className="flex flex-col">
          {data.data.map(s => (
            <li key={s.reading.id} className="flex flex-wrap items-center gap-3 border-t border-rule py-2 first:border-t-0">
              <Pill tone={s.status === 'removed' ? 'bad' : s.status === 'added' ? 'good' : 'plain'}>{s.status}</Pill>
              <span className="font-mono text-[12.5px] text-ink">{shortSha(s.reading.commit)}</span>
              <span className="text-[12.5px] text-ink-dim">{relativeTime(s.reading.created_at)}</span>
              <span className="ml-auto flex items-center gap-1">
                {s.previous !== null && (
                  <Link
                    to={`/app/projects/${projectId}/drift?before=${s.previous}&after=${s.reading.id}&file=${encodeURIComponent(path)}`}
                    className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[12.5px] text-ink-mid transition-colors hover:bg-hover hover:text-ink"
                  >
                    <Icon name="file-diff" size={13} /> See the change
                  </Link>
                )}
                {s.status !== 'removed' && (
                  <button
                    type="button"
                    onClick={() => onBrowse(s.reading)}
                    className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[12.5px] text-ink-mid transition-colors hover:bg-hover hover:text-ink"
                  >
                    <Icon name="eye" size={13} /> As it was
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export default function HistoryPage() {
  const { projectId } = useParams()
  const id = Number(projectId)
  const [params, setParams] = useSearchParams()
  const steps = useAsync(s => api.history(id, s), [id])
  const project = useAsync(() => api.project(id), [id])
  const [browsing, setBrowsing] = useState<{ reading: Reading; path: string | null } | null>(null)
  const [fetching, setFetching] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const file = params.get('file')

  const fetchHistory = async () => {
    setFetching(true)
    setNote(null)
    try {
      const done = await api.fetchHistory(id)
      setNote(done.ok ? `${countLabel(done.commits, 'commit')} read, ${done.new} new.` : done.reason)
      if (done.ok) steps.reload()
    } catch (e) {
      setNote(e instanceof ApiError ? e.message : 'The history could not be fetched.')
    } finally {
      setFetching(false)
    }
  }

  if (steps.loading)
    return (
      <div className="w-full px-6 py-5">
        <SkeletonPanel rows={8} />
      </div>
    )
  if (steps.error)
    return (
      <div className="w-full px-6 py-5">
        <ErrorState message={steps.error} onRetry={steps.reload} />
      </div>
    )
  const list = steps.data ?? []
  const readings = list.map(s => s.reading)
  const noCommits = list.length > 1 && list.every(s => s.commits === null)

  return (
    <div className="flex w-full flex-col gap-6 px-6 py-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex items-center gap-3.5">
          <IconTile icon="history" size={44} tint />
          <div>
            <h1 className="text-[22px] leading-tight font-semibold text-ink">History</h1>
            <p className="mt-1 text-[13px] text-ink-mid">
              {countLabel(list.length, 'reading')} of {project.data?.name ?? 'this codebase'}, each against the one before it.
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => void fetchHistory()} disabled={fetching} title="Read the commits from the source, for readings taken before commits were kept">
            <Icon name={fetching ? 'loader' : 'git-commit-horizontal'} size={14} className={fetching ? 'animate-spin' : ''} />
            {noCommits ? 'Fetch the commits' : 'Refresh the commits'}
          </Button>
        </div>
      </header>
      {note && <p className="text-[12.5px] text-ink-mid">{note}</p>}

      {file && (
        <FileHistory
          projectId={id}
          path={file}
          onBrowse={r => setBrowsing({ reading: r, path: file })}
          onClear={() => setParams(p => {
            const next = new URLSearchParams(p)
            next.delete('file')
            return next
          })}
        />
      )}

      {!list.length ? (
        <p className="text-[13px] text-ink-mid">This codebase has not been read yet.</p>
      ) : (
        <ul className="flex flex-col overflow-hidden rounded-xl border border-rule bg-panel">
          {list.map((s, k) => (
            <StepRow
              key={s.reading.id}
              projectId={id}
              step={s}
              latest={k === 0}
              readings={readings}
              onBrowse={() => setBrowsing({ reading: s.reading, path: null })}
              onFetched={steps.reload}
            />
          ))}
        </ul>
      )}

      {browsing && <Browse projectId={id} reading={browsing.reading} path={browsing.path} onClose={() => setBrowsing(null)} />}
    </div>
  )
}
