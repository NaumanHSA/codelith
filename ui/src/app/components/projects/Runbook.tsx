import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../lib/api'
import { languageBrand } from '../../lib/brands'
import { useAsync } from '../../lib/hooks'
import { Icon } from '../../lib/icons'
import { brandFor, kindOf } from '../../lib/kinds'
import type { RunbookEnv, RunbookStep } from '../../lib/types'
import { ErrorState, SkeletonPanel } from '../States'
import { IconTile, Pill } from '../primitives'

/* ------------------------------------------------------------------ *
 * How to run it (`knowledge/runbook.py`): what the code needs, the
 * commands to install, run and test it, and the environment it reads,
 * each from the file that says it. Nothing here is written by a model,
 * so every line names its file and opens it.
 * ------------------------------------------------------------------ */

const STEPS: { key: 'install' | 'run' | 'test' | 'container'; label: string; icon: 'download' | 'play' | 'flask-conical' | 'container' }[] = [
  { key: 'install', label: 'Install', icon: 'download' },
  { key: 'run', label: 'Run', icon: 'play' },
  { key: 'test', label: 'Test', icon: 'flask-conical' },
  { key: 'container', label: 'In a container', icon: 'container' },
]

/** A runtime's logo by its language (Python, Go, Java), a service's or Node's by name. */
function needBrand(what: string) {
  return languageBrand(what) ?? brandFor(what)
}

function SourceLink({ projectId, path }: { projectId: number; path: string }) {
  return (
    <Link
      to={`/app/projects/${projectId}/code?file=${encodeURIComponent(path)}`}
      className="truncate font-mono text-[11.5px] text-ink-dim transition-colors hover:text-hot-ink"
      title={`Open ${path}`}
    >
      {path}
    </Link>
  )
}

function Command({ step, projectId }: { step: RunbookStep; projectId: number }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(step.command)
      setCopied(true)
      setTimeout(() => setCopied(false), 1400)
    } catch {
      /* the command is selectable */
    }
  }
  return (
    <li className="flex min-w-0 flex-col gap-1 py-1.5">
      <div className="flex min-w-0 items-center gap-2">
        <code className="min-w-0 flex-1 truncate rounded-md bg-sunk px-2.5 py-1.5 font-mono text-[12.5px] text-ink shadow-[inset_0_0_0_1px_var(--line-2)]" title={step.command}>
          {step.command}
        </code>
        <button
          type="button"
          onClick={copy}
          title="Copy the command"
          aria-label={`Copy ${step.command}`}
          className="flex h-[30px] shrink-0 items-center gap-1.5 rounded-full border border-line-2 px-3 text-[12px] text-ink-mid transition-colors hover:border-hot-edge hover:text-hot-ink"
        >
          <Icon name={copied ? 'check' : 'copy'} size={13} />
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 pl-0.5 text-[12px]">
        {step.note && <span className="min-w-0 text-ink-mid">{step.note}</span>}
        <SourceLink projectId={projectId} path={step.source} />
      </div>
    </li>
  )
}

function EnvRow({ env }: { env: RunbookEnv }) {
  const declared = env.declared_in.length > 0
  const read = env.read_in.length > 0
  const tone = env.missing ? 'bad' : declared && !env.has_default ? 'warn' : 'plain'
  const state = env.missing
    ? 'needed, declared nowhere'
    : !declared
      ? 'in no template'
      : !env.has_default
        ? 'no default'
        : read
          ? 'has a default'
          : 'not seen read'
  const where = [
    env.declared_in.length ? `Declared in ${env.declared_in.join(', ')}` : 'Declared in no template, compose file or Dockerfile',
    env.read_in.length ? `read in ${env.read_in.join(', ')}` : 'not seen read by the code',
  ].join('; ')
  return (
    <li className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-b border-rule py-2 last:border-b-0" title={where}>
      <span className="flex min-w-0 items-center gap-2">
        {env.secret ? (
          <Icon name="key-round" size={13} className="shrink-0 text-warn" aria-label="A secret" />
        ) : (
          <span className="size-[13px] shrink-0" />
        )}
        <span className="truncate font-mono text-[12.5px] text-ink">{env.name}</span>
      </span>
      <Pill tone={tone}>{state}</Pill>
    </li>
  )
}

