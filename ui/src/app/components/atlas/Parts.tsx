import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { Icon } from '../../lib/icons'
import { KINDS, kindOf, lookOf } from '../../lib/kinds'
import type { Atlas } from '../../lib/types'
import { IconTile } from '../primitives'
import { shortName, type Adjacency } from './graph'
import type { ComponentEdge, ComponentInfo } from './model'

/* ------------------------------------------------------------------ *
 * The inspector before a file is chosen. With nothing selected it is the
 * codebase's table of contents: every component analysis named, what it
 * is for, how to open it. With a component selected it says what that
 * part is made of, where the rest of the code comes into it and where it
 * reaches out, which is most of what "how does this part work" means.
 * ------------------------------------------------------------------ */

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

function ToggleButton({ open, name, onClick }: { open: boolean; name: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={e => {
        e.stopPropagation()
        onClick()
      }}
      aria-label={open ? `Close ${name} in the map` : `Open ${name} in the map`}
      title={open ? 'Close in the map' : 'Open in the map'}
      className="grid size-7 shrink-0 place-items-center rounded-md text-ink-dim transition-colors hover:bg-hover hover:text-ink"
    >
      <Icon name={open ? 'circle-minus' : 'circle-plus'} size={16} />
    </button>
  )
}

const LEGEND: { icon: React.ReactNode; text: React.ReactNode }[] = [
  {
    icon: <span className="block size-4 rounded-full border-[1.5px] border-dashed border-ink-dim" />,
    text: (
      <>
        A dashed circle is a part of the code. <b className="font-medium text-ink">+</b> opens it to show its files.
      </>
    ),
  },
  {
    icon: <span className="block size-2 rounded-full bg-hot shadow-[0_0_8px_var(--hot)]" />,
    text: 'Dots travel the way the call goes, from the code that calls to the code it calls.',
  },
  {
    icon: <Icon name="mouse" size={15} className="text-ink-dim" />,
    text: 'Point at a part to light up its files and links. Pick a file to follow what it calls.',
  },
]

export function OverviewPane({
  atlas,
  components,
  expanded,
  focus,
  onToggle,
  onPick,
  onFocus,
  onAll,
}: {
  atlas: Atlas
  components: ComponentInfo[]
  expanded: Set<number>
  focus: number | null
  onToggle: (c: number) => void
  onPick: (c: number) => void
  onFocus: (c: number | null) => void
  onAll: (open: boolean) => void
}) {
  const parts = components.filter(c => c.members.length)
  // Analysis's own components first, by size; then the groups the map adds.
  const order = [...parts].sort(
    (a, b) => Number(a.group !== 'component') - Number(b.group !== 'component') || b.members.length - a.members.length,
  )
  const files = atlas.nodes.filter(n => !n.fact).length
  const allOpen = parts.every(c => expanded.has(c.index))

  return (
    <div className="flex flex-col gap-5 p-5">
      <header className="flex flex-col gap-1.5">
        <h3 className="text-[15px] font-semibold text-ink">The codebase in {parts.length} parts</h3>
        <p className="text-[13px] leading-relaxed text-ink-mid">
          {files.toLocaleString()} files, grouped into the parts analysis found. Start from a part to see what it
          does and what it talks to.
        </p>
      </header>

      <ul className="flex flex-col gap-2 rounded-lg border border-rule bg-sunk/40 p-3">
        {LEGEND.map((l, k) => (
          <li key={k} className="flex items-start gap-2.5 text-[12.5px] leading-snug text-ink-mid">
            <span className="grid size-4 shrink-0 place-items-center pt-0.5">{l.icon}</span>
            <span>{l.text}</span>
          </li>
        ))}
      </ul>

      <Section title="Parts" count={parts.length}>
        <div className="-mx-2 flex flex-col">
          {order.map(c => {
            const top = kindOf(c.dominant[0])
            return (
              <div
                key={c.index}
                role="button"
                tabIndex={0}
                onClick={() => onPick(c.index)}
                onKeyDown={e => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    onPick(c.index)
                  }
                }}
                onMouseEnter={() => onFocus(c.index)}
                onMouseLeave={() => onFocus(null)}
                className={`group flex cursor-pointer items-start gap-3 rounded-lg px-2 py-2 transition-colors hover:bg-hover ${
                  focus === c.index ? 'bg-hover' : ''
                }`}
              >
                <IconTile icon={top.icon} color={top.color} tint size={30} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-2">
                    <span className="truncate text-[13.5px] font-medium text-ink">{c.name}</span>
                    <span className="shrink-0 font-mono text-[11.5px] text-ink-dim">{c.members.length}</span>
                  </div>
                  {c.description && (
                    <p className="mt-0.5 line-clamp-2 text-[12.5px] leading-snug text-ink-dim">{c.description}</p>
                  )}
                </div>
                <ToggleButton open={expanded.has(c.index)} name={c.name} onClick={() => onToggle(c.index)} />
              </div>
            )
          })}
        </div>
        <button
          type="button"
          onClick={() => onAll(!allOpen)}
          className="mt-1 flex items-center gap-2 self-start rounded-md px-2 py-1 text-[12.5px] text-ink-mid transition-colors hover:bg-hover hover:text-ink"
        >
          <Icon name={allOpen ? 'chevrons-down-up' : 'chevrons-up-down'} size={14} />
          {allOpen ? 'Close every part' : 'Open every part'}
        </button>
      </Section>
    </div>
  )
}

