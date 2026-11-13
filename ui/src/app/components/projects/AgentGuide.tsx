import { useState } from 'react'
import { api, ApiError } from '../../lib/api'
import { Icon } from '../../lib/icons'

/* ------------------------------------------------------------------ *
 * The instruction file coding agents read first (AGENTS.md / CLAUDE.md),
 * written from the reading (`knowledge/guide.py`): what the codebase is,
 * its parts and which way imports run, how to run it, how things are done
 * here, and the files to edit with care. Generated on request — it builds
 * the map and ranks every file — and copied, or written into the repository
 * with `codelith agents-md --write`.
 * ------------------------------------------------------------------ */

type Format = 'agents' | 'claude'

export default function AgentGuide({ projectId }: { projectId: number }) {
  const [format, setFormat] = useState<Format>('agents')
  const [text, setText] = useState<Record<Format, string | undefined>>({ agents: undefined, claude: undefined })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const load = async (f: Format) => {
    setFormat(f)
    if (text[f] !== undefined) return
    setLoading(true)
    setError(null)
    try {
      const guide = await fetchGuide(projectId, f)
      setText(t => ({ ...t, [f]: guide }))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not write it.')
    } finally {
      setLoading(false)
    }
  }

  const copy = async () => {
    const body = text[format]
    if (!body) return
    try {
      await navigator.clipboard.writeText(body)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* selectable below */
    }
  }

  const file = format === 'claude' ? 'CLAUDE.md' : 'AGENTS.md'
  const shown = text[format]

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-rule bg-panel px-4 py-3.5">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex gap-0.5 rounded-lg border border-rule bg-paper p-[3px]" role="group" aria-label="Which file">
          {(['agents', 'claude'] as Format[]).map(f => (
            <button
              key={f}
              type="button"
              aria-pressed={format === f}
              onClick={() => void load(f)}
              className={`rounded-md px-2.5 py-1 font-mono text-[12px] transition-colors ${
                format === f && shown !== undefined ? 'bg-sunk text-ink shadow-[inset_0_0_0_1px_var(--line-2)]' : 'text-ink-mid hover:text-ink'
              }`}
            >
              {f === 'claude' ? 'CLAUDE.md' : 'AGENTS.md'}
            </button>
          ))}
        </div>
        {shown === undefined ? (
          <button
            type="button"
            onClick={() => void load(format)}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-lg border border-line-2 bg-sunk px-3 py-[5px] text-[12.5px] font-medium text-ink transition-colors hover:bg-hover disabled:opacity-60"
          >
            <Icon name={loading ? 'loader' : 'bot'} size={14} className={loading ? 'anim-spin' : ''} />
            {loading ? 'Writing…' : `Write ${file}`}
          </button>
        ) : (
          <button
            type="button"
            onClick={() => void copy()}
            className="inline-flex items-center gap-2 rounded-lg border border-line-2 bg-sunk px-3 py-[5px] text-[12.5px] font-medium text-ink transition-colors hover:bg-hover"
          >
            <Icon name={copied ? 'check' : 'copy'} size={14} />
            {copied ? 'Copied' : `Copy ${file}`}
          </button>
        )}
        <span className="ml-auto text-[12.5px] text-ink-dim">
          Or in the repository: <code className="font-mono text-ink">codelith agents-md --write{format === 'claude' ? ' --format claude' : ''}</code>
        </span>
      </div>
      {error && <p className="text-[12.5px] text-bad">{error}</p>}
      {shown !== undefined && (
        <pre className="max-h-[420px] overflow-auto rounded-lg border border-rule bg-sunk/50 px-3.5 py-3 font-mono text-[12px] leading-relaxed whitespace-pre-wrap text-ink-mid">
          {shown}
        </pre>
      )}
    </div>
  )
}

async function fetchGuide(projectId: number, format: Format): Promise<string> {
  const guide = await api.agentGuide(projectId, format)
  return guide.markdown
}
