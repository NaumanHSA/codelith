import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../lib/api'
import { useAsync } from '../../lib/hooks'
import { Icon } from '../../lib/icons'
import { kindOf, lookOf, symbolKindOf } from '../../lib/kinds'
import type { Atlas, FileCalls, Preflight } from '../../lib/types'
import { IconTile, Pill } from '../primitives'
import { ErrorState, SkeletonPanel } from '../States'
import CodeView from '../projects/CodeView'
import { reachList, shortName, type Adjacency, type Blast } from './graph'
import { NEW_TAB } from '../layout/tabState'
import { SEVERITY } from '../qa/look'

/* ------------------------------------------------------------------ *
 * The inspector: what the selected node is and what an edit to it would
 * touch. The counts and the list come from the same shortest-path walk
 * the scene draws; the risk, the written pages and the declared facts
 * come from /preflight, the answer a connected agent gets.
 * ------------------------------------------------------------------ */

const SHOWN = 8

const RISK = {
  high: { tone: 'bad', icon: 'triangle-alert', text: 'High risk to edit' },
  moderate: { tone: 'warn', icon: 'triangle-alert', text: 'Edit with care' },
  low: { tone: 'good', icon: 'shield-check', text: 'Safe to edit' },
} as const

function Section({ title, count, children }: { title: string; count?: number; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-1.5">
      <h4 className="flex items-center justify-between text-[12.5px] font-semibold text-ink-mid">
        <span>{title}</span>
        {count !== undefined && <span className="font-mono text-[11.5px] font-normal text-ink-dim">{count}</span>}
      </h4>
      {children}
    </section>
  )
}

function NodeRow({
  atlas,
  i,
  lead,
  onPick,
}: {
  atlas: Atlas
  i: number
  lead?: React.ReactNode
  onPick: (i: number) => void
}) {
  const node = atlas.nodes[i]
  const kind = kindOf(node.kind)
  const look = lookOf(node)
  return (
    <button
      type="button"
      onClick={() => onPick(i)}
      title={`Fly to ${node.path}`}
      className="group flex w-full min-w-0 items-center gap-2.5 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-hover"
    >
      {lead}
      <IconTile icon={look.icon} brand={look.brand} color={kind.color} tint={!look.brand} size={22} />
      <span className="min-w-0 flex-1 truncate font-mono text-[12.5px] text-ink-mid group-hover:text-ink">
        {node.fact ? node.path : shortName(node.path)}
      </span>
    </button>
  )
}

