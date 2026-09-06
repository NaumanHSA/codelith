import { Link } from 'react-router-dom'
import type { Preflight } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * What this file is connected to.
 *
 * The same pre-flight a connected agent gets from `before_edit`, asked
 * automatically about the file already on screen. The panel on the
 * codebase page makes you type a path first, which is the same failure
 * as putting a check behind its own page: a question you have to phrase
 * is a question nobody asks.
 *
 * Every path is a link back into this viewer, so the graph is walkable
 * rather than merely printed. That is the whole difference between a
 * report and a browser.
 * ------------------------------------------------------------------ */

const RISK: Record<string, string> = {
  high: 'border-bad/40 bg-bad-wash text-bad',
  moderate: 'border-warn/40 bg-warn-wash text-warn',
  low: 'border-ok/40 bg-ok-wash text-ok',
  unknown: 'border-rule bg-sunk text-ink-dim',
}

export default function FileGraph({
  data,
  projectId,
}: {
  data: Preflight
  projectId: number
}) {
  if (!data.found) {
    return (
      <p className="p-3 font-sans text-[11.5px] leading-relaxed text-ink-dim">
        The code graph has no edges for this file. Analysis builds it from the
        languages it has a provider for; a file it indexed as text has content but no
        imports.
      </p>
    )
  }

  const untested = data.tests.length === 0

  // Sized to the lists that exist. A fixed four-column grid with three lists in it
  // shows the rule colour through the empty track, which reads as a broken panel
  // rather than as an absent list. The class names are spelled out because Tailwind
  // scans source text and cannot see a template string.
  const filled =
    (data.imports.length ? 1 : 0) +
    (data.dependents.length ? 1 : 0) +
    (data.callers.length ? 1 : 0) +
    (data.reached.length ? 1 : 0)
  const columns =
    filled >= 4
      ? 'md:grid-cols-2 xl:grid-cols-4'
      : filled === 3
        ? 'md:grid-cols-2 xl:grid-cols-3'
        : filled === 2
          ? 'md:grid-cols-2'
          : ''

  return (
    <div>
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 border-b border-rule px-2.5 py-2">
        <span className={`tag border px-1.5 py-0.5 ${RISK[data.risk] ?? RISK.unknown}`}>
          {data.risk} risk
        </span>
        {/* `reach_weight` itself. It has been the ranking every caller is meant to
            sort on since it moved into the base, and no screen has ever shown it. */}
        <span className="tag tabular-nums text-ink-dim" title="reach_weight: capped reach plus five per written page">
          weight {data.weight}
        </span>
      </div>

      {/* Four independent lists, so they read across rather than down. Stacked
          full-width, six imports one per line leave most of the panel empty and
          push everything below it off the screen. */}
      <div className={`grid grid-cols-1 gap-px bg-rule ${columns}`}>
        <Group
          title="depends on"
          hint="what this file imports"
          paths={data.imports}
          projectId={projectId}
        />
        <Group
          title="imported by"
          hint="breaks first"
          paths={data.dependents}
          projectId={projectId}
        />

        {data.callers.length > 0 && (
          <Section title="called from" count={data.callers.length}>
            {data.callers.slice(0, 40).map(c => (
              <Row key={`${c.file}:${c.symbol}`} projectId={projectId} path={c.file}>
                <span className="text-ink-dim"> :: </span>
                {c.symbol}
              </Row>
            ))}
          </Section>
        )}

        {data.reached.length > 0 && (
          <Section title="reaches it" count={data.reached.length} hint="nearest first">
            {data.reached.slice(0, 40).map(r => (
              <Row
                key={r.path}
                projectId={projectId}
                path={r.path}
                muted={r.is_test}
                right={`${r.distance}`}
              >
                {r.is_test && <span className="ml-1 text-ok">test</span>}
              </Row>
            ))}
          </Section>
        )}
      </div>

      {untested && (
        <p className="border-t border-rule bg-warn-wash px-2.5 py-2 font-sans text-[11px] leading-relaxed text-warn">
          No test file reaches this. A change here is unverified by the suite.
        </p>
      )}

      {data.documented_in.length > 0 && (
        <Section
          title="written about in"
          count={data.documented_in.length}
          hint="would need re-writing"
        >
          {data.documented_in.map(p => (
            <li key={p.address} className="px-2.5 py-[3px] font-mono text-[10.5px] text-ink-mid">
              <span className="text-hot-ink">{p.address}</span>
              <span className="text-ink-dim"> · {p.title}</span>
            </li>
          ))}
        </Section>
      )}

      {data.facts.length > 0 && (
        <Section title="declares" count={data.facts.length}>
          {data.facts.slice(0, 30).map(f => (
            <li key={f} className="px-2.5 py-[3px] font-mono text-[10.5px] text-ink-mid">
              {f}
            </li>
          ))}
        </Section>
      )}
    </div>
  )
}

/** A list of paths, each a link into the viewer. */
function Group({
  title,
  hint,
  paths,
  projectId,
}: {
  title: string
  hint?: string
  paths: string[]
  projectId: number
}) {
  if (!paths.length) return null
  return (
    <Section title={title} count={paths.length} hint={hint}>
      {paths.slice(0, 40).map(p => (
        <Row key={p} projectId={projectId} path={p} />
      ))}
    </Section>
  )
}

function Section({
  title,
  count,
  hint,
  children,
}: {
  title: string
  count: number
  hint?: string
  children: React.ReactNode
}) {
  return (
    <div className="min-w-0 border-t border-rule bg-panel">
      <div className="flex items-baseline gap-1.5 bg-sunk/40 px-2.5 py-1">
        <span className="tag text-ink-dim">{title}</span>
        <span className="tag tabular-nums text-ink-dim">{count}</span>
        {hint && <span className="ml-auto font-sans text-[10px] text-ink-dim">{hint}</span>}
      </div>
      <ul className="max-h-[190px] overflow-y-auto">{children}</ul>
    </div>
  )
}

function Row({
  projectId,
  path,
  muted,
  right,
  children,
}: {
  projectId: number
  path: string
  muted?: boolean
  right?: string
  children?: React.ReactNode
}) {
  return (
    <li className="flex items-baseline gap-1.5 px-2.5 py-[3px]">
      <Link
        to={`/app/projects/${projectId}/code?file=${encodeURIComponent(path)}`}
        title={path}
        className={`min-w-0 flex-1 truncate font-mono text-[10.5px] hover:underline ${
          muted ? 'text-ink-dim' : 'text-ink-mid hover:text-hot-ink'
        }`}
      >
        {path}
        {children}
      </Link>
      {right && (
        <span className="shrink-0 font-mono text-[9.5px] tabular-nums text-ink-dim">{right}</span>
      )}
    </li>
  )
}
