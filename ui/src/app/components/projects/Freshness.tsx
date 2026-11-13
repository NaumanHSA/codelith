import { useState } from 'react'
import { useAuth } from '../../auth'
import { api, ApiError } from '../../lib/api'
import { shortSha } from '../../lib/format'
import { useAsync } from '../../lib/hooks'
import type { Project, ProjectSource } from '../../lib/types'
import { Pill } from '../primitives'

/* ------------------------------------------------------------------ *
 * How current the knowledge is. Shown wherever the knowledge is shown —
 * the codebase page and the knowledge graph — because a map of the code
 * as it was is accurate and still misleading if nothing says so.
 *
 * The check asks where the repository is now (no clone: `git ls-remote`
 * or `rev-parse`) and, for a folder on this machine, how many commits
 * have landed since the reading. Managers only on the server; everyone
 * else sees what the stored status says.
 * ------------------------------------------------------------------ */

export function Freshness({ projectId, project, sha }: { projectId: number; project?: Project; sha: string | null }) {
  const { can } = useAuth()
  const manager = can('manager')
  const preview = useAsync(
    sig => (manager ? api.analysisPreview(projectId, sig) : Promise.resolve(null)),
    [projectId, manager, sha],
  )
  if (manager && preview.loading) return <span className="skel block h-6 w-40 rounded-full" />
  const p = preview.data
  if (p?.checked && !p.never_analysed)
    return p.changed ? (
      <Pill tone="warn" icon="git-compare-arrows" title={p.summary}>
        {p.behind
          ? `${p.behind} commit${p.behind === 1 ? '' : 's'} since ${shortSha(p.analysed_commit)}`
          : `The code has moved since ${shortSha(p.analysed_commit)}`}
      </Pill>
    ) : (
      <Pill tone="good" icon="check" title={p.summary}>
        Read at the latest commit
      </Pill>
    )
  if (project?.kb_status === 'stale')
    return (
      <Pill tone="warn" icon="clock">
        Reading is stale
      </Pill>
    )
  return (
    <Pill icon="git-commit-horizontal" title={p?.reason ?? undefined}>
      Read at {shortSha(sha)}
    </Pill>
  )
}

/**
 * "Read every commit", for a folder on this machine: the server checks it every few
 * seconds and reads the changes after each commit (`services/auto_read.py`). A hosted
 * repository has no working copy here to check, so the switch is not offered for one.
 */
export function AutoReadSwitch({ projectId, source }: { projectId: number; source: ProjectSource }) {
  const [on, setOn] = useState(Boolean(source.config_json?.auto_read?.on))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const flip = async () => {
    setBusy(true)
    setError(null)
    try {
      const state = await api.setAutoRead(projectId, !on)
      setOn(state.on)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not change it.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={() => void flip()}
      disabled={busy}
      title={
        error ??
        (on
          ? 'Every commit to this folder is read again a few seconds after it is made. Click to stop.'
          : 'Read this codebase again after every commit to the folder, by itself. Only the changes are read.')
      }
      className="inline-flex h-6 items-center gap-2 rounded-full border border-rule px-2 text-[12px] font-medium text-ink-mid transition-colors hover:border-line-2 hover:text-ink disabled:opacity-60"
    >
      <span
        className={`relative h-[14px] w-[24px] rounded-full transition-colors ${on ? 'bg-hot' : 'bg-line-2'}`}
        aria-hidden
      >
        <span
          className={`absolute top-[2px] size-[10px] rounded-full bg-ink transition-[left] ${on ? 'left-[12px]' : 'left-[2px]'}`}
        />
      </span>
      {error ? <span className="text-bad">Could not change</span> : 'Read every commit'}
    </button>
  )
}