export default function Inspector({
  projectId,
  atlas,
  adj,
  selected,
  blast,
  preflight,
  calls,
  source,
  onPick,
  onOpenSource,
  onCloseSource,
  onDive,
  onComponent,
}: {
  projectId: number
  atlas: Atlas
  adj: Adjacency
  selected: number
  blast: Blast
  preflight: { data?: Preflight; loading: boolean }
  calls: { data?: FileCalls; loading: boolean }
  source: { path: string; line: number | null } | null
  onPick: (i: number) => void
  onOpenSource: (path: string, line: number | null) => void
  onCloseSource: () => void
  onDive: () => void
  onComponent: (c: number) => void
}) {
  const node = atlas.nodes[selected]
  const kind = kindOf(node.kind)
  const look = lookOf(node)
  const component = atlas.components[node.component]
  const [allHops, setAllHops] = useState(false)
  const [allUses, setAllUses] = useState(false)

  const list = useMemo(() => reachList(atlas, blast, selected), [atlas, blast, selected])
  const direct = list.filter(([, d]) => d === 1).length
  const tests = list.filter(([i]) => atlas.nodes[i].kind === 'test').length
  const uses = adj.uses[selected]
  const sourceIndex = node.source ? atlas.nodes.findIndex(n => n.path === node.source && !n.fact) : -1

  const incomingBy = useMemo(() => {
    const m = new Map<string, number>()
    for (const c of calls.data?.incoming ?? []) m.set(c.callee, (m.get(c.callee) ?? 0) + 1)
    return m
  }, [calls.data])

  if (source) return <SourcePane projectId={projectId} source={source} onClose={onCloseSource} />

  const risk = preflight.data?.found ? RISK[preflight.data.risk as keyof typeof RISK] : undefined
  const ask = `/app/chat?project=${projectId}&thread=new&ask=${encodeURIComponent(
    node.fact
      ? `Where and how does this codebase use ${node.path}?`
      : `What does ${node.path} do, and what depends on it?`,
  )}`

  return (
    <div className="flex flex-col gap-5 p-5">
      <header className="flex flex-col gap-3">
        <div className="flex items-center gap-3">
          <IconTile icon={look.icon} brand={look.brand} color={kind.color} tint={!look.brand} size={40} />
          <div className="flex min-w-0 flex-col items-start">
            <span className="text-[12.5px] font-medium" style={{ color: kind.color }}>
              {kind.label}
            </span>
            {component && (
              <button
                type="button"
                onClick={() => onComponent(node.component)}
                title={node.why ? `${node.why} Show the ${component.name} part.` : `Show the ${component.name} part`}
                className="mt-0.5 flex max-w-full items-center gap-1 truncate rounded text-[12.5px] text-ink-mid transition-colors hover:text-hot-ink"
              >
                <span className="truncate">in {component.name}</span>
                <Icon name="chevron-right" size={13} />
              </button>
            )}
          </div>
        </div>
        <h3 className="font-mono text-[13.5px] leading-snug font-semibold break-all text-ink">{node.path}</h3>
        {!node.fact && node.why && (
          <p className="flex items-start gap-1.5 text-[12.5px] leading-snug text-ink-dim">
            <Icon name="info" size={13} className="mt-[3px] shrink-0" />
            <span>{node.why}</span>
          </p>
        )}
        {node.fact && (
          <p className="text-[13px] text-ink-mid">
            {node.detail ? `${node.detail} · ` : ''}declared in{' '}
            {sourceIndex >= 0 ? (
              <button
                type="button"
                className="font-mono text-hot-ink hover:underline"
                onClick={() => onPick(sourceIndex)}
              >
                {shortName(node.source!)}
              </button>
            ) : (
              <span className="font-mono">{node.source}</span>
            )}
          </p>
        )}
        {!node.fact &&
          (risk ? (
            <div className="flex flex-col gap-2">
              <span className="self-start">
                <Pill tone={risk.tone} icon={risk.icon}>
                  {risk.text}
                </Pill>
              </span>
              <p className="text-[13px] leading-relaxed text-ink-mid first-letter:uppercase">
                {preflight.data?.headline}
              </p>
            </div>
          ) : preflight.loading ? (
            <span className="skel block h-6 w-32 rounded-full" />
          ) : null)}
      </header>

      <div className="grid grid-cols-3 overflow-hidden rounded-lg border border-rule">
        {[
          [direct, 'import it'],
          [list.length, 'reach it'],
          [tests, tests === 1 ? 'test' : 'tests'],
        ].map(([v, k], ix) => (
          <div key={ix} className={`px-3 py-2.5 ${ix ? 'border-l border-rule' : ''}`}>
            <b className="font-head block text-[20px] leading-tight font-semibold text-ink tabular-nums">{v}</b>
            <span className="text-[11.5px] text-ink-mid">{k}</span>
          </div>
        ))}
      </div>

      <Section title="What breaks first" count={list.length || undefined}>
        {list.length === 0 ? (
          <p className="text-[13px] text-ink-dim">Nothing depends on this.</p>
        ) : (
          <div className="flex flex-col">
            {(allHops ? list : list.slice(0, SHOWN)).map(([i, d]) => (
              <NodeRow
                key={i}
                atlas={atlas}
                i={i}
                onPick={onPick}
                lead={
                  <span className="w-11 shrink-0 font-mono text-[11px] text-ink-dim">
                    {d} hop{d > 1 ? 's' : ''}
                  </span>
                }
              />
            ))}
            {list.length > SHOWN && (
              <button
                type="button"
                onClick={() => setAllHops(v => !v)}
                className="mt-1 self-start rounded-md px-2 py-1 text-[12.5px] text-ink-dim transition-colors hover:bg-hover hover:text-ink"
              >
                {allHops ? 'Show fewer' : `Show all ${list.length}`}
              </button>
            )}
          </div>
        )}
      </Section>

      {!node.fact && (calls.loading || (calls.data?.symbols.length ?? 0) > 0) && (
        <Section title="Inside this file" count={calls.data?.symbols.length}>
          {calls.loading && !calls.data ? (
            <SkeletonPanel rows={3} />
          ) : (
            <>
              <div className="flex flex-col">
                {calls.data!.symbols.slice(0, 40).map(s => {
                  const sk = symbolKindOf(s.kind)
                  const n = incomingBy.get(s.qname) ?? 0
                  return (
                    <button
                      key={`${s.qname}:${s.line}`}
                      type="button"
                      onClick={() => onOpenSource(node.path, s.line)}
                      title={`${sk.label} ${s.qname}, line ${s.line ?? '?'}`}
                      className="group flex min-w-0 items-center gap-2.5 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-hover"
                    >
                      <Icon name={sk.icon} size={15} style={{ color: sk.color }} />
                      <span className="min-w-0 flex-1 truncate font-mono text-[12.5px] text-ink-mid group-hover:text-ink">
                        {s.qname}
                      </span>
                      {n > 0 && (
                        <span className="shrink-0 font-mono text-[11px] text-ink-dim" title={`Called from ${n} place${n === 1 ? '' : 's'} in other files`}>
                          ←{n}
                        </span>
                      )}
                      <span className="shrink-0 font-mono text-[11px] text-ink-dim">{s.line}</span>
                    </button>
                  )
                })}
              </div>
              <button
                type="button"
                onClick={onDive}
                className="flex items-center gap-2 self-start rounded-md px-2 py-1 text-[12.5px] text-ink-mid transition-colors hover:bg-hover hover:text-ink"
              >
                <Icon name="move-3d" size={14} /> Show them in the map
              </button>
            </>
          )}
        </Section>
      )}

      {(preflight.data?.findings?.length ?? 0) > 0 && (
        <Section title="Open QA findings" count={preflight.data!.findings.length}>
          {preflight.data!.findings.slice(0, 8).map(f => {
            const sev = SEVERITY[f.severity] ?? SEVERITY.info
            return (
              <Link
                key={f.id}
                to={`/app/projects/${projectId}/qa?run=${f.run_id}&f=${f.id}`}
                state={NEW_TAB}
                className="flex items-start gap-2.5 rounded-md px-2 py-1.5 text-[13px] text-ink-mid transition-colors hover:bg-hover hover:text-ink"
              >
                <Icon name={sev.icon} size={15} className="mt-0.5 shrink-0" style={{ color: sev.color }} />
                <span className="min-w-0">
                  <span className="block truncate">{f.title}</span>
                  <span className="block font-mono text-[11.5px] text-ink-dim">
                    {sev.label.toLowerCase()} · line {f.line ?? '-'}
                  </span>
                </span>
              </Link>
            )
          })}
        </Section>
      )}

      {(preflight.data?.documented_in.length ?? 0) > 0 && (
        <Section title="Written pages that describe it" count={preflight.data!.documented_in.length}>
          {preflight.data!.documented_in.map(p => (
            <Link
              key={p.address}
              to={`/app/projects/${projectId}/docs/${p.address}`}
              state={NEW_TAB}
              className="flex items-center gap-2.5 rounded-md px-2 py-1.5 text-[13px] text-ink-mid transition-colors hover:bg-hover hover:text-ink"
            >
              <Icon name="book-open-text" size={15} className="text-ink-dim" />
              <span className="truncate">{p.title}</span>
            </Link>
          ))}
        </Section>
      )}

      {uses.length > 0 && (
        <Section title="Depends on" count={uses.length}>
          <div className="flex flex-col">
            {(allUses ? uses : uses.slice(0, 6)).map(i => (
              <NodeRow key={i} atlas={atlas} i={i} onPick={onPick} />
            ))}
            {uses.length > 6 && (
              <button
                type="button"
                onClick={() => setAllUses(v => !v)}
                className="mt-1 self-start rounded-md px-2 py-1 text-[12.5px] text-ink-dim transition-colors hover:bg-hover hover:text-ink"
              >
                {allUses ? 'Show fewer' : `Show all ${uses.length}`}
              </button>
            )}
          </div>
        </Section>
      )}

      {(preflight.data?.facts.length ?? 0) > 0 && (
        <Section title="Declares" count={preflight.data!.facts.length}>
          <ul className="flex flex-col gap-1 font-mono text-[12px] text-ink-mid">
            {preflight.data!.facts.slice(0, 12).map(f => (
              <li key={f} className="break-all">
                {f}
              </li>
            ))}
          </ul>
        </Section>
      )}

      <div className="flex flex-wrap gap-2">
        {!node.fact && (
          <button
            type="button"
            onClick={() => onOpenSource(node.path, null)}
            className="inline-flex items-center gap-2 rounded-lg border border-line-2 bg-sunk px-3.5 py-[7px] text-[13px] font-medium text-ink transition-colors hover:bg-hover"
          >
            <Icon name="file-code" size={15} /> Open the source
          </button>
        )}
        {!node.fact && (
          <Link
            to={`/app/projects/${projectId}/history?file=${encodeURIComponent(node.path)}`}
            state={NEW_TAB}
            className="inline-flex items-center gap-2 rounded-lg border border-line-2 bg-sunk px-3.5 py-[7px] text-[13px] font-medium text-ink transition-colors hover:bg-hover"
          >
            <Icon name="history" size={15} /> Its history
          </Link>
        )}
        <Link
          to={ask}
          className="inline-flex items-center gap-2 rounded-lg border border-line-2 bg-sunk px-3.5 py-[7px] text-[13px] font-medium text-ink transition-colors hover:bg-hover"
        >
          <Icon name="message-square" size={15} /> Ask about it
        </Link>
      </div>
    </div>
  )
}

