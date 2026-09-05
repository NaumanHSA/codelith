import { useParams } from 'react-router-dom'
import { api } from '../../lib/api'
import { useAsync } from '../../lib/hooks'
import { EmptyState, ErrorState, SkeletonPanel } from '../../components/States'
import { PageHead, Panel, Stat } from '../../components/ui'
import type { Drift, DriftModule, DriftPageAtRisk } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * What changed between two readings.
 *
 * The pages at risk come first and everything else is context. A list
 * of modules that moved is interesting; "these four pages describe code
 * that is no longer there" is the reason anybody opened this.
 * ------------------------------------------------------------------ */

const CHANGE_TONE: Record<string, string> = {
  added: 'text-ok',
  removed: 'text-[var(--bad)]',
  rewritten: 'text-hot-ink',
  grew: 'text-ink-mid',
  shrank: 'text-ink-mid',
}

function Delta({ n }: { n: number }) {
  if (n === 0) return <span className="tag text-ink-dim">-</span>
  return (
    <span className={`tag tabular-nums ${n > 0 ? 'text-ok' : 'text-[var(--bad)]'}`}>
      {n > 0 ? '+' : ''}
      {n}
    </span>
  )
}

function AtRisk({ page }: { page: DriftPageAtRisk }) {
  return (
    <li className="border-b border-rule px-3 py-2.5 last:border-b-0">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="text-[12.5px] font-semibold text-ink">{page.title}</span>
        <span className="tag text-ink-dim">{page.address}</span>
      </div>
      <p className="mt-1 font-sans text-[12px] leading-relaxed text-ink-mid">{page.reason}</p>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {page.changed_files.map(f => (
          <span key={f} className="tag border border-rule px-1.5 py-0.5 text-ink-dim">
            {f}
          </span>
        ))}
      </div>
    </li>
  )
}

function ModuleRow({ m }: { m: DriftModule }) {
  return (
    <li className="flex items-center gap-3 border-b border-rule px-3 py-2 last:border-b-0">
      <span className={`tag w-[72px] shrink-0 ${CHANGE_TONE[m.change] ?? 'text-ink-dim'}`}>
        {m.change}
      </span>
      <span className="min-w-0 flex-1 truncate text-[12px] text-ink">{m.path}</span>
      <span className="tag shrink-0 tabular-nums text-ink-dim">
        {m.loc_before} → {m.loc_after}
      </span>
      <Delta n={m.loc_delta} />
    </li>
  )
}

export default function DriftPage() {
  const { projectId } = useParams()
  const id = Number(projectId)
  const drift = useAsync<Drift>(s => api.drift(id, s), [id])

  if (drift.loading) return <SkeletonPanel rows={6} />
  if (drift.error) return <ErrorState message={drift.error} />
  const d = drift.data
  if (!d) return null

  return (
    <div className="mx-auto w-full max-w-[1100px] p-5">
      <PageHead
        index="04"
        title="What changed"
        sub={
          d.comparable
            ? `${d.from_commit?.slice(0, 7) ?? '-'} → ${d.to_commit?.slice(0, 7) ?? '-'}`
            : 'Needs two readings'
        }
      />

      {!d.comparable ? (
        <EmptyState
          title="Only one reading so far"
          body={d.summary}
        />
      ) : (
        <div className="mt-3 space-y-3">
          <Panel title="In one sentence" index="01">
            <p className="px-3 py-2.5 font-sans text-[12.5px] leading-relaxed text-ink">
              {d.summary}
            </p>
            <div className="grid grid-cols-3 gap-px border-t border-rule bg-rule">
              <Stat k="modules moved" v={d.modules.length} hot />
              <Stat k="routes & facts" v={d.entities.length} />
              <Stat k="pages at risk" v={d.pages_at_risk.length} />
            </div>
          </Panel>

          {/* First, because it is the only part that says something is wrong. */}
          {d.pages_at_risk.length > 0 && (
            <Panel title="Pages that describe code which moved" index="!!">
              <ul>
                {d.pages_at_risk.map(p => (
                  <AtRisk key={p.address} page={p} />
                ))}
              </ul>
            </Panel>
          )}

          {d.modules.length > 0 && (
            <Panel title="Modules" index="02">
              <ul>
                {d.modules.map(m => (
                  <ModuleRow key={m.path} m={m} />
                ))}
              </ul>
            </Panel>
          )}

          {d.entities.length > 0 && (
            <Panel title="Routes, entrypoints and facts" index="03">
              <ul>
                {d.entities.map(e => (
                  <li
                    key={`${e.kind}:${e.name}`}
                    className="flex items-center gap-3 border-b border-rule px-3 py-2 last:border-b-0"
                  >
                    <span className={`tag w-[72px] shrink-0 ${CHANGE_TONE[e.change]}`}>
                      {e.change}
                    </span>
                    <span className="tag shrink-0 text-ink-dim">{e.kind}</span>
                    <span className="min-w-0 flex-1 truncate text-[12px] text-ink">{e.name}</span>
                    {e.source_path && (
                      <span className="tag shrink-0 text-ink-dim">{e.source_path}</span>
                    )}
                  </li>
                ))}
              </ul>
            </Panel>
          )}
        </div>
      )}
    </div>
  )
}
