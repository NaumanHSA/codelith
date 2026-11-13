import { useState } from 'react'
import { api, ApiError } from '../../lib/api'
import { relativeTime, shortSha } from '../../lib/format'
import { useAsync } from '../../lib/hooks'
import { Icon } from '../../lib/icons'
import { ErrorState, SkeletonPanel } from '../States'
import { Button } from '../ui'

/* ------------------------------------------------------------------ *
 * The commits between two readings, newest first: what git would list
 * for `before..after`. Each opens to the files it touched, and each
 * file to its diff in the Files tab. A codebase read before commits
 * were kept can fetch its history here.
 * ------------------------------------------------------------------ */

export function Commits({
  projectId,
  before,
  after,
  onFile,
}: {
  projectId: number
  before?: number
  after?: number
  /** A file was picked: show its diff. */
  onFile: (path: string) => void
}) {
  const data = useAsync(s => api.compareCommits(projectId, before, after, s), [projectId, before, after])
  const [open, setOpen] = useState<string | null>(null)
  const [fetching, setFetching] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchHistory = async () => {
    setFetching(true)
    setError(null)
    try {
      const done = await api.fetchHistory(projectId)
      if (!done.ok) setError(done.reason)
      else data.reload()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'The history could not be fetched.')
    } finally {
      setFetching(false)
    }
  }

  if (data.loading) return <SkeletonPanel rows={6} />
  if (data.error) return <ErrorState message={data.error} onRetry={data.reload} />
  const d = data.data
  if (!d) return null

  const fetchPanel = (title: string, body: string) => (
    <div className="flex max-w-[760px] flex-col gap-3 rounded-xl border border-rule bg-panel p-5">
      <div className="flex items-center gap-3">
        <Icon name="git-commit-horizontal" size={20} className="text-ink-dim" />
        <div>
          <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
          <p className="text-[13px] text-ink-mid">{body}</p>
        </div>
      </div>
      {error && <ErrorState message={error} compact />}
      <Button onClick={() => void fetchHistory()} disabled={fetching} className="self-start">
        <Icon name={fetching ? 'loader' : 'download'} size={14} className={fetching ? 'animate-spin' : ''} />
        {fetching ? 'Reading the history…' : 'Fetch the history'}
      </Button>
      <p className="text-[12px] text-ink-dim">
        A local folder is only read. A repository on a host is cloned without file contents into a scratch folder,
        read, and removed. Author names are kept; emails never are.
      </p>
    </div>
  )

  if (!d.known)
    return fetchPanel(
      'No commits are kept for these readings yet',
      'Readings taken from now on keep their commits. For these, fetch the history from the source.',
    )

  return (
    <div className="flex flex-col gap-3">
      {!d.complete && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-line-2 bg-sunk px-3.5 py-2.5">
          <Icon name="info" size={15} className="shrink-0 text-ink-dim" />
          <p className="min-w-0 flex-1 text-[12.5px] text-ink-mid">{d.reason}</p>
          <Button onClick={() => void fetchHistory()} disabled={fetching}>
            <Icon name={fetching ? 'loader' : 'download'} size={14} className={fetching ? 'animate-spin' : ''} />
            Fetch the history
          </Button>
        </div>
      )}
      {error && <ErrorState message={error} compact />}
      {!d.commits.length ? (
        <p className="text-[13px] text-ink-mid">No commits between these two readings: they were read at the same point.</p>
      ) : (
        <ul className="flex flex-col overflow-hidden rounded-xl border border-rule bg-panel">
          {d.commits.map(c => {
            const expanded = open === c.sha
            return (
              <li key={c.sha} className="border-b border-rule last:border-b-0">
                <button
                  type="button"
                  onClick={() => setOpen(expanded ? null : c.sha)}
                  aria-expanded={expanded}
                  className="flex w-full items-start gap-3 px-4 py-2.5 text-left transition-colors hover:bg-hover"
                >
                  <Icon
                    name={c.merge ? 'git-branch' : 'git-commit-horizontal'}
                    size={16}
                    className="mt-0.5 shrink-0 text-ink-dim"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13.5px] text-ink">{c.subject || '(no message)'}</span>
                    <span className="block text-[12px] text-ink-dim">
                      <span className="font-mono">{shortSha(c.sha)}</span> · {c.author || 'someone'}
                      {c.when ? ` · ${relativeTime(c.when)}` : ''}
                      {c.merge ? ' · merge' : ` · ${c.files.length} file${c.files.length === 1 ? '' : 's'}`}
                    </span>
                  </span>
                  {!c.merge && c.files.length > 0 && (
                    <Icon name={expanded ? 'chevron-down' : 'chevron-right'} size={15} className="mt-0.5 text-ink-dim" />
                  )}
                </button>
                {expanded && c.files.length > 0 && (
                  <ul className="flex flex-col pb-2 pl-11">
                    {c.files.slice(0, 60).map(f => (
                      <li key={f}>
                        <button
                          type="button"
                          onClick={() => onFile(f)}
                          className="w-full truncate rounded-md px-2 py-1 text-left font-mono text-[12px] text-ink-mid transition-colors hover:bg-hover hover:text-ink"
                          title="Its diff between the two readings"
                        >
                          {f}
                        </button>
                      </li>
                    ))}
                    {c.files.length > 60 && <li className="px-2 py-1 text-[12px] text-ink-dim">and {c.files.length - 60} more</li>}
                  </ul>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
