import { useId, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../../lib/api'
import { countLabel, formatDateTime, shortSha } from '../../lib/format'
import { useAsync } from '../../lib/hooks'
import { Icon, type IconName } from '../../lib/icons'
import { kindOf } from '../../lib/kinds'
import { useFill } from '../../lib/motion'
import type { TimelineReading } from '../../lib/types'
import { ErrorState, SkeletonPanel } from '../States'
import { IconTile, Pill } from '../primitives'

/* ------------------------------------------------------------------ *
 * Health over time, on the codebase page: where danger collects
 * (`knowledge/hotspots.py`) and whether the code is getting better or
 * worse, reading after reading (`knowledge/timeline.py`).
 * ------------------------------------------------------------------ */

const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 })

function date(iso: string | null) {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

/* ── hotspots ─────────────────────────────────────────────────────────── */

function ChangeBar({ value, max }: { value: number; max: number }) {
  const pct = useFill(max ? (value / max) * 100 : 0)
  return (
    <span className="block h-1.5 w-full overflow-hidden rounded-full bg-rule">
      <span className="block h-full rounded-full bg-hot transition-[width] duration-[420ms]" style={{ width: `${pct}%` }} />
    </span>
  )
}

export function Hotspots({ projectId }: { projectId: number }) {
  const data = useAsync(sig => api.hotspots(projectId, 12, sig), [projectId])
  if (data.loading) return <SkeletonPanel rows={6} />
  if (data.error) return <ErrorState message={data.error} onRetry={data.reload} compact />
  const h = data.data
  if (!h) return null
  if (!h.available)
    return (
      <p className="flex items-start gap-2 rounded-lg border border-rule bg-panel px-3.5 py-3 text-[13px] leading-relaxed text-ink-mid">
        <Icon name="history" size={16} className="mt-0.5 shrink-0 text-ink-dim" />
        {h.reason}
      </p>
    )
  const window =
    h.window === 'recent'
      ? `${countLabel(h.recent_commits, 'commit')} in the last ${h.days} days`
      : `${countLabel(h.commits, 'commit')}${h.since ? ` since ${date(h.since)}` : ''} (the last ${h.days} days were quiet, so all of it)`
  if (!h.hotspots.length)
    return <p className="text-[13px] text-ink-dim">No file was changed in {window}.</p>
  const max = Math.max(...h.hotspots.map(x => x.changes))
  return (
    <div className="flex flex-col gap-2">
      <p className="text-[12.5px] text-ink-dim">
        Counted from {window}.{' '}
        {h.shallow && <span className="text-warn">The clone had little history, so these are partial.</span>}
      </p>
      <ul className="flex flex-col">
        {h.hotspots.map(f => {
          const kind = kindOf(f.kind)
          return (
            <li key={f.path}>
              <Link
                to={`/app/projects/${projectId}/graph?file=${encodeURIComponent(f.path)}`}
                className="group grid grid-cols-[auto_minmax(0,1.4fr)_minmax(80px,1fr)_auto] items-center gap-3.5 border-b border-rule px-1 py-2.5 transition-colors hover:bg-hover"
                title="Open in the knowledge graph"
              >
                <IconTile icon={kind.icon} color={kind.color} tint size={30} />
                <span className="min-w-0">
                  <span className="flex items-center gap-1.5">
                    {f.level === 'hot' && (
                      <span className="inline-flex shrink-0 items-center gap-0.5 text-[11px] font-semibold text-hot-ink" title="Near the top: changed often and depended on widely">
                        <Icon name="flame" size={12} />
                        hot
                      </span>
                    )}
                    <span className="truncate font-mono text-[12.5px] text-ink">{f.path}</span>
                  </span>
                  <span className="block truncate text-[12px] text-ink-dim">
                    {f.component} · changed in {countLabel(f.changes, 'commit')} · {f.reach} reach it
                  </span>
                </span>
                <span className="flex items-center gap-2" title={`${countLabel(f.changes, 'commit')} touched it`}>
                  <ChangeBar value={f.changes} max={max} />
                  <span className="w-6 shrink-0 text-right font-mono text-[12px] text-ink-mid">{f.changes}</span>
                </span>
                {f.tests ? (
                  <Pill tone="good" icon="flask-conical">
                    {countLabel(f.tests, 'test')}
                  </Pill>
                ) : (
                  <Pill tone="bad" icon="triangle-alert">
                    Untested
                  </Pill>
                )}
              </Link>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

/* ── the timeline ─────────────────────────────────────────────────────── */

type Measure = {
  key: string
  label: string
  icon: IconName
  value: (r: TimelineReading) => number
  /** Whether a rise is bad news; undefined when it is neither. */
  upIsBad?: boolean
}

const MEASURES: Measure[] = [
  { key: 'files', label: 'Files', icon: 'file-code', value: r => r.files },
  { key: 'loc', label: 'Lines of code', icon: 'align-left', value: r => r.loc },
  { key: 'links', label: 'Imports between parts', icon: 'waypoints', value: r => r.links },
  { key: 'backwards', label: 'Links against the columns', icon: 'arrow-left-right', value: r => r.backwards.length, upIsBad: true },
]

/** One measure across readings: a 2px line in the quiet ink, the latest reading
 *  marked in the accent. Each reading is a hit area the full height of the chart. */
function Trend({ readings, measure, onStep }: { readings: TimelineReading[]; measure: Measure; onStep?: (k: number) => void }) {
  const id = useId()
  const [at, setAt] = useState<number | null>(null)
  const W = 160
  const H = 36
  const pad = 5
  const values = readings.map(measure.value)
  const lo = Math.min(...values)
  const hi = Math.max(...values)
  const x = (k: number) => (readings.length === 1 ? W / 2 : pad + (k * (W - 2 * pad)) / (readings.length - 1))
  const y = (v: number) => (hi === lo ? H / 2 : H - pad - ((v - lo) * (H - 2 * pad)) / (hi - lo))
  const d = values.map((v, k) => `${k ? 'L' : 'M'}${x(k).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  const last = values.length - 1
  const slice = readings.length > 1 ? (W - 2 * pad) / (readings.length - 1) : W
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="block h-9 w-full overflow-visible" preserveAspectRatio="none" aria-hidden>
        <path d={d} fill="none" stroke="var(--ink-dim)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
        {at !== null && <line x1={x(at)} x2={x(at)} y1={0} y2={H} stroke="var(--line-2)" strokeWidth={1} vectorEffect="non-scaling-stroke" />}
      </svg>
      {/* Markers in HTML so they stay round however the line is stretched. */}
      {values.map((v, k) =>
        k === last || k === at ? (
          <span
            key={k}
            className={`pointer-events-none absolute size-2 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-panel ${k === last ? 'bg-hot' : 'bg-ink-mid'}`}
            style={{ left: `${(x(k) / W) * 100}%`, top: `${(y(v) / H) * 100}%` }}
          />
        ) : null,
      )}
      <div className="absolute inset-0 flex" onMouseLeave={() => setAt(null)}>
        {readings.map((r, k) => (
          <button
            key={r.kb_id}
            type="button"
            className={`h-full flex-1 outline-none focus-visible:bg-hover/60 ${k > 0 && onStep ? 'cursor-pointer' : 'cursor-default'}`}
            onClick={k > 0 && onStep ? () => onStep(k) : undefined}
            title={k > 0 && onStep ? 'Compare this reading with the one before' : undefined}
            style={readings.length > 1 ? { flexBasis: `${(slice / W) * 100}%` } : undefined}
            onMouseEnter={() => setAt(k)}
            onFocus={() => setAt(k)}
            onBlur={() => setAt(null)}
            aria-describedby={at === k ? id : undefined}
            aria-label={`${measure.label} at ${shortSha(r.commit)}: ${values[k].toLocaleString()}`}
          />
        ))}
      </div>
      {at !== null && (
        <div
          id={id}
          role="tooltip"
          className="atlas-float pointer-events-none absolute bottom-full z-10 mb-1.5 -translate-x-1/2 rounded-md px-2.5 py-1.5 text-[12px] whitespace-nowrap"
          style={{ left: `${(x(at) / W) * 100}%` }}
        >
          <span className="block font-semibold text-ink">{values[at].toLocaleString()}</span>
          <span className="block font-mono text-[11px] text-ink-dim">
            {shortSha(readings[at].commit)} · {date(readings[at].completed_at)}
          </span>
        </div>
      )}
    </div>
  )
}

function Tile({ readings, measure, onStep }: { readings: TimelineReading[]; measure: Measure; onStep?: (k: number) => void }) {
  const now = measure.value(readings[readings.length - 1])
  const before = readings.length > 1 ? measure.value(readings[readings.length - 2]) : null
  const delta = before === null ? null : now - before
  const tone =
    delta === null || delta === 0 || measure.upIsBad === undefined
      ? 'text-ink-mid'
      : (delta > 0) === measure.upIsBad
        ? 'text-bad'
        : 'text-ok'
  return (
    <div className="flex min-w-0 flex-col gap-1.5 rounded-xl border border-rule bg-panel px-3.5 py-3">
      <span className="flex items-center gap-1.5 text-[12.5px] text-ink-mid">
        <Icon name={measure.icon} size={14} className="text-ink-dim" />
        {measure.label}
      </span>
      <span className="flex items-baseline gap-2">
        <span className="font-head text-[22px] leading-none font-semibold text-ink" title={now.toLocaleString()}>
          {compact.format(now)}
        </span>
        {delta !== null && (
          <span className={`inline-flex items-center gap-0.5 text-[12px] font-medium ${tone}`} title="Since the reading before">
            {delta !== 0 && <Icon name={delta > 0 ? 'arrow-up-right' : 'arrow-down-right'} size={12} />}
            {delta === 0 ? 'no change' : `${delta > 0 ? '+' : '−'}${compact.format(Math.abs(delta))}`}
          </span>
        )}
      </span>
      {readings.length > 1 && <Trend readings={readings} measure={measure} onStep={onStep} />}
    </div>
  )
}

export function Timeline({ projectId }: { projectId: number }) {
  const navigate = useNavigate()
  const data = useAsync(sig => api.timeline(projectId, sig), [projectId])
  const [table, setTable] = useState(false)
  if (data.loading) return <SkeletonPanel rows={4} />
  if (data.error) return <ErrorState message={data.error} onRetry={data.reload} compact />
  const readings = data.data?.readings ?? []
  if (!readings.length) return <p className="text-[13px] text-ink-dim">No reading is kept yet.</p>
  const latest = readings[readings.length - 1]
  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
        {MEASURES.map(m => (
          <Tile
            key={m.key}
            readings={readings}
            measure={m}
            onStep={k => navigate(`/app/projects/${projectId}/drift?before=${readings[k - 1].kb_id}&after=${readings[k].kb_id}`)}
          />
        ))}
      </div>

      {readings.length === 1 ? (
        <p className="text-[12.5px] text-ink-dim">
          One reading so far. Each new reading adds a point, and the tiles show what moved since the one before.
        </p>
      ) : latest.new_backwards.length ? (
        <div className="rounded-lg border border-bad/30 bg-bad-wash/40 px-3.5 py-2.5 text-[12.5px] text-ink-mid">
          <span className="font-medium text-ink">New since the reading before: </span>
          {latest.new_backwards.map(([a, b], k) => (
            <span key={`${a}>${b}`}>
              {k ? ', ' : ''}
              <span className="text-ink">{a}</span> now imports <span className="text-ink">{b}</span>
            </span>
          ))}
          .
        </div>
      ) : (
        <p className="text-[12.5px] text-ink-dim">No new link against the columns since the reading before.</p>
      )}

      {latest.backwards.length > 0 && (
        <p className="text-[12.5px] leading-relaxed text-ink-dim">
          Against the columns now:{' '}
          {latest.backwards.map(([a, b], k) => (
            <span key={`${a}>${b}`}>
              {k ? '; ' : ''}
              {a} → {b}
            </span>
          ))}
          .{latest.tangled.length > 0 && ` ${countLabel(latest.tangled.length, 'pair')} of parts import each other.`}
        </p>
      )}

      <button
        type="button"
        onClick={() => setTable(v => !v)}
        aria-expanded={table}
        className="inline-flex w-fit items-center gap-1.5 text-[12.5px] text-ink-mid transition-colors hover:text-ink"
      >
        <Icon name={table ? 'chevron-down' : 'chevron-right'} size={14} />
        Every reading as a table
      </button>
      {table && (
        <div className="overflow-x-auto rounded-lg border border-rule">
          <table className="tbl">
            <thead>
              <tr>
                <th>Commit</th>
                <th>Read</th>
                <th className="text-right">Files</th>
                <th className="text-right">Lines</th>
                <th className="text-right">Imports between parts</th>
                <th className="text-right">Against the columns</th>
              </tr>
            </thead>
            <tbody>
              {[...readings].reverse().map(r => (
                <tr key={r.kb_id}>
                  <td className="font-mono">{shortSha(r.commit)}</td>
                  <td>{formatDateTime(r.completed_at)}</td>
                  <td className="text-right font-mono">{r.files.toLocaleString()}</td>
                  <td className="text-right font-mono">{r.loc.toLocaleString()}</td>
                  <td className="text-right font-mono">{r.links.toLocaleString()}</td>
                  <td className="text-right font-mono">
                    {r.backwards.length}
                    {r.new_backwards.length ? <span className="text-bad"> (+{r.new_backwards.length} new)</span> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
