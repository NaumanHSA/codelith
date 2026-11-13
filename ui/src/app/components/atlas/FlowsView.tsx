import { useMemo, useState } from 'react'
import { Icon, type IconName } from '../../lib/icons'
import type { Atlas, FlowDetail, FlowSummary } from '../../lib/types'
import { SkeletonPanel } from '../States'
import { Diagram, fileNode, type FEdge, type FNode } from './FlowPanel'

/* ------------------------------------------------------------------ *
 * Flows, in the panel under the map: every way into the code — routes,
 * commands, scheduled jobs, entry points — and the path the selected one
 * takes, function by function, to the data or the outside service it
 * reaches (`knowledge/flows.py`). The map lights the same path; a step
 * opens its function in the source.
 * ------------------------------------------------------------------ */

const KIND_ICON: Record<string, IconName> = {
  route: 'route',
  cli_command: 'square-terminal',
  scheduled_task: 'clock',
  event: 'zap',
  entrypoint: 'play',
}

const shortFn = (qname: string) => qname.split('.').slice(-2).join('.')

export default function FlowsView({
  atlas,
  flows,
  loading,
  flow,
  flowLoading,
  selected,
  onPick,
  onStep,
  reduced,
}: {
  atlas: Atlas
  flows: FlowSummary[] | undefined
  loading: boolean
  flow: FlowDetail | undefined
  flowLoading: boolean
  selected: string | null
  onPick: (id: string) => void
  onStep: (path: string, line: number | null) => void
  reduced: boolean
}) {
  const [query, setQuery] = useState('')
  const index = useMemo(() => new Map(atlas.nodes.map((n, i) => [n.path, i])), [atlas])

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (flows ?? []).filter(f => !q || f.name.toLowerCase().includes(q) || f.path.toLowerCase().includes(q))
  }, [flows, query])

  const diagram = useMemo(() => {
    if (!flow) return null
    const columns: FNode[][] = []
    const edges: FEdge[] = []
    flow.chain_steps.forEach((si, k) => {
      const step = flow.all_steps[si]
      const at = index.get(step.path)
      const base: FNode =
        at !== undefined
          ? fileNode(atlas, at, {})
          : { key: '', title: step.path, color: 'var(--ink-dim)', mono: true }
      columns.push([
        {
          ...base,
          key: `s${k}`,
          title: shortFn(step.qname),
          sub: `${step.path.split('/').pop()}${step.part ? ` · ${step.part}` : ''}`,
          hint: `${step.qname} — ${step.path}${step.line ? `:${step.line}` : ''}`,
          current: k === 0,
          onClick: () => onStep(step.path, step.line),
        },
      ])
      if (k > 0) edges.push({ from: `s${k - 1}`, to: `s${k}`, label: k === 1 ? 'handled by' : 'calls', strong: true })
    })
    if (flow.ends) {
      const n = columns.length
      columns.push([
        {
          key: 'end',
          title: flow.ends === 'data' ? 'Data' : 'Outside service',
          sub: flow.ends === 'data' ? 'read or written here' : 'called from here',
          icon: flow.ends === 'data' ? 'database' : 'globe',
          color: flow.ends === 'data' ? '#f472b6' : '#c7d2fe',
        },
      ])
      edges.push({ from: `s${n - 1}`, to: 'end', label: flow.ends === 'data' ? 'reads / writes' : 'calls out', strong: true })
    }
    return { columns, edges }
  }, [flow, atlas, index, onStep])

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-0 md:flex-row">
      <div className="flex max-h-[260px] min-h-0 flex-col border-rule md:max-h-none md:w-[260px] md:shrink-0 md:border-r">
        <label className="mx-3 mt-2.5 flex h-[30px] items-center gap-2 rounded-lg border border-rule bg-paper px-2.5 focus-within:border-hot">
          <Icon name="search" size={13} className="text-ink-dim" />
          <input
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Find a route or command"
            aria-label="Find a way into the code"
            className="min-w-0 flex-1 bg-transparent text-[12.5px] text-ink outline-none placeholder:text-ink-dim"
          />
        </label>
        <div className="min-h-0 flex-1 overflow-y-auto px-1.5 py-1.5">
          {loading && !flows ? (
            <div className="p-2">
              <SkeletonPanel rows={4} />
            </div>
          ) : !shown.length ? (
            <p className="px-2 py-3 text-[12.5px] text-ink-dim">
              {flows?.length ? 'Nothing matches.' : 'The analysis found no ways into this code.'}
            </p>
          ) : (
            shown.map(f => (
              <button
                key={f.id}
                type="button"
                onClick={() => onPick(f.id)}
                aria-current={f.id === selected ? 'true' : undefined}
                title={`${f.name} — ${f.path}`}
                className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors ${
                  f.id === selected ? 'bg-sunk shadow-[inset_0_0_0_1px_var(--line-2)]' : 'hover:bg-hover'
                }`}
              >
                <Icon name={KIND_ICON[f.kind] ?? 'play'} size={14} className="shrink-0 text-ink-dim" />
                <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-ink">{f.name}</span>
                <span className="shrink-0 font-mono text-[11px] text-ink-dim">{f.chain}</span>
                {f.ends && (
                  <Icon
                    name={f.ends === 'data' ? 'database' : 'globe'}
                    size={12}
                    className="shrink-0"
                    style={{ color: f.ends === 'data' ? '#f472b6' : '#c7d2fe' }}
                  />
                )}
              </button>
            ))
          )}
        </div>
      </div>

      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        {!selected ? (
          <p className="px-4 py-3 text-[13px] leading-relaxed text-ink-mid">
            Pick a way in to follow it: the function that handles it, each function it calls, and where it meets
            data or an outside service. The map lights the same path; click a step to open it in the source.
          </p>
        ) : flowLoading && !flow ? (
          <div className="p-4">
            <SkeletonPanel rows={3} />
          </div>
        ) : flow && diagram ? (
          <>
            <p className="px-4 pt-2.5 text-[13px] leading-relaxed text-ink-mid">
              <span className="font-mono text-ink">{flow.name}</span> is handled in{' '}
              <span className="font-mono text-ink">{flow.path.split('/').pop()}</span>
              {flow.ends
                ? `, and reaches ${flow.ends === 'data' ? 'data' : 'an outside service'} in ${flow.chain} step${flow.chain === 1 ? '' : 's'}`
                : '. The recorded calls stop before any data: they are traced only where the callee is unambiguous'}
              {flow.steps > flow.chain ? `. It also calls ${flow.steps - flow.chain} other function(s) along the way.` : '.'}
            </p>
            <div className="min-h-0 flex-1 overflow-y-auto pb-1">
              <Diagram columns={diagram.columns} edges={diagram.edges} reduced={reduced} />
            </div>
          </>
        ) : (
          <p className="px-4 py-3 text-[13px] text-ink-dim">This way in could not be traced.</p>
        )}
      </div>
    </div>
  )
}
