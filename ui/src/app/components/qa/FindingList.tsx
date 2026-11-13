import { useEffect, useMemo, useState } from 'react'
import { Icon } from '../../lib/icons'
import type { QAFinding, QASeverity } from '../../lib/types'
import { Inline } from './FindingDetail'
import { SEVERITIES, SEVERITY } from './look'

/* ------------------------------------------------------------------ *
 * Findings grouped twice, so the list stays short: by severity, then
 * by what was found ("Exceptions caught and dropped · 15"), each group
 * opening onto the places it was found. A group of one is the finding
 * itself.
 *
 * Groups start closed except the one holding the selected finding;
 * a search opens every group it matches in.
 * ------------------------------------------------------------------ */

interface Group {
  key: string
  label: string
  findings: QAFinding[]
}

function groupsOf(findings: QAFinding[]): { severity: QASeverity; groups: Group[]; total: number }[] {
  return SEVERITIES.map(severity => {
    const mine = findings.filter(f => f.severity === severity)
    const by = new Map<string, QAFinding[]>()
    for (const f of mine) {
      const key = f.group || f.rule
      by.set(key, [...(by.get(key) ?? []), f])
    }
    const groups = [...by.entries()]
      .map(([label, list]) => ({ key: `${severity}:${label}`, label, findings: list }))
      .sort((a, b) => b.findings.length - a.findings.length || a.label.localeCompare(b.label))
    return { severity, groups, total: mine.length }
  }).filter(s => s.total > 0)
}

function Place({ f, on, onClick, showTitle }: { f: QAFinding; on: boolean; onClick: () => void; showTitle: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={on}
      data-qa-finding
      title={f.title.replace(/`/g, '')}
      className={`flex w-full flex-col gap-0.5 py-1.5 pr-3 pl-[42px] text-left transition-colors ${
        on ? 'bg-sunk shadow-[inset_2px_0_0_var(--hot)]' : 'hover:bg-hover'
      } ${f.status !== 'open' ? 'opacity-60' : ''}`}
    >
      {showTitle && (
        <span className="text-[12.5px] leading-snug text-ink">
          <Inline text={f.title} />
        </span>
      )}
      <span className="flex min-w-0 items-center gap-2">
        <span className="flex min-w-0 flex-1" dir="rtl">
          <bdi className={`truncate font-mono text-[11.5px] ${on ? 'text-ink' : 'text-ink-mid'}`}>
            {f.path ?? 'the codebase'}
            {f.line ? `:${f.line}` : ''}
          </bdi>
        </span>
        {f.is_new && <span className="shrink-0 text-[10.5px] font-semibold text-hot-ink">new</span>}
      </span>
    </button>
  )
}

export function FindingList({
  findings,
  selectedId,
  onSelect,
  searching,
}: {
  findings: QAFinding[]
  selectedId: number | null
  onSelect: (id: number) => void
  /** A search is active: open every group so the matches show. */
  searching: boolean
}) {
  const tree = useMemo(() => groupsOf(findings), [findings])
  const [closedSeverity, setClosedSeverity] = useState<Set<string>>(new Set())
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set())

  // The group holding the selected finding opens, so the selection is never hidden.
  useEffect(() => {
    const f = findings.find(x => x.id === selectedId)
    if (!f) return
    const key = `${f.severity}:${f.group || f.rule}`
    setOpenGroups(s => (s.has(key) ? s : new Set(s).add(key)))
    setClosedSeverity(s => {
      if (!s.has(f.severity)) return s
      const next = new Set(s)
      next.delete(f.severity)
      return next
    })
  }, [selectedId, findings])

  const flip = (set: (f: (s: Set<string>) => Set<string>) => void, key: string) =>
    set(s => {
      const next = new Set(s)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })

  if (!findings.length) return <p className="px-3 py-4 text-[12.5px] text-ink-dim">No finding matches.</p>

  return (
    <div className="flex flex-col">
      {tree.map(({ severity, groups, total }) => {
        const sev = SEVERITY[severity]
        const closed = closedSeverity.has(severity)
        return (
          <section key={severity} className="border-b border-rule last:border-b-0">
            <button
              type="button"
              onClick={() => flip(setClosedSeverity, severity)}
              aria-expanded={!closed}
              className="sticky top-0 z-[1] flex w-full items-center gap-2 bg-panel px-3 py-2 text-left hover:bg-hover"
            >
              <Icon name={closed ? 'chevron-right' : 'chevron-down'} size={13} className="text-ink-dim" />
              <Icon name={sev.icon} size={14} style={{ color: sev.color }} />
              <span className="text-[12.5px] font-semibold tracking-wide uppercase" style={{ color: sev.color }}>
                {sev.label}
              </span>
              <span className="ml-auto font-mono text-[11.5px] text-ink-dim">{total}</span>
            </button>
            {!closed &&
              groups.map(g => {
                if (g.findings.length === 1) {
                  const f = g.findings[0]
                  return (
                    <Place key={f.id} f={f} on={f.id === selectedId} onClick={() => onSelect(f.id)} showTitle />
                  )
                }
                const open = searching || openGroups.has(g.key)
                const titles = new Set(g.findings.map(f => f.title))
                const fresh = g.findings.filter(f => f.is_new).length
                const hasSelected = g.findings.some(f => f.id === selectedId)
                return (
                  <div key={g.key}>
                    <button
                      type="button"
                      onClick={() => flip(setOpenGroups, g.key)}
                      aria-expanded={open}
                      className={`flex w-full items-center gap-2 py-1.5 pr-3 pl-[22px] text-left transition-colors hover:bg-hover ${
                        hasSelected && !open ? 'bg-sunk' : ''
                      }`}
                    >
                      <Icon name={open ? 'chevron-down' : 'chevron-right'} size={12} className="shrink-0 text-ink-dim" />
                      <span className="min-w-0 flex-1 truncate text-[13px] text-ink">
                        <Inline text={g.label} />
                      </span>
                      {fresh > 0 && <span className="shrink-0 text-[10.5px] font-semibold text-hot-ink">{fresh} new</span>}
                      <span className="shrink-0 rounded-full bg-sunk px-1.5 font-mono text-[11px] text-ink-mid">
                        {g.findings.length}
                      </span>
                    </button>
                    {open &&
                      g.findings.map(f => (
                        <Place
                          key={f.id}
                          f={f}
                          on={f.id === selectedId}
                          onClick={() => onSelect(f.id)}
                          showTitle={titles.size > 1}
                        />
                      ))}
                  </div>
                )
              })}
          </section>
        )
      })}
    </div>
  )
}
