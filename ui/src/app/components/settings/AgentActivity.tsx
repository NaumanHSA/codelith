import { useState } from 'react'
import { api } from '../../lib/api'
import { useAsync } from '../../lib/hooks'
import { relativeTime } from '../../lib/format'
import { Icon, type IconName } from '../../lib/icons'
import { IconTile, Pill } from '../primitives'
import { ErrorState, SkeletonPanel } from '../States'

/* ------------------------------------------------------------------ *
 * Agents over MCP: how to attach one, which have, and what they asked.
 *
 * The MCP server is a second door onto the same knowledge base, used by
 * Claude Code, Cursor and anything else that speaks the protocol. It
 * records each tool call it answers; this is the only place a person can
 * see that an agent asked "what breaks if I change this?" before editing.
 * ------------------------------------------------------------------ */

const TOOL_ICON: Record<string, IconName> = {
  list_codebases: 'folder-git-2',
  before_edit: 'shield-check',
  search_code: 'search',
  read_file: 'file-code',
  find_callers: 'square-function',
  find_dependents: 'network',
  blast_radius: 'radar',
  list_facts: 'hash',
}

const CONFIG = `{
  "mcpServers": {
    "codelith": { "command": "codelith", "args": ["mcp"] }
  }
}`

function CopyBlock({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="overflow-hidden rounded-lg border border-term-rule bg-term">
      <div className="flex items-center gap-2 border-b border-term-rule px-3 py-1.5">
        <span className="text-[12px] text-term-dim">{label}</span>
        <button
          type="button"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(text)
              setCopied(true)
              window.setTimeout(() => setCopied(false), 1500)
            } catch {
              /* the text is on screen to select by hand */
            }
          }}
          className="ml-auto flex items-center gap-1 rounded px-1.5 py-0.5 text-[12px] text-term-dim transition-colors hover:text-term-text"
        >
          <Icon name={copied ? 'check' : 'copy'} size={12} /> {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre className="overflow-x-auto px-3 py-2 font-mono text-[12px] leading-relaxed text-term-text">{text}</pre>
    </div>
  )
}

function describeArgs(args: Record<string, unknown>) {
  const v = args.target ?? args.query ?? args.path ?? args.name ?? args.symbol
  return typeof v === 'string' ? v : Object.keys(args).length ? JSON.stringify(args) : ''
}

export default function AgentActivity() {
  const activity = useAsync(sig => api.agentActivity(30, sig), [])
  const gaps = useAsync(sig => api.agentGaps(sig), [])

  return (
    <section className="flex flex-col gap-4 rounded-xl border border-rule bg-panel p-5">
      <header className="flex items-center gap-3">
        <IconTile icon="plug" color="var(--hot)" tint size={36} />
        <div className="min-w-0 flex-1">
          <h2 className="text-[15px] font-semibold text-ink">Agents over MCP</h2>
          <p className="text-[13px] text-ink-mid">
            Coding agents can query the same knowledge base, and ask what an edit would touch before they make it.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            activity.reload()
            gaps.reload()
          }}
          className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line-2 bg-sunk px-3 text-[12.5px] font-medium text-ink transition-colors hover:bg-hover"
        >
          <Icon name="refresh-cw" size={14} /> Refresh
        </button>
      </header>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <CopyBlock label=".mcp.json, for Claude Code, Cursor and others" text={CONFIG} />
        <CopyBlock label="Or, in Claude Code" text="claude mcp add codelith -- codelith mcp" />
      </div>

      {activity.loading && <SkeletonPanel rows={3} />}
      {activity.error && <ErrorState message={activity.error} onRetry={activity.reload} compact />}

      {activity.data && activity.data.agents.length === 0 && (
        <p className="text-[13px] text-ink-dim">
          No agent has called a tool yet. Once one does, it appears here with what it asked.
        </p>
      )}

      {activity.data && activity.data.agents.length > 0 && (
        <>
          <div className="flex flex-wrap gap-2">
            {activity.data.agents.map(a => (
              <span key={a.client} className="inline-flex items-center gap-2 rounded-lg border border-rule px-3 py-1.5 text-[13px]">
                <Icon name="bot" size={15} className="text-ink-mid" />
                <span className="font-medium text-ink">{a.client}</span>
                <span className="text-ink-dim">
                  {a.calls} call{a.calls === 1 ? '' : 's'} · last {relativeTime(a.last_seen)}
                </span>
              </span>
            ))}
          </div>
          {gaps.data && gaps.data.length > 0 && (
            <div className="flex flex-col gap-2 rounded-lg border border-warn/30 bg-warn-wash/40 px-4 py-3">
              <h3 className="flex items-center gap-2 text-[13.5px] font-semibold text-ink">
                <Icon name="search" size={15} className="text-warn" />
                What agents could not find
              </h3>
              <p className="text-[12.5px] leading-relaxed text-ink-mid">
                Questions that came back empty, and ones asked three times or more. Each is a name the
                knowledge does not know, a part analysis skipped, or a reading that is out of date.
              </p>
              <ul className="flex flex-col divide-y divide-rule">
                {gaps.data.slice(0, 12).map((g, k) => (
                  <li key={k} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 py-1.5">
                    <span className="font-mono text-[12px] text-ink-dim">{g.tool}</span>
                    <span className="min-w-0 flex-1 truncate font-mono text-[12.5px] text-ink" title={g.asked}>
                      {g.asked || '(no argument)'}
                    </span>
                    <span className="text-[12px] text-ink-dim">
                      {g.project_name ?? '-'} · {g.empty ? 'nothing found' : 'asked again'} · {g.times}×
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Asked</th>
                  <th>Agent</th>
                  <th>Codebase</th>
                  <th>Answer began</th>
                  <th>When</th>
                </tr>
              </thead>
              <tbody>
                {activity.data.calls.map(c => (
                  <tr key={c.id}>
                    <td>
                      <span className="flex items-center gap-2">
                        <Icon name={TOOL_ICON[c.tool] ?? 'wrench'} size={15} className="text-ink-dim" />
                        <span className="font-mono text-[12.5px] text-ink">{c.tool}</span>
                        <span className="max-w-[260px] truncate font-mono text-[12px] text-ink-mid">{describeArgs(c.args)}</span>
                      </span>
                    </td>
                    <td className="text-[13px] text-ink-mid">{c.client}</td>
                    <td className="text-[13px] text-ink-mid">{c.project_name ?? '-'}</td>
                    <td className="max-w-[360px] truncate text-[12.5px] text-ink-dim" title={c.summary ?? undefined}>
                      {c.ok ? c.summary ?? '-' : <Pill tone="bad" icon="circle-x">Failed</Pill>}
                    </td>
                    <td className="text-[12.5px] whitespace-nowrap text-ink-dim">{relativeTime(c.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  )
}
