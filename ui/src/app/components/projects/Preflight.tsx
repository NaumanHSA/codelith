import { useState } from 'react'
import { api } from '../../lib/api'
import { Button, Panel, inputClass } from '../ui'
import type { Preflight as PreflightResult } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * What an edit would touch.
 *
 * This is the studio's window onto the `before_edit` MCP tool — the same
 * service, the same answer. It is here rather than behind its own page
 * because it is a question you ask *about* a codebase you are already
 * looking at, and a destination you have to navigate to is a check
 * nobody runs.
 *
 * The raw agent brief is one click away on purpose. Somebody wiring an
 * agent to Codelith needs to see what it will actually receive, not a
 * prettier arrangement of the same fields.
 * ------------------------------------------------------------------ */

const RISK: Record<string, { label: string; className: string }> = {
  high: { label: 'high risk', className: 'border-bad/40 bg-bad-wash text-bad' },
  moderate: { label: 'moderate risk', className: 'border-warn/40 bg-warn-wash text-warn' },
  low: { label: 'low risk', className: 'border-ok/40 bg-ok-wash text-ok' },
  unknown: { label: 'not found', className: 'border-rule bg-sunk text-ink-dim' },
}

function List({
  title,
  hint,
  items,
}: {
  title: string
  hint?: string
  items: { key: string; left: string; right?: string; muted?: boolean }[]
}) {
  if (!items.length) return null
  return (
    <div className="border-t border-rule">
      <div className="flex items-baseline gap-2 bg-sunk/40 px-3 py-1.5">
        <span className="tag text-ink-dim">{title}</span>
        <span className="tag text-ink-dim">{items.length}</span>
        {hint && <span className="ml-auto font-sans text-[10.5px] text-ink-dim">{hint}</span>}
      </div>
      <ul className="max-h-[220px] overflow-y-auto">
        {items.map(i => (
          <li
            key={i.key}
            className="flex items-baseline gap-2.5 border-b border-rule px-3 py-1.5 last:border-b-0"
          >
            {i.right && <span className="tag w-[52px] shrink-0 text-ink-dim">{i.right}</span>}
            <span
              className={`min-w-0 flex-1 truncate text-[11.5px] ${
                i.muted ? 'text-ink-mid' : 'text-ink'
              }`}
            >
              {i.left}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export default function Preflight({ projectId }: { projectId: number }) {
  const [target, setTarget] = useState('')
  const [result, setResult] = useState<PreflightResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [raw, setRaw] = useState(false)

  async function check() {
    const q = target.trim()
    if (!q) return
    setBusy(true)
    setError(null)
    try {
      setResult(await api.preflight(projectId, q))
    } catch (e) {
      setResult(null)
      setError(e instanceof Error ? e.message : 'That lookup failed.')
    } finally {
      setBusy(false)
    }
  }

  const risk = RISK[result?.risk ?? 'unknown'] ?? RISK.unknown

  return (
    <Panel
      title="Before you edit"
      action={<span className="tag text-ink-dim">mcp: before_edit</span>}
    >
      <div className="px-3 py-2.5">
        <p className="font-sans text-[11.5px] leading-relaxed text-ink-mid">
          Name a file or a function and see what depends on it: who imports it, what
          calls it, whether a test reaches it, and which written pages describe it. This
          is the answer a connected coding agent gets before it changes anything.
        </p>
        <form
          className="mt-2.5 flex gap-2"
          onSubmit={e => {
            e.preventDefault()
            void check()
          }}
        >
          <input
            className={inputClass}
            value={target}
            onChange={e => setTarget(e.target.value)}
            placeholder="src/auth/session.py  ·  or  ·  authenticate"
            spellCheck={false}
          />
          <Button type="submit" variant="hot" disabled={busy || !target.trim()}>
            {busy ? 'checking…' : 'Check →'}
          </Button>
        </form>
      </div>

      {error && (
        <div className="border-t border-rule bg-bad-wash px-3 py-2 font-sans text-[11.5px] text-bad">
          {error}
        </div>
      )}

      {result && (
        <>
          <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1 border-t border-rule px-3 py-2.5">
            <span className={`tag border px-1.5 py-0.5 ${risk.className}`}>{risk.label}</span>
            <span className="text-[12px] font-semibold text-ink">
              {result.files[0] ?? result.target}
            </span>
            {result.files.length > 1 && (
              <span className="tag text-ink-dim">+{result.files.length - 1} more file(s)</span>
            )}
            <button
              onClick={() => setRaw(r => !r)}
              className="tag ml-auto text-ink-dim underline-offset-2 hover:text-hot-ink hover:underline"
            >
              {raw ? 'hide agent view' : 'agent view'}
            </button>
          </div>

          <p className="border-t border-rule px-3 py-2 font-sans text-[12px] leading-relaxed text-ink-mid">
            {result.headline}
          </p>

          {raw ? (
            <pre className="max-h-[420px] overflow-auto border-t border-rule bg-sunk/50 px-3 py-2.5 text-[11px] leading-relaxed whitespace-pre-wrap text-ink">
              {result.brief}
            </pre>
          ) : (
            result.found && (
              <>
                <List
                  title="defined at"
                  items={result.defined_at.map(d => ({ key: d, left: d }))}
                />
                <List
                  title="called from"
                  items={result.callers.map(c => ({
                    key: `${c.file}:${c.symbol}`,
                    left: `${c.file} :: ${c.symbol}`,
                  }))}
                />
                <List
                  title="breaks first"
                  hint="nearest first"
                  items={result.reached.map(r => ({
                    key: r.path,
                    right: `${r.distance} hop${r.distance === 1 ? '' : 's'}`,
                    left: r.is_test ? `${r.path}  [test]` : r.path,
                    muted: r.is_test,
                  }))}
                />
                {!result.tests.length && (
                  <p className="border-t border-rule bg-warn-wash px-3 py-2 font-sans text-[11.5px] text-warn">
                    No test file reaches this. A change here is unverified by the suite.
                  </p>
                )}
                <List
                  title="written pages that describe it"
                  hint="these will need re-writing"
                  items={result.documented_in.map(p => ({
                    key: p.address,
                    left: `${p.address} · ${p.title}`,
                  }))}
                />
                <List title="declares" items={result.facts.map(f => ({ key: f, left: f }))} />
              </>
            )
          )}
        </>
      )}
    </Panel>
  )
}
