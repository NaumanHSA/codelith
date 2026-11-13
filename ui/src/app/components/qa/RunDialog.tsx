import { useEffect, useState } from 'react'
import { api, ApiError } from '../../lib/api'
import { shortSha } from '../../lib/format'
import { useAsync } from '../../lib/hooks'
import { Icon } from '../../lib/icons'
import type { QACatalog, QARun } from '../../lib/types'
import { ErrorState, SkeletonPanel } from '../States'
import { Button, Dialog, inputClass } from '../ui'
import { areaIcon } from './look'

/* ------------------------------------------------------------------ *
 * What to check, how deep, and how much of the code. Depths that have
 * not been built are shown and say when they arrive, rather than being
 * hidden: the picker is also the honest list of what QA can do today.
 * ------------------------------------------------------------------ */

type ScopeKind = 'all' | 'paths' | 'since'

export function RunDialog({
  open,
  onClose,
  projectId,
  catalog,
  initial,
  onStarted,
}: {
  open: boolean
  onClose: () => void
  projectId: number
  catalog: QACatalog
  /** The areas to start from: the last run's, or all of them. */
  initial: string[]
  onStarted: (run: QARun) => void
}) {
  const [areas, setAreas] = useState<string[]>(initial)
  const [depth, setDepth] = useState('quick')
  const [scope, setScope] = useState<ScopeKind>('all')
  const [paths, setPaths] = useState('')
  const [since, setSince] = useState<number | null>(null)
  const [online, setOnline] = useState(false)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const readings = useAsync(s => (open && scope === 'since' ? api.readings(projectId, s) : Promise.resolve(null)), [projectId, open, scope])
  const docker = useAsync(s => (open && depth === 'tests' ? api.qaSandbox(projectId, s) : Promise.resolve(null)), [projectId, open, depth])
  const testsAsked = areas.includes('tests') || areas.includes('breaks')

  useEffect(() => {
    if (open) {
      setAreas(initial)
      setError(null)
    }
  }, [open, initial])

  const older = (readings.data ?? []).slice(1)
  useEffect(() => {
    if (scope === 'since' && since === null && older.length) setSince(older[0].id)
  }, [scope, since, older])

  const toggle = (id: string) => setAreas(a => (a.includes(id) ? a.filter(x => x !== id) : [...a, id]))
  const pathList = paths.split(/[\n,]/).map(p => p.trim()).filter(Boolean)
  const ready = areas.length > 0 && (scope !== 'paths' || pathList.length > 0) && (scope !== 'since' || since !== null)

  const start = async () => {
    setStarting(true)
    setError(null)
    try {
      const run = await api.qaStart(projectId, {
        areas,
        depth,
        online: online && areas.includes('dependencies'),
        scope: scope === 'all' ? { kind: 'all' } : scope === 'paths' ? { kind: 'paths', paths: pathList } : { kind: 'since', kb_id: since! },
      })
      onStarted(run)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'The check could not be started.')
    } finally {
      setStarting(false)
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title="Run a check" width={720} bodyClass="px-5 py-4">
      <div className="flex flex-col gap-5">
        <section className="flex flex-col gap-2">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-[13px] font-semibold text-ink">What to look for</h3>
            <div className="flex gap-3 text-[12px]">
              <button type="button" className="text-ink-mid hover:text-hot-ink" onClick={() => setAreas(catalog.areas.map(a => a.id))}>
                All
              </button>
              <button type="button" className="text-ink-mid hover:text-hot-ink" onClick={() => setAreas([])}>
                None
              </button>
            </div>
          </div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {catalog.areas.map(a => {
              const on = areas.includes(a.id)
              return (
                <button
                  key={a.id}
                  type="button"
                  role="checkbox"
                  aria-checked={on}
                  onClick={() => toggle(a.id)}
                  title={a.looks_for.join(' · ')}
                  className={`flex items-start gap-3 rounded-lg border px-3 py-2.5 text-left transition-colors ${
                    on ? 'border-hot-edge bg-hot-wash' : 'border-rule hover:bg-hover'
                  }`}
                >
                  <span
                    className={`mt-0.5 grid size-[18px] shrink-0 place-items-center rounded border ${
                      on ? 'border-hot bg-hot text-on-hot' : 'border-line-2'
                    }`}
                  >
                    {on && <Icon name="check" size={12} strokeWidth={3} />}
                  </span>
                  <span className="min-w-0">
                    <span className="flex items-center gap-1.5 text-[13px] font-medium text-ink">
                      <Icon name={areaIcon(a.icon)} size={14} className="text-ink-dim" />
                      {a.label}
                    </span>
                    <span className="mt-0.5 block text-[12px] leading-snug text-ink-mid">{a.blurb}</span>
                  </span>
                </button>
              )
            })}
          </div>
        </section>

        <section className="flex flex-col gap-2">
          <h3 className="text-[13px] font-semibold text-ink">How deep</h3>
          <div className="flex flex-col gap-1.5">
            {catalog.depths.map(d => (
              <label
                key={d.id}
                className={`flex items-start gap-3 rounded-lg border px-3 py-2 ${
                  !d.available ? 'cursor-not-allowed border-rule opacity-60' : depth === d.id ? 'border-hot-edge bg-hot-wash' : 'border-rule hover:bg-hover'
                }`}
              >
                <input
                  type="radio"
                  name="qa-depth"
                  className="mt-1 accent-[var(--hot)]"
                  checked={depth === d.id}
                  disabled={!d.available}
                  onChange={() => setDepth(d.id)}
                />
                <span className="min-w-0">
                  <span className="text-[13px] font-medium text-ink">{d.label}</span>
                  <span className="block text-[12px] leading-snug text-ink-mid">{d.available ? d.blurb : `${d.blurb} ${d.why_not}`}</span>
                </span>
              </label>
            ))}
          </div>
          {depth === 'tests' && (
            <p className="flex items-start gap-1.5 text-[12px] leading-snug text-ink-mid">
              {docker.loading ? (
                <>
                  <Icon name="loader" size={13} className="mt-0.5 shrink-0 animate-spin" /> Asking Docker…
                </>
              ) : docker.data && !docker.data.ready ? (
                <>
                  <Icon name="octagon-alert" size={13} className="mt-0.5 shrink-0 text-hot-ink" />
                  <span>{docker.data.reason} Until then a run does everything else and says the tests did not run.</span>
                </>
              ) : !testsAsked ? (
                <>
                  <Icon name="octagon-alert" size={13} className="mt-0.5 shrink-0 text-hot-ink" />
                  <span>The tests run when Tests or Things that will break is among the areas.</span>
                </>
              ) : docker.data?.ready ? (
                <>
                  <Icon name="box" size={13} className="mt-0.5 shrink-0" />
                  <span>
                    Docker is running. The install gets the network to fetch packages; the tests and tools get none,
                    and no key or setting of yours goes into either container.
                  </span>
                </>
              ) : null}
            </p>
          )}
        </section>

        <section className="flex flex-col gap-2">
          <h3 className="text-[13px] font-semibold text-ink">How much of the code</h3>
          <div className="flex flex-wrap gap-2">
            {(
              [
                ['all', 'The whole codebase'],
                ['paths', 'Some folders or files'],
                ['since', 'What changed since a reading'],
              ] as const
            ).map(([k, label]) => (
              <button
                key={k}
                type="button"
                aria-pressed={scope === k}
                onClick={() => setScope(k)}
                className={`rounded-full border px-3 py-1 text-[12.5px] transition-colors ${
                  scope === k ? 'border-hot-edge bg-hot-wash text-hot-ink' : 'border-line-2 text-ink-mid hover:text-ink'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          {scope === 'paths' && (
            <textarea
              className={`${inputClass} min-h-[64px] font-mono`}
              placeholder={'app/api\napp/services/billing.py'}
              value={paths}
              onChange={e => setPaths(e.target.value)}
              aria-label="Folders or files to check, one per line"
            />
          )}
          {scope === 'since' &&
            (readings.loading ? (
              <SkeletonPanel rows={1} />
            ) : older.length ? (
              <select className={`${inputClass} font-mono`} value={since ?? ''} onChange={e => setSince(Number(e.target.value))}>
                {older.map(r => (
                  <option key={r.id} value={r.id}>
                    {shortSha(r.commit)} · {new Date(r.created_at).toLocaleDateString()}
                  </option>
                ))}
              </select>
            ) : (
              <p className="text-[12.5px] text-ink-dim">This codebase has been read once: there is nothing to compare with yet.</p>
            ))}
        </section>

        <label
          className={`flex items-start gap-3 rounded-lg border px-3 py-2.5 ${
            catalog.online_available && areas.includes('dependencies')
              ? online
                ? 'cursor-pointer border-hot-edge bg-hot-wash'
                : 'cursor-pointer border-rule hover:bg-hover'
              : 'cursor-not-allowed border-rule bg-sunk opacity-60'
          }`}
        >
          <input
            type="checkbox"
            className="mt-1 accent-[var(--hot)]"
            checked={online && areas.includes('dependencies')}
            disabled={!catalog.online_available || !areas.includes('dependencies')}
            onChange={e => setOnline(e.target.checked)}
          />
          <span className="min-w-0 text-[12.5px] leading-snug text-ink-mid">
            <span className="flex items-center gap-1.5 font-medium text-ink">
              <Icon name="globe" size={14} /> Also check dependencies online
            </span>
            Sends package names and versions to OSV.dev (known vulnerabilities), and package names to PyPI, the npm
            registry and the Go proxy (latest versions and licences). No code, no file names. Off unless you tick it;
            {areas.includes('dependencies') ? ' nothing else in a run leaves this machine.' : ' needs Dependencies & compatibility.'}
          </span>
        </label>

        {error && <ErrorState message={error} compact />}

        <div className="flex items-center justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="hot" onClick={() => void start()} disabled={!ready || starting}>
            <Icon name={starting ? 'loader' : 'play'} size={14} className={starting ? 'animate-spin' : ''} />
            {starting ? 'Starting…' : `Check ${areas.length} area${areas.length === 1 ? '' : 's'}`}
          </Button>
        </div>
      </div>
    </Dialog>
  )
}
