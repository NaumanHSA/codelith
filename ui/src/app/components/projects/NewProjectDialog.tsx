import { useState } from 'react'
import { api, ApiError } from '../../lib/api'
import { countLabel, languageShares, shortSha } from '../../lib/format'
import type { ProbeResult, Project, SourceType } from '../../lib/types'
import { Button, Chip, Dialog, Field, inputClass } from '../../components/ui'
import { ErrorState } from '../../components/States'

/* ------------------------------------------------------------------ *
 * Probe before create.
 *
 * The previous version created the project first and swallowed source
 * errors, leaving empty projects behind whenever a URL was wrong. This
 * inspects the repository first, shows what was found, and only then
 * writes anything — via /projects/with-source, which is atomic.
 * ------------------------------------------------------------------ */

const SOURCE_TYPES: { value: SourceType; label: string }[] = [
  { value: 'github', label: 'GitHub' },
  { value: 'gitlab', label: 'GitLab' },
  { value: 'bitbucket', label: 'Bitbucket' },
  { value: 'local', label: 'Local path' },
]

/** "https://github.com/acme/neurosurfer.git" → "neurosurfer" */
function nameFromUrl(url: string): string {
  const cleaned = url.trim().replace(/\.git$/, '').replace(/\/+$/, '')
  const last = cleaned.split(/[/\\]/).filter(Boolean).pop() ?? ''
  return last.replace(/[-_]+/g, ' ').trim() || ''
}