/** The file, opened in place: the inspector widens and the map stays where it was. */
function SourcePane({
  projectId,
  source,
  onClose,
}: {
  projectId: number
  source: { path: string; line: number | null }
  onClose: () => void
}) {
  const file = useAsync(sig => api.file(projectId, source.path, sig), [projectId, source.path])
  const [range, setRange] = useState<[number, number] | null>(source.line ? [source.line, source.line] : null)

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex items-center gap-2 border-b border-rule px-4 py-3">
        <button
          type="button"
          onClick={onClose}
          className="flex items-center gap-1.5 rounded-md px-2 py-1 text-[12.5px] text-ink-mid transition-colors hover:bg-hover hover:text-ink"
        >
          <Icon name="arrow-left" size={14} /> Details
        </button>
        <span className="min-w-0 flex-1 truncate text-right font-mono text-[12.5px] text-ink-mid">
          {source.path}
        </span>
      </header>
      <div className="min-h-0 flex-1 overflow-hidden">
        {file.loading && (
          <div className="p-4">
            <SkeletonPanel rows={10} />
          </div>
        )}
        {file.error && (
          <div className="p-4">
            <ErrorState message={file.error} compact />
          </div>
        )}
        {file.data && (
          <CodeView
            file={file.data}
            range={range}
            fill
            onPickLine={(line, extend) =>
              setRange(r => (extend && r ? [Math.min(r[0], line), Math.max(r[1], line)] : [line, line]))
            }
          />
        )}
      </div>
    </div>
  )
}