export function ComponentPane({
  projectId,
  atlas,
  adj,
  components,
  edges,
  c,
  expanded,
  onToggle,
  onBack,
  onPickComponent,
  onPickFile,
  onFocus,
}: {
  projectId: number
  atlas: Atlas
  adj: Adjacency
  components: ComponentInfo[]
  edges: ComponentEdge[]
  c: number
  expanded: boolean
  onToggle: () => void
  onBack: () => void
  onPickComponent: (c: number) => void
  onPickFile: (i: number) => void
  onFocus: (c: number | null) => void
}) {
  const info = components[c]
  const top = kindOf(info.dominant[0])

  const { doors, reaches } = useMemo(() => {
    const outsideIn = (i: number) => adj.dependants[i].filter(j => atlas.nodes[j].component !== c).length
    const insideOut = (i: number) => adj.uses[i].filter(j => atlas.nodes[j].component !== c).length
    const rank = (f: (i: number) => number) =>
      info.members
        .map(i => [i, f(i)] as const)
        .filter(([, n]) => n > 0)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 6)
    return { doors: rank(outsideIn), reaches: rank(insideOut) }
  }, [adj, atlas, c, info])

  const into = edges.filter(e => e.to === c).sort((a, b) => b.imports - a.imports)
  const out = edges.filter(e => e.from === c).sort((a, b) => b.imports - a.imports)
  const kinds = (Object.keys(KINDS) as (keyof typeof KINDS)[]).filter(k => info.kinds[k])

  const ask = `/app/chat?project=${projectId}&thread=new&ask=${encodeURIComponent(
    `How does the ${info.name} part of this codebase work, and what does it talk to?`,
  )}`

  const fileRow = (i: number, n: number, arrow: string, title: string) => {
    const node = atlas.nodes[i]
    const look = lookOf(node)
    const kind = kindOf(node.kind)
    return (
      <button
        key={i}
        type="button"
        onClick={() => onPickFile(i)}
        title={`${node.path} · ${title}`}
        className="group flex w-full min-w-0 items-center gap-2.5 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-hover"
      >
        <IconTile icon={look.icon} brand={look.brand} color={kind.color} tint={!look.brand} size={22} />
        <span className="min-w-0 flex-1 truncate font-mono text-[12.5px] text-ink-mid group-hover:text-ink">
          {node.fact ? node.path : shortName(node.path)}
        </span>
        <span className="shrink-0 font-mono text-[11px] text-ink-dim">
          {arrow}
          {n}
        </span>
      </button>
    )
  }

  const compRow = (e: ComponentEdge, other: number) => {
    const o = components[other]
    const k = kindOf(o.dominant[0])
    return (
      <button
        key={other}
        type="button"
        onClick={() => onPickComponent(other)}
        onMouseEnter={() => onFocus(other)}
        onMouseLeave={() => onFocus(null)}
        className="group flex w-full min-w-0 items-center gap-2.5 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-hover"
      >
        <IconTile icon={k.icon} color={k.color} tint size={22} />
        <span className="min-w-0 flex-1 truncate text-[13px] text-ink-mid group-hover:text-ink">{o.name}</span>
        <span className="shrink-0 font-mono text-[11px] text-ink-dim">
          {e.verb ?? `${e.imports} import${e.imports === 1 ? '' : 's'}`}
        </span>
      </button>
    )
  }

  return (
    <div className="flex flex-col gap-5 p-5">
      <button
        type="button"
        onClick={onBack}
        className="-ml-2 flex items-center gap-1.5 self-start rounded-md px-2 py-1 text-[12.5px] text-ink-mid transition-colors hover:bg-hover hover:text-ink"
      >
        <Icon name="arrow-left" size={14} /> All parts
      </button>

      <header className="flex flex-col gap-3">
        <div className="flex items-center gap-3">
          <IconTile icon={top.icon} color={top.color} tint size={40} />
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-[16px] font-semibold text-ink">{info.name}</h3>
            <span className="text-[12.5px] text-ink-dim">
              {info.members.length} file{info.members.length === 1 ? '' : 's'}
            </span>
          </div>
        </div>
        {info.description && <p className="text-[13px] leading-relaxed text-ink-mid">{info.description}</p>}
        <div className="flex flex-wrap gap-1.5">
          {kinds.map(k => (
            <span
              key={k}
              className="inline-flex items-center gap-1.5 rounded-md border border-rule bg-sunk/50 px-2 py-0.5 text-[12px] text-ink-mid"
            >
              <Icon name={KINDS[k].icon} size={13} style={{ color: KINDS[k].color }} />
              {info.kinds[k]} {(info.kinds[k] === 1 ? KINDS[k].label : KINDS[k].plural).toLowerCase()}
            </span>
          ))}
        </div>
      </header>

      {into.length > 0 && (
        <Section title="Used by" count={into.length}>
          <div className="-mx-2 flex flex-col">{into.slice(0, 8).map(e => compRow(e, e.from))}</div>
        </Section>
      )}
      {out.length > 0 && (
        <Section title="Uses" count={out.length}>
          <div className="-mx-2 flex flex-col">{out.slice(0, 8).map(e => compRow(e, e.to))}</div>
        </Section>
      )}

      {doors.length > 0 && (
        <Section title="Where the rest of the code comes in">
          <div className="-mx-2 flex flex-col">
            {doors.map(([i, n]) => fileRow(i, n, '←', `imported by ${n} file${n === 1 ? '' : 's'} in other parts`))}
          </div>
        </Section>
      )}
      {reaches.length > 0 && (
        <Section title="Where it reaches out">
          <div className="-mx-2 flex flex-col">
            {reaches.map(([i, n]) => fileRow(i, n, '→', `imports ${n} file${n === 1 ? '' : 's'} in other parts`))}
          </div>
        </Section>
      )}

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onToggle}
          className="inline-flex items-center gap-2 rounded-lg border border-line-2 bg-sunk px-3.5 py-[7px] text-[13px] font-medium text-ink transition-colors hover:bg-hover"
        >
          <Icon name={expanded ? 'circle-minus' : 'circle-plus'} size={15} />
          {expanded ? 'Close in the map' : 'Open in the map'}
        </button>
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