export default function NewProjectDialog({
  open, onClose, onCreated,
}: {
  open: boolean
  onClose: () => void
  onCreated: (p: Project) => void
}) {
  const [sourceType, setSourceType] = useState<SourceType>('github')
  const [url, setUrl] = useState('')
  const [branch, setBranch] = useState('')
  const [name, setName] = useState('')
  const [nameTouched, setNameTouched] = useState(false)

  const [probe, setProbe] = useState<ProbeResult | null>(null)
  const [probing, setProbing] = useState(false)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const reset = () => {
    setUrl('')
    setBranch('')
    setName('')
    setNameTouched(false)
    setProbe(null)
    setError(null)
    setProbing(false)
    setCreating(false)
  }

  const close = () => {
    reset()
    onClose()
  }

  const onUrlChange = (v: string) => {
    setUrl(v)
    setProbe(null)
    setError(null)
    if (!nameTouched) setName(nameFromUrl(v))
  }

  const runProbe = async () => {
    if (!url.trim()) return
    setProbing(true)
    setError(null)
    setProbe(null)
    try {
      const result = await api.probe({
        source_type: sourceType,
        url_or_path: url.trim(),
        branch: branch.trim() || null,
      })
      // ok:false still arrives as HTTP 200 — the error text is written
      // for users, so show it verbatim.
      setProbe(result)
      if (!nameTouched && result.ok) setName(prev => prev || nameFromUrl(result.url_or_path))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not reach the repository.')
    } finally {
      setProbing(false)
    }
  }

  const create = async () => {
    if (!probe?.ok || !name.trim()) return
    setCreating(true)
    setError(null)
    try {
      const project = await api.createProjectWithSource({
        name: name.trim(),
        description: null,
        source_type: sourceType,
        url_or_path: url.trim(),
        branch: branch.trim() || null,
      })
      onCreated(project)
      reset()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not create the project.')
    } finally {
      setCreating(false)
    }
  }

  const shares = languageShares(probe?.languages)

  return (
    <Dialog open={open} onClose={close} title="New project" width={560}>
      <div className="flex flex-col gap-3">
        {error && <ErrorState message={error} compact />}

        <div>
          <span className="tag mb-1.5 block text-ink-dim">Source</span>
          <div className="flex flex-wrap gap-1.5">
            {SOURCE_TYPES.map(s => (
              <Chip
                key={s.value}
                active={sourceType === s.value}
                onClick={() => {
                  setSourceType(s.value)
                  setProbe(null)
                }}
              >
                {s.label}
              </Chip>
            ))}
          </div>
        </div>

        <Field
          label={sourceType === 'local' ? 'Absolute path' : 'Repository URL'}
          help={
            sourceType === 'local'
              ? 'A directory on this machine.'
              : 'Public repositories work out of the box.'
          }
        >
          <input
            value={url}
            onChange={e => onUrlChange(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') {
                e.preventDefault()
                runProbe()
              }
            }}
            placeholder={
              sourceType === 'local' ? '/Users/ada/src/neurosurfer' : 'https://github.com/org/repo'
            }
            className={inputClass}
          />
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Branch" help="Blank uses the default.">
            <input
              value={branch}
              onChange={e => {
                setBranch(e.target.value)
                setProbe(null)
              }}
              placeholder="main"
              className={inputClass}
            />
          </Field>
          <Field label="Project name">
            <input
              value={name}
              onChange={e => {
                setName(e.target.value)
                setNameTouched(true)
              }}
              placeholder="neurosurfer"
              className={inputClass}
            />
          </Field>
        </div>

        <Button variant="ghost" onClick={runProbe} disabled={!url.trim() || probing}>
          {probing ? (
            <>
              <span className="anim-spin block size-[9px] rounded-full border border-hot border-t-transparent" />
              checking the repository…
            </>
          ) : (
            '↻ Check the repository'
          )}
        </Button>

        {/* probe report */}
        {probe && !probe.ok && (
          <div className="border border-bad/35 bg-bad-wash px-3 py-2.5">
            <span className="tag flex items-center gap-1.5 text-bad">
              <span className="block size-[6px] rotate-45 bg-bad" /> Cannot use this source
            </span>
            <p className="mt-1.5 font-sans text-[12.5px] leading-relaxed text-ink">
              {probe.error ?? 'The repository could not be read.'}
            </p>
          </div>
        )}

        {probe?.ok && (
          <div className="anim-rise border border-ok/35 bg-ok-wash">
            <div className="tag flex items-center gap-2 border-b border-ok/25 px-3 py-2 text-ok">
              <span className="block size-[6px] rotate-45 bg-ok" />
              Repository looks good
              <span className="ml-auto normal-case text-ink-dim">
                {probe.branch ?? 'default'} · {shortSha(probe.commit_sha)}
              </span>
            </div>
            <div className="grid grid-cols-2 gap-px bg-ok/15 sm:grid-cols-3">
              {[
                ['files', probe.file_count?.toLocaleString() ?? '—'],
                ['analysable', probe.analysable_files?.toLocaleString() ?? '—'],
                ['languages', String(shares.length || '—')],
              ].map(([k, v]) => (
                <div key={k} className="bg-ok-wash px-2.5 py-2">
                  <div className="tag mb-1 text-ink-dim">{k}</div>
                  <div className="text-[14px] leading-none font-bold text-ink">{v}</div>
                </div>
              ))}
            </div>
            {shares.length > 0 && (
              <div className="border-t border-ok/25 px-3 py-2.5">
                <div className="flex h-[7px] w-full overflow-hidden border border-ink/10">
                  {shares.slice(0, 6).map((l, i) => (
                    <span
                      key={l.name}
                      title={`${l.name} · ${countLabel(l.count, 'file')}`}
                      style={{ width: `${l.pct}%`, opacity: 1 - i * 0.13 }}
                      className="block bg-hot"
                    />
                  ))}
                </div>
                <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
                  {shares.slice(0, 5).map(l => (
                    <span key={l.name} className="tag text-ink-mid">
                      {l.name} {Math.round(l.pct)}%
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      <footer className="flex items-center gap-2 border-t border-rule bg-sunk/60 px-3 py-2.5">
        <span className="tag text-ink-dim">
          {probe?.ok ? 'nothing is written until you create' : 'check the source first'}
        </span>
        <div className="ml-auto flex gap-2">
          <Button variant="ghost" onClick={close}>
            Cancel
          </Button>
          <Button variant="hot" onClick={create} disabled={!probe?.ok || !name.trim() || creating}>
            {creating ? (
              <>
                <span className="anim-spin block size-[9px] rounded-full border border-current border-t-transparent" />
                creating…
              </>
            ) : (
              'Create project →'
            )}
          </Button>
        </div>
      </footer>
    </Dialog>
  )
}
