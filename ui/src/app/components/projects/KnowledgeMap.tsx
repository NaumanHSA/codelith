import { useMemo, useState } from 'react'
import { humanize } from '../../lib/format'
import type { KnowledgeBase, ModuleRole } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * The knowledge base as a survey plot.
 *
 * Roles orbit the repository at radii set by their share of modules, so
 * the shape of the codebase reads before any number does: an API-heavy
 * service and a UI-heavy one look different at a glance.
 * ------------------------------------------------------------------ */

const SIZE = 300
const C = SIZE / 2

export default function KnowledgeMap({ kb }: { kb: KnowledgeBase }) {
  const [active, setActive] = useState<string | null>(null)

  const roles = useMemo(() => {
    const entries = Object.entries(kb.roles ?? {})
      .filter(([, n]) => n > 0)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 10)
    const max = Math.max(1, ...entries.map(([, n]) => n))
    const total = entries.reduce((s, [, n]) => s + n, 0) || 1
    return entries.map(([role, count], i) => {
      // Even angular spread, radius by share — big roles sit further out
      // and carry a larger node, so weight reads twice.
      const angle = (i / entries.length) * Math.PI * 2 - Math.PI / 2
      const r = 52 + (count / max) * 76
      return {
        role,
        count,
        pct: (count / total) * 100,
        x: C + Math.cos(angle) * r,
        y: C + Math.sin(angle) * r,
        node: 4 + (count / max) * 7,
      }
    })
  }, [kb.roles])

  const modulesFor = (role: string) =>
    (kb.top_modules ?? []).filter(m => m.role === role).slice(0, 6)

  if (!roles.length) return null

  return (
    <div className="grid grid-cols-1 gap-px bg-rule lg:grid-cols-[300px_1fr]">
      <div className="bp-grid flex items-center justify-center bg-panel p-2">
        <svg width={SIZE} height={SIZE} role="img" aria-label="Module roles by share">
          {/* survey rings */}
          {[52, 90, 128].map(r => (
            <circle
              key={r}
              cx={C}
              cy={C}
              r={r}
              fill="none"
              stroke="var(--rule)"
              strokeDasharray="2 4"
            />
          ))}

          {roles.map(r => {
            const on = active === r.role
            const dim = active !== null && !on
            return (
              <g
                key={r.role}
                opacity={dim ? 0.28 : 1}
                onMouseEnter={() => setActive(r.role)}
                onMouseLeave={() => setActive(null)}
                style={{ transition: 'opacity .15s', cursor: 'pointer' }}
              >
                <line
                  x1={C}
                  y1={C}
                  x2={r.x}
                  y2={r.y}
                  stroke={on ? 'var(--hot)' : 'var(--rule)'}
                  strokeWidth={on ? 1.5 : 1}
                />
                <rect
                  x={r.x - r.node / 2}
                  y={r.y - r.node / 2}
                  width={r.node}
                  height={r.node}
                  transform={`rotate(45 ${r.x} ${r.y})`}
                  fill={on ? 'var(--hot)' : 'var(--panel)'}
                  stroke={on ? 'var(--hot)' : 'var(--ink-mid)'}
                  strokeWidth="1.5"
                />
                <text
                  x={r.x}
                  y={r.y - r.node - 5}
                  textAnchor="middle"
                  className="fill-ink-mid text-[8.5px] tracking-[.12em] uppercase"
                >
                  {humanize(r.role)}
                </text>
                <text
                  x={r.x}
                  y={r.y + r.node + 10}
                  textAnchor="middle"
                  className={`text-[9px] font-bold ${on ? 'fill-hot-ink' : 'fill-ink-dim'}`}
                >
                  {r.count}
                </text>
              </g>
            )
          })}

          {/* the repository itself */}
          <circle cx={C} cy={C} r="21" fill="var(--panel)" stroke="var(--ink)" strokeWidth="1.5" />
          <text
            x={C}
            y={C - 2}
            textAnchor="middle"
            className="fill-ink text-[13px] font-bold tabular-nums"
          >
            {kb.module_count}
          </text>
          <text
            x={C}
            y={C + 9}
            textAnchor="middle"
            className="fill-ink-dim text-[7px] tracking-[.14em] uppercase"
          >
            modules
          </text>
        </svg>
      </div>

      {/* the legend doubles as a drill-down */}
      <div className="bg-panel">
        <ul>
          {roles.map(r => {
            const on = active === r.role
            const mods = on ? modulesFor(r.role) : []
            return (
              <li
                key={r.role}
                onMouseEnter={() => setActive(r.role)}
                onMouseLeave={() => setActive(null)}
                className={`border-b border-rule px-3 py-2 transition-colors last:border-b-0 ${
                  on ? 'bg-hot-wash/70' : ''
                }`}
              >
                <div className="flex items-center gap-2.5">
                  <span className="tag w-[92px] shrink-0 truncate text-ink">
                    {humanize(r.role as ModuleRole)}
                  </span>
                  <span className="h-[5px] min-w-0 flex-1 bg-sunk">
                    <span
                      className={`block h-full ${on ? 'bg-hot' : 'bg-ink-mid'}`}
                      style={{ width: `${Math.max(2, r.pct)}%`, transition: 'width .3s' }}
                    />
                  </span>
                  <span className="tag w-9 shrink-0 text-right tabular-nums text-ink-dim">
                    {Math.round(r.pct)}%
                  </span>
                </div>
                {mods.length > 0 && (
                  <ul className="mt-1.5 ml-[102px] space-y-0.5">
                    {mods.map(m => (
                      <li key={m.path} className="truncate text-[10.5px] text-ink-mid">
                        <span className="text-hot-ink">└</span> {m.path}
                        {m.loc != null && <span className="text-ink-dim"> · {m.loc} loc</span>}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            )
          })}
        </ul>
      </div>
    </div>
  )
}