export function Runbook({ projectId }: { projectId: number }) {
  const data = useAsync(sig => api.runbook(projectId, sig), [projectId])
  const [allEnv, setAllEnv] = useState(false)

  if (data.loading) return <SkeletonPanel rows={5} />
  if (data.error) return <ErrorState message={data.error} onRetry={data.reload} compact />
  const book = data.data
  if (!book) return null
  if (!book.available)
    return (
      <p className="flex items-start gap-2 rounded-xl border border-rule bg-panel px-4 py-3 text-[13px] text-ink-mid">
        <Icon name="info" size={15} className="mt-0.5 shrink-0" />
        {book.reason}
      </p>
    )

  const steps = STEPS.filter(s => book[s.key].length)
  const missing = book.env.filter(e => e.missing).length
  const env = allEnv ? book.env : book.env.slice(0, 8)

  if (!steps.length && !book.needs.length && !book.env.length)
    return (
      <p className="rounded-xl border border-rule bg-panel px-4 py-3 text-[13px] text-ink-mid">
        The reading kept no manifest, Makefile, compose file or env template that says how to run this.
      </p>
    )

  return (
    <div className="grid grid-cols-1 gap-x-10 gap-y-6 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
      <div className="flex min-w-0 flex-col gap-5">
        {book.needs.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {book.needs.map(n => {
              const brand = needBrand(n.what)
              return (
                <span
                  key={`${n.what}-${n.source}`}
                  className="flex items-center gap-2 rounded-full border border-line-2 py-1 pr-3 pl-1.5 text-[12.5px]"
                  title={`From ${n.source}`}
                >
                  <IconTile
                    brand={brand ?? undefined}
                    icon={brand ? undefined : n.kind === 'service' ? 'database' : 'package'}
                    color={brand ? undefined : kindOf(n.kind === 'service' ? 'store' : 'manifest').color}
                    tint={!brand}
                    size={22}
                  />
                  <span className="text-ink">{n.what}</span>
                  {n.version && <span className="font-mono text-[11.5px] text-ink-dim">{n.version}</span>}
                </span>
              )
            })}
          </div>
        )}

        {steps.map(s => (
          <div key={s.key} className="flex min-w-0 flex-col">
            <h3 className="flex items-center gap-2 text-[13px] font-semibold text-ink">
              <Icon name={s.icon} size={14} className="text-ink-dim" />
              {s.label}
            </h3>
            <ul className="flex min-w-0 flex-col">
              {book[s.key].slice(0, s.key === 'run' ? 4 : 3).map(step => (
                <Command key={step.command} step={step} projectId={projectId} />
              ))}
            </ul>
          </div>
        ))}

        {book.ci.length > 0 && (
          <p className="text-[12.5px] text-ink-mid">
            <span className="text-ink-dim">CI runs </span>
            {book.ci.slice(0, 6).map((c, i) => (
              <span key={c.command}>
                {i > 0 && ', '}
                <code className="font-mono text-[12px] text-ink">{c.command}</code>
              </span>
            ))}
          </p>
        )}
      </div>

      {book.env.length > 0 && (
        <div className="flex min-w-0 flex-col gap-2">
          <h3 className="flex items-center justify-between gap-2 text-[13px] font-semibold text-ink">
            <span className="flex items-center gap-2">
              <Icon name="key-round" size={14} className="text-ink-dim" />
              Environment
            </span>
            <span className="text-[12px] font-normal text-ink-dim">{book.env.length} variables</span>
          </h3>
          {missing > 0 && (
            <p className="text-[12.5px] text-ink-mid">
              {missing === 1 ? 'One is' : `${missing} are`} read by the code and declared in no template,
              compose file or Dockerfile: set {missing === 1 ? 'it' : 'them'} before it starts.
            </p>
          )}
          <ul className="flex flex-col">
            {env.map(e => (
              <EnvRow key={e.name} env={e} />
            ))}
          </ul>
          {book.env.length > 8 && (
            <button
              type="button"
              onClick={() => setAllEnv(v => !v)}
              className="self-start text-[12.5px] text-ink-mid transition-colors hover:text-hot-ink"
            >
              {allEnv ? 'Show fewer' : `Show all ${book.env.length}`}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
