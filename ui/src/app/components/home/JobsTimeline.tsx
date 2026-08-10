import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import type { Job } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * Seven days of work, by the hour.
 *
 * This replaced a row of four counters that read "1 · 0 · 1 · 0" on a
 * real installation. Totals since the beginning of time do not say
 * whether anything is happening, and at low counts they teach the
 * reader to skip the row. A week of bars answers the question the
 * counters were pretending to: has this been running, and did it work?
 *
 * One bar an hour rather than one a day. A day-wide bar for a single
 * job is a slab that says nothing about when the work happened, and
 * analysis runs are long enough that the hour is the interesting unit.
 *
 * Failures stack on top of successes rather than sitting beside them,
 * so a bad hour is a red cap on a bar rather than a second bar
 * somewhere else to compare against.
 * ------------------------------------------------------------------ */

const DAYS = 7
const HOURS = 24
const HOUR_MS = 3_600_000

interface Slot {
  start: Date
  ok: number
  bad: number
  live: number
  total: number
}

/** Calendar days, not rolling windows — the labels say "Mon", so the buckets
 *  have to agree with what somebody means by that. */
function bucket(jobs: Job[]): Slot[][] {
  const first = new Date()
  first.setHours(0, 0, 0, 0)
  first.setDate(first.getDate() - (DAYS - 1))

  const days: Slot[][] = []
  for (let d = 0; d < DAYS; d++) {
    const day: Slot[] = []
    for (let h = 0; h < HOURS; h++) {
      const start = new Date(first)
      start.setDate(start.getDate() + d)
      start.setHours(h)
      day.push({ start, ok: 0, bad: 0, live: 0, total: 0 })
    }
    days.push(day)
  }

  for (const j of jobs) {
    const at = new Date(j.created_at)
    // Rounded, not floored: a clock change inside the window makes the
    // difference fractional, and flooring 5.96 buries the job a day early.
    const d = Math.round(
      (new Date(at).setHours(0, 0, 0, 0) - first.getTime()) / (HOURS * HOUR_MS),
    )
    if (d < 0 || d >= DAYS) continue
    const slot = days[d][at.getHours()]
    if (j.status === 'completed') slot.ok++
    else if (j.status === 'failed' || j.status === 'cancelled') slot.bad++
    else slot.live++
    slot.total++
  }
  return days
}

const WEEKDAY = new Intl.DateTimeFormat(undefined, { weekday: 'short' })
const DATE = new Intl.DateTimeFormat(undefined, { weekday: 'short', month: 'short', day: 'numeric' })

export default function JobsTimeline({
  jobs,
  loading,
}: {
  jobs: Job[] | null
  loading: boolean
}) {
  const days = useMemo(() => bucket(jobs ?? []), [jobs])
  const [hover, setHover] = useState<{ d: number; h: number } | null>(null)

  const flat = days.flat()
  const max = Math.max(...flat.map(s => s.total), 1)
  const week = flat.reduce(
    (a, s) => ({ ok: a.ok + s.ok, bad: a.bad + s.bad, live: a.live + s.live }),
    { ok: 0, bad: 0, live: 0 },
  )
  const shown = hover ? days[hover.d][hover.h] : null

  return (
    <section className="plate relative mb-5">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-rule bg-sunk/60 px-3 py-2">
        <h2 className="text-[11.5px] font-semibold tracking-tight text-ink">Jobs</h2>
        <span className="tag text-ink-dim">last 7 days · by hour</span>

        <span className="ml-auto flex items-center gap-3">
          <span className="tag flex items-center gap-1.5 text-ink-dim">
            <span className="block size-[7px] bg-ok" /> {week.ok} completed
          </span>
          <span className="tag flex items-center gap-1.5 text-ink-dim">
            <span className="block size-[7px] bg-bad" /> {week.bad} failed
          </span>
          {week.live > 0 && (
            <span className="tag flex items-center gap-1.5 text-ink-dim">
              <span className="block size-[7px] bg-hot" /> {week.live} running
            </span>
          )}
          <Link to="/app/jobs" className="tag plate-arrow text-hot-ink hover:underline">
            See all jobs →
          </Link>
        </span>
      </header>

      <div className="relative flex items-stretch gap-2.5 px-3 pt-3 pb-2">
        {days.map((day, d) => (
          <div key={d} className="flex min-w-0 flex-1 flex-col">
            <div className="flex h-[42px] items-end gap-px">
              {day.map((s, h) => {
                const active = hover?.d === d && hover.h === h
                return (
                  <div
                    key={h}
                    onMouseEnter={() => setHover({ d, h })}
                    onMouseLeave={() =>
                      setHover(v => (v && v.d === d && v.h === h ? null : v))
                    }
                    // Full-height hit area: an hour with nothing in it is 1px
                    // tall and would otherwise be impossible to point at.
                    className={`flex h-full min-w-0 flex-1 items-end ${
                      active ? 'bg-hot-wash' : ''
                    }`}
                  >
                    {s.total === 0 ? (
                      <span className="block h-px w-full bg-rule" />
                    ) : (
                      <span
                        className="flex w-full flex-col-reverse"
                        style={{ height: `${Math.max((s.total / max) * 100, 12)}%` }}
                      >
                        {s.ok > 0 && (
                          <span
                            className="block w-full bg-ok"
                            style={{ height: `${(s.ok / s.total) * 100}%` }}
                          />
                        )}
                        {s.bad > 0 && (
                          <span
                            className="block w-full bg-bad"
                            style={{ height: `${(s.bad / s.total) * 100}%` }}
                          />
                        )}
                        {s.live > 0 && (
                          <span
                            className="anim-pulse block w-full bg-hot"
                            style={{ height: `${(s.live / s.total) * 100}%` }}
                          />
                        )}
                      </span>
                    )}
                  </div>
                )
              })}
            </div>

            <div
              className={`mt-1.5 truncate border-t pt-1 text-center text-[9.5px] tracking-[0.06em] uppercase ${
                hover?.d === d ? 'border-hot text-hot-ink' : 'border-rule text-ink-dim'
              }`}
            >
              {WEEKDAY.format(day[0].start)}
            </div>
          </div>
        ))}

        {/* The detail only a hover can carry, without a row of numbers under
            every bar that nobody reads on the days they are all zero. */}
        {shown && (
          <div className="pointer-events-none absolute top-1 right-3 border border-ink bg-panel px-2.5 py-1.5 shadow-sm">
            <div className="text-[11px] font-semibold text-ink">
              {DATE.format(shown.start)} ·{' '}
              {String(shown.start.getHours()).padStart(2, '0')}:00
            </div>
            <div className="tag mt-0.5 text-ink-dim">
              {shown.total === 0
                ? 'nothing ran'
                : [
                    shown.ok ? `${shown.ok} completed` : '',
                    shown.bad ? `${shown.bad} failed` : '',
                    shown.live ? `${shown.live} running` : '',
                  ]
                    .filter(Boolean)
                    .join(' · ')}
            </div>
          </div>
        )}
      </div>

      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-panel/70">
          <span className="tag text-ink-dim">loading…</span>
        </div>
      )}
    </section>
  )
}
