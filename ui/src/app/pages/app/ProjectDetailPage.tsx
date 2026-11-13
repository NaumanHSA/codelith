import AgentGuide from '../../components/projects/AgentGuide'
import { Runbook } from '../../components/projects/Runbook'
import TourInvite from '../../components/projects/TourInvite'
import { Hotspots, Timeline } from '../../components/projects/Health'
import { AutoReadSwitch, Freshness } from '../../components/projects/Freshness'
import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../../lib/api'
import { useAsync } from '../../lib/hooks'
import { useAuth } from '../../auth'
import { useRunningJobs } from '../../running-jobs'
import { BrandMark, languageBrand, sourceBrand } from '../../lib/brands'
import { countLabel, humanize, languageShares, relativeTime, shortSha } from '../../lib/format'
import { Icon, type IconName } from '../../lib/icons'
import { APP_LOOKS, TOPIC_ICONS, brandFor, factKindOf, kindOf, lookOf } from '../../lib/kinds'
import { useFill } from '../../lib/motion'
import type { Fact, Narrative, Project, ProjectApp } from '../../lib/types'
import { Button, Dialog, StatusBadge } from '../../components/ui'
import { CodebaseMark, IconTile, Pill, StatBlock } from '../../components/primitives'
import { EmptyState, ErrorState, SkeletonPanel } from '../../components/States'
import { Markdown } from '../../components/Markdown'
import ReanalyseDialog from '../../components/projects/ReanalyseDialog'
import ModuleExplorer from '../../components/projects/ModuleExplorer'
import ConfirmDelete from '../../components/ConfirmDelete'
import { coverage, describeJobScope } from '../../lib/site'

/* ------------------------------------------------------------------ *
 * A codebase: how fresh the reading is, what is in it, and where it is
 * fragile, above the fold. Then the ways into it (atlas, assistant,
 * changes, library), what it is built with and talks to, every fact the
 * reading found, and the prose analysis wrote.
 *
 * Replaces the 718-line page whose graph, architecture map and module
 * tabs the atlas now does better. The module list stays, below: it is the
 * one place the per-module prose is readable.
 * ------------------------------------------------------------------ */

function Section({
  title,
  sub,
  right,
  children,
  className = '',
}: {
  title: string
  sub?: React.ReactNode
  right?: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  return (
    <section className={`flex min-w-0 flex-col gap-3.5 ${className}`}>
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-[17px] font-semibold text-ink">{title}</h2>
          {sub && <p className="mt-1 max-w-[70ch] text-[13px] text-ink-mid">{sub}</p>}
        </div>
        {right}
      </header>
      {children}
    </section>
  )
}

/* ── header ──────────────────────────────────────────────────────────── */

/* ── the ways in ─────────────────────────────────────────────────────── */

function WaysIn({ projectId, apps, files }: { projectId: number; apps: ProjectApp[]; files: number | null }) {
  const site = useAsync(s => api.site(projectId, null, s), [projectId])
  const qa = useAsync(s => api.findingsMap(projectId, s), [projectId])
  const qaOpen = Object.values(qa.data?.open ?? {}).reduce((a, b) => a + (b ?? 0), 0)
  const qaWorst = (['critical', 'high'] as const).filter(s => qa.data?.open[s]).map(s => `${qa.data!.open[s]} ${s}`)
  const c = coverage(site.data ?? null)
  const app = (id: string) => apps.find(a => a.id === id)
  const look = (k: keyof typeof APP_LOOKS) => ({ icon: APP_LOOKS[k].icon as IconName, color: APP_LOOKS[k].color as string, title: APP_LOOKS[k].label as string })
  const rows: { icon: IconName; color: string; title: string; line: string; to: string | null; reason?: string }[] = [
    {
      ...look('graph'),
      line: files ? `${files.toLocaleString()} files on a map, and what breaks if each one changes` : 'Every file on a map',
      to: `/app/projects/${projectId}/graph`,
    },
    {
      ...look('assistant'),
      line: app('ask')?.short ?? 'Ask the code, with checked citations',
      to: app('ask')?.state === 'available' ? app('ask')!.route : null,
      reason: app('ask')?.reason,
    },
    {
      ...look('changes'),
      line: app('drift')?.short ?? 'What moved between two readings',
      to: app('drift')?.state === 'available' ? app('drift')!.route : null,
      reason: app('drift')?.reason,
    },
    {
      ...look('qa'),
      line: qa.data?.checked.length
        ? `${qaOpen} open${qaWorst.length ? ` (${qaWorst.join(', ')})` : ''} in ${qa.data.checked.length} of 8 areas checked`
        : app('qa')?.short ?? 'Security, leaks, error handling, deployment and test gaps',
      to: app('qa')?.state === 'available' ? app('qa')!.route : null,
      reason: app('qa')?.reason,
    },
    {
      ...look('documentation'),
      line:
        site.data && site.data.sections.length
          ? `${c.pct}% of ${c.total - c.orphaned} planned pages written`
          : app('documentation')?.short ?? 'Documentation written from the reading',
      to: app('documentation')?.state === 'available' ? app('documentation')!.route : null,
      reason: app('documentation')?.reason,
    },
  ]
  return (
    <div className="grid grid-cols-1 overflow-hidden rounded-xl border border-rule sm:grid-cols-2 xl:grid-cols-5">
      {rows.map((r, i) => {
        const body = (
          <>
            <IconTile icon={r.icon} color={r.color} tint size={38} />
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-1.5 text-[14px] font-medium text-ink">
                {r.title}
                {r.to && <Icon name="arrow-right" size={14} className="plate-arrow text-ink-dim transition-transform" />}
              </span>
              <span className="mt-0.5 block text-[12.5px] leading-snug text-ink-mid">{r.to ? r.line : r.reason || r.line}</span>
            </span>
          </>
        )
        const cls = `plate-lift flex items-start gap-3 p-4 transition-colors ${i ? 'border-t border-rule sm:border-t-0 sm:border-l' : ''} ${
          r.to ? 'hover:bg-hover' : 'opacity-60'
        }`
        return r.to ? (
          <Link key={r.title} to={r.to} className={cls}>
            {body}
          </Link>
        ) : (
          <div key={r.title} className={cls}>
            {body}
          </div>
        )
      })}
    </div>
  )
}

/* ── where an edit would hurt ────────────────────────────────────────── */

function ReachBar({ value, max }: { value: number; max: number }) {
  const pct = useFill(max ? (value / max) * 100 : 0)
  return (
    <span className="block h-1.5 w-full overflow-hidden rounded-full bg-rule">
      <span className="block h-full rounded-full bg-hot transition-[width] duration-[420ms]" style={{ width: `${pct}%` }} />
    </span>
  )
}

function RiskList({ projectId }: { projectId: number }) {
  const risk = useAsync(sig => api.risk(projectId, 12, sig), [projectId])
  if (risk.loading) return <SkeletonPanel rows={6} />
  if (risk.error) return <ErrorState message={risk.error} onRetry={risk.reload} compact />
  const files = risk.data?.files ?? []
  if (!files.length) return <p className="text-[13px] text-ink-dim">Nothing imports anything else, so nothing is at risk from an edit.</p>
  const max = Math.max(...files.map(f => f.reach))
  return (
    <ul className="flex flex-col">
      {files.map(f => {
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
                <span className="block truncate font-mono text-[12.5px] text-ink">{f.path}</span>
                <span className="block truncate text-[12px] text-ink-dim">
                  {f.component} · {f.direct} import it, {f.reach} reach it
                  {f.pages ? ` · ${countLabel(f.pages, 'page')} cite it` : ''}
                </span>
              </span>
              <ReachBar value={f.reach} max={max} />
              {f.tests ? (
                <Pill tone={f.level === 'high' ? 'warn' : 'good'} icon="flask-conical">
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
  )
}

/* ── built with, talks to ────────────────────────────────────────────── */

function Chip({ brand, icon, color, title, small }: { brand?: ReturnType<typeof brandFor>; icon?: IconName; color?: string; title: string; small?: string }) {
  return (
    <span className="inline-flex h-[34px] items-center gap-2 rounded-lg border border-rule bg-panel pr-3 pl-2 text-[13px] font-medium text-ink">
      {brand ? <BrandMark name={brand} size={16} decorative /> : <Icon name={icon ?? 'package'} size={16} style={{ color: color ?? 'var(--ink-mid)' }} />}
      {title}
      {small && <small className="font-mono text-[11.5px] font-normal text-ink-dim">{small}</small>}
    </span>
  )
}

function BuiltWith({ project, projectId }: { project: Project; projectId: number }) {
  const arch = useAsync(sig => api.architecture(projectId, sig), [projectId])
  const shares = languageShares(project.sources?.[0]?.config_json?.probe?.languages)
  const stack = arch.data?.available ? arch.data.tech_stack : null
  const named = [...(stack?.frameworks ?? []), ...(stack?.databases ?? []), ...(stack?.infra ?? [])]
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-2">
        {shares.slice(0, 4).map(l => (
          <Chip key={l.name} brand={languageBrand(l.name)} title={humanize(l.name)} small={`${Math.round(l.pct)}%`} />
        ))}
        {named.map(n => (
          <Chip key={n} brand={brandFor(n)} icon="package" title={n} />
        ))}
      </div>
      {!!(arch.data?.available && (arch.data.patterns.length || arch.data.layers.length)) && (
        <div className="flex flex-wrap items-center gap-1.5 text-[12.5px] text-ink-dim">
          {arch.data.layers.length > 0 && <span className="tag mr-1">Layers</span>}
          {arch.data.layers.map(l => (
            <Pill key={l.name}>{l.name}</Pill>
          ))}
          {arch.data.patterns.length > 0 && <span className="tag mr-1 ml-2">Patterns</span>}
          {arch.data.patterns.map(p => (
            <Pill key={p}>{p}</Pill>
          ))}
        </div>
      )}
    </div>
  )
}

function atlasAt(projectId: number, path: string | null, line: number | null) {
  return path
    ? `/app/projects/${projectId}/graph?file=${encodeURIComponent(path)}${line ? `&line=${line}` : ''}`
    : null
}

function TalksTo({ projectId }: { projectId: number }) {
  const facts = useAsync(sig => api.facts(projectId, ['datastore', 'external_api'], sig), [projectId])
  if (facts.loading) return <SkeletonPanel rows={2} />
  const items = facts.data?.items ?? []
  if (!items.length) return <p className="text-[13px] text-ink-dim">The reading found no datastore and no outside service.</p>
  return (
    <div className="flex flex-wrap gap-2">
      {items.map(f => {
        const look = lookOf({ kind: f.kind === 'datastore' ? 'store' : 'external', fact: f.kind, path: f.name })
        const color = factKindOf(f.kind).color
        const to = atlasAt(projectId, f.source_path, f.source_line)
        const chip = (
          <Chip
            brand={look.brand}
            icon={look.icon}
            color={color}
            title={f.name}
            small={typeof f.data.engine === 'string' ? (f.data.engine as string) : f.kind === 'datastore' ? 'datastore' : 'service'}
          />
        )
        return to ? (
          <Link key={`${f.kind}:${f.name}`} to={to} title={`Used in ${f.source_path}${f.source_line ? `:${f.source_line}` : ''}`} className="rounded-lg transition-opacity hover:opacity-80">
            {chip}
          </Link>
        ) : (
          <span key={`${f.kind}:${f.name}`}>{chip}</span>
        )
      })}
    </div>
  )
}

/* ── what the reading found ──────────────────────────────────────────── */

function Ring({ kinds, selected, onSelect }: { kinds: [string, number][]; selected: string | null; onSelect: (k: string | null) => void }) {
  const total = kinds.reduce((n, [, v]) => n + v, 0)
  const R = 104
  const C = 130
  const gap = 0.03
  let a = 0
  const spans = kinds.map(([k, n]) => {
    const span = Math.max(0.06, (n / total) * Math.PI * 2)
    const o = { k, n, a0: a, a1: a + span }
    a += span
    return o
  })
  const sc = (Math.PI * 2) / a
  const shown = selected ? kinds.find(([k]) => k === selected) : null
  return (
    <svg viewBox="0 0 260 260" className="w-full max-w-[260px]" role="img" aria-label={`${total} facts, by kind`}>
      {spans.map(o => {
        const s = -Math.PI / 2 + o.a0 * sc + gap / 2
        const e = -Math.PI / 2 + o.a1 * sc - gap / 2
        const big = e - s > Math.PI ? 1 : 0
        const on = selected === o.k
        return (
          <path
            key={o.k}
            d={`M${C + R * Math.cos(s)} ${C + R * Math.sin(s)}A${R} ${R} 0 ${big} 1 ${C + R * Math.cos(e)} ${C + R * Math.sin(e)}`}
            fill="none"
            stroke={factKindOf(o.k).color}
            strokeWidth={on ? 28 : 24}
            opacity={selected === null || on ? 1 : 0.25}
            className="cursor-pointer transition-[opacity,stroke-width] duration-200"
            onClick={() => onSelect(on ? null : o.k)}
          >
            <title>
              {o.n} {factKindOf(o.k).plural.toLowerCase()}
            </title>
          </path>
        )
      })}
      <text x={C} y={C + 6} textAnchor="middle" className="fill-ink" style={{ font: '600 40px Geist, Inter, sans-serif' }}>
        {shown ? shown[1] : total}
      </text>
      <text x={C} y={C + 30} textAnchor="middle" className="fill-ink-mid" style={{ font: '500 12px Inter, sans-serif' }}>
        {shown ? factKindOf(shown[0]).plural.toLowerCase() : 'facts'}
      </text>
    </svg>
  )
}

function FactList({ projectId, kind }: { projectId: number; kind: string }) {
  const facts = useAsync(sig => api.facts(projectId, [kind], sig), [projectId, kind])
  if (facts.loading) return <SkeletonPanel rows={4} />
  if (facts.error) return <ErrorState message={facts.error} compact />
  const items = facts.data?.items ?? []
  const detail = (f: Fact) => {
    for (const k of ['method', 'path', 'version', 'engine', 'client', 'via', 'purpose', 'framework', 'type']) {
      const v = f.data[k]
      if (typeof v === 'string' && v && v !== f.name) return v
    }
    return null
  }
  return (
    <div className="flex flex-col">
      <ul className="max-h-[360px] overflow-y-auto">
        {items.map((f, i) => {
          const to = atlasAt(projectId, f.source_path, f.source_line)
          return (
            <li key={`${f.name}-${i}`} className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-3 border-b border-rule py-2 text-[13px]">
              <span className="min-w-0">
                <span className="font-mono text-[12.5px] break-all text-ink">{f.name}</span>
                {detail(f) && <span className="ml-2 text-[12px] text-ink-dim">{detail(f)}</span>}
              </span>
              {f.source_path &&
                (to ? (
                  <Link to={to} className="truncate font-mono text-[11.5px] text-ink-dim hover:text-hot-ink" title="Open in the knowledge graph">
                    {f.source_path.split('/').pop()}
                    {f.source_line ? `:${f.source_line}` : ''}
                  </Link>
                ) : null)}
            </li>
          )
        })}
      </ul>
      {facts.data?.truncated && <p className="pt-2 text-[12px] text-ink-dim">Showing the first {items.length}.</p>}
    </div>
  )
}

function FactsFound({ projectId }: { projectId: number }) {
  const facts = useAsync(sig => api.facts(projectId, [], sig), [projectId])
  const [selected, setSelected] = useState<string | null>(null)
  const kinds = useMemo(
    () => Object.entries(facts.data?.kinds ?? {}).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1]),
    [facts.data],
  )
  if (facts.loading) return <SkeletonPanel rows={4} />
  if (!kinds.length) return <p className="text-[13px] text-ink-dim">No facts were extracted.</p>
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 items-center gap-6 md:grid-cols-[220px_minmax(0,1fr)]">
        <Ring kinds={kinds} selected={selected} onSelect={setSelected} />
        <div className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-x-4 gap-y-0.5">
          {kinds.map(([k, n]) => {
            const fk = factKindOf(k)
            const on = selected === k
            return (
              <button
                key={k}
                type="button"
                aria-pressed={on}
                onClick={() => setSelected(on ? null : k)}
                className={`flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-left text-[13px] transition-colors ${
                  on ? 'bg-sunk text-ink shadow-[inset_0_0_0_1px_var(--line-2)]' : 'text-ink-mid hover:bg-hover hover:text-ink'
                }`}
              >
                <IconTile icon={fk.icon} color={fk.color} tint size={26} />
                {fk.plural}
                <b className="ml-auto font-mono text-[12.5px] text-ink tabular-nums">{n}</b>
              </button>
            )
          })}
        </div>
      </div>
      {selected && <FactList projectId={projectId} kind={selected} />}
    </div>
  )
}

/* ── written by analysis ─────────────────────────────────────────────── */

function NarrativeList({ projectId }: { projectId: number }) {
  const narratives = useAsync(sig => api.narratives(projectId, sig), [projectId])
  const [open, setOpen] = useState<Narrative | null>(null)
  if (narratives.loading) return <SkeletonPanel rows={3} />
  if (!narratives.data?.available || !narratives.data.narratives.length)
    return <p className="text-[13px] text-ink-dim">This reading has no narratives.</p>
  return (
    <>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(230px,1fr))] gap-x-6">
        {narratives.data.narratives.map(n => (
          <button
            key={n.topic}
            type="button"
            onClick={() => setOpen(n)}
            title={n.brief}
            className="flex items-center gap-2.5 border-b border-rule px-1 py-2.5 text-left transition-colors hover:bg-hover"
          >
            <IconTile icon={TOPIC_ICONS[n.topic] ?? 'file-text'} size={28} />
            <span className="min-w-0 flex-1 truncate text-[13.5px] text-ink">{n.title || humanize(n.topic)}</span>
            <small className="font-mono text-[11.5px] text-ink-dim">{n.words.toLocaleString()} words</small>
          </button>
        ))}
      </div>
      <Dialog open={!!open} onClose={() => setOpen(null)} title={open?.title || humanize(open?.topic ?? '')} width={860}>
        {open && (
          <div className="doc max-h-[70vh] overflow-y-auto">
            <Markdown>{open.content_md}</Markdown>
            {!!open.provenance?.modules?.length && (
              <p className="mt-4 border-t border-rule pt-3 text-[12px] text-ink-dim">
                Written from {countLabel(open.provenance.modules.length, 'module')}
                {open.provenance.facts?.length ? ` and ${countLabel(open.provenance.facts.length, 'fact')}` : ''}.
              </p>
            )}
          </div>
        )}
      </Dialog>
    </>
  )
}

/* ── the page ────────────────────────────────────────────────────────── */

export default function ProjectDetailPage() {
  const { projectId } = useParams()
  const id = Number(projectId)
  const navigate = useNavigate()
  const { can } = useAuth()
  const { track } = useRunningJobs()

  const project = useAsync(() => api.project(id), [id])
  const kb = useAsync(s => api.knowledgeBase(id, s), [id])
  const jobs = useAsync(() => api.projectJobs(id, 6, 0), [id])
  const apps = useAsync(sig => api.projectApps(id, sig), [id])
  const modules = useAsync(sig => api.modules(id, sig), [id])

  const [analysing, setAnalysing] = useState(false)
  const [analyseError, setAnalyseError] = useState<string | null>(null)
  const [doomed, setDoomed] = useState(false)
  const [confirmingReanalyse, setConfirmingReanalyse] = useState(false)
  const [showModules, setShowModules] = useState(false)
  const canRun = can('manager')

  const startAnalysis = async (force: boolean) => {
    setAnalysing(true)
    setAnalyseError(null)
    try {
      const job = await api.analyze(id, force)
      track(job, project.data?.name)
      navigate(`/app/projects/${id}/jobs/${job.id}`)
    } catch (e) {
      setAnalyseError(e instanceof ApiError ? e.message : 'Could not start analysis.')
      setAnalysing(false)
      setConfirmingReanalyse(false)
    }
  }

  if (project.loading)
    return (
      <div className="w-full px-6 py-5">
        <SkeletonPanel rows={6} />
      </div>
    )
  if (project.error || !project.data)
    return (
      <div className="w-full px-6 py-5">
        <ErrorState message={project.error ?? 'Codebase not found.'} onRetry={project.reload} />
      </div>
    )

  const p = project.data
  const base = kb.data?.knowledge_base
  const neverAnalysed = !kb.loading && !kb.error && !kb.data
  const source = p.sources?.[0]
  const probe = source?.config_json?.probe
  const host = sourceBrand(source?.source_type)
  const files = probe?.analysable_files ?? probe?.file_count ?? null
  const factCount = Object.values(kb.data?.entity_kinds ?? {}).reduce((a, b) => a + b, 0) || kb.data?.entity_count || 0

  return (
    <div className="flex w-full flex-col gap-8 px-6 py-6">
      <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-4">
        <div className="flex min-w-0 items-start gap-4">
          <span className="grid size-[52px] shrink-0 place-items-center rounded-[14px] bg-sunk shadow-[inset_0_0_0_1px_var(--line-2)]">
            <CodebaseMark project={p} size={26} />
          </span>
          <div className="min-w-0">
            <h1 className="text-[26px] leading-tight font-semibold text-ink">{p.name}</h1>
            {p.description && <p className="mt-1 max-w-[80ch] text-[13.5px] text-ink-mid">{p.description}</p>}
            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[12.5px] text-ink-mid">
              {source && (
                <a
                  href={source.source_type === 'local' ? undefined : source.url_or_path}
                  target="_blank"
                  rel="noreferrer"
                  className="flex min-w-0 items-center gap-1.5 hover:text-ink"
                >
                  {host ? <BrandMark name={host} size={14} decorative /> : <Icon name="folder" size={14} />}
                  <span className="max-w-[420px] truncate font-mono">{source.url_or_path}</span>
                </a>
              )}
              <span className="flex items-center gap-1.5">
                <Icon name="git-branch" size={14} className="text-ink-dim" />
                {source?.branch ?? 'default branch'}
              </span>
              {base?.commit_sha && (
                <span className="flex items-center gap-1.5 font-mono">
                  <Icon name="git-commit-horizontal" size={14} className="text-ink-dim" />
                  {shortSha(base.commit_sha)}
                </span>
              )}
              {base && <Freshness projectId={id} project={p} sha={base.commit_sha} />}
              {canRun && source?.source_type === 'local' && <AutoReadSwitch projectId={id} source={source} />}
            </div>
          </div>
        </div>
        {canRun && (
          <div className="flex flex-wrap gap-2">
            {base && (
              <Link
                to={`/app/projects/${id}/review`}
                className="inline-flex items-center gap-2 rounded-lg border border-line-2 bg-sunk px-3.5 py-[7px] text-[13px] font-medium text-ink transition-colors hover:bg-hover"
                title="Check a change against what Codelith knows, before it is merged"
              >
                <Icon name="list-checks" size={15} /> Review a change
              </Link>
            )}
            {base && (
              <Link
                to={`/app/projects/${id}/graph`}
                className="inline-flex items-center gap-2 rounded-lg border border-line-2 bg-sunk px-3.5 py-[7px] text-[13px] font-medium text-ink transition-colors hover:bg-hover"
              >
                <Icon name="waypoints" size={15} /> Open the knowledge graph
              </Link>
            )}
            {!neverAnalysed ? (
              <Button variant="hot" onClick={() => setConfirmingReanalyse(true)} disabled={analysing}>
                <Icon name="refresh-cw" size={15} /> Read again
              </Button>
            ) : (
              <Button variant="hot" onClick={() => startAnalysis(false)} disabled={analysing}>
                <Icon name="play" size={15} /> {analysing ? 'Starting…' : 'Analyse'}
              </Button>
            )}
            <button
              type="button"
              onClick={() => setDoomed(true)}
              title="Delete this codebase"
              aria-label="Delete this codebase"
              className="grid size-[34px] place-items-center rounded-lg border border-line-2 text-ink-dim transition-colors hover:border-bad/50 hover:bg-bad-wash hover:text-bad"
            >
              <Icon name="trash" size={15} />
            </button>
          </div>
        )}
      </header>

      <ReanalyseDialog
        open={confirmingReanalyse}
        projectId={id}
        starting={analysing}
        onClose={() => setConfirmingReanalyse(false)}
        onConfirm={force => void startAnalysis(force)}
      />
      <ConfirmDelete
        open={doomed}
        onClose={() => setDoomed(false)}
        onConfirm={async () => {
          await api.deleteProject(id)
          navigate('/app/projects')
        }}
        title={`Delete ${p.name}`}
        actionLabel="Delete everything"
        confirmText={p.name}
        body={
          <>
            <p>
              This removes the codebase and everything derived from it: its knowledge base, every
              job, every document, and the whole documentation site with its pages and versions.
            </p>
            <p className="mt-2">The repository is untouched. Nothing here can be recovered.</p>
          </>
        }
      />

      {analyseError && <ErrorState message={analyseError} compact />}
      {kb.loading && <SkeletonPanel rows={5} />}
      {kb.error && <ErrorState message={kb.error} onRetry={kb.reload} />}

      {neverAnalysed && (
        <EmptyState
          title="This repository has not been read yet"
          body="Analysis walks every file once and builds the knowledge base every app reads: modules, routes, dependencies, environment variables, and prose about how it fits together. Nothing is written until you ask for it."
          action={
            canRun ? (
              <Button variant="hot" onClick={() => startAnalysis(false)} disabled={analysing}>
                <Icon name="play" size={15} /> {analysing ? 'Starting…' : 'Analyse this repository'}
              </Button>
            ) : (
              <span className="text-[12.5px] text-ink-dim">The manager role can start an analysis.</span>
            )
          }
        />
      )}

      {kb.data && base && (
        <>
          {base.error_message && (
            <div className="flex items-start gap-2.5 rounded-lg border border-bad/35 bg-bad-wash px-4 py-3 text-[13px]">
              <Icon name="circle-x" size={16} className="mt-0.5 text-bad" />
              <div>
                <p className="font-medium text-bad">Analysis reported a problem</p>
                <p className="mt-1 text-ink">{base.error_message}</p>
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 gap-x-6 border-y border-rule sm:grid-cols-3 lg:grid-cols-5">
            {files != null && <StatBlock value={files} label="files read" icon="file-code" />}
            <StatBlock value={kb.data.module_count} label="modules" icon="layers" />
            <StatBlock value={factCount} label="facts" icon="hash" />
            <StatBlock value={base.stats?.indexed_chunks ?? 0} label="chunks indexed for search" icon="database" />
            <StatBlock value={p.stats?.page_count ?? 0} label="pages written" icon="book-open" />
          </div>

          <TourInvite projectId={id} />

          {apps.data && <WaysIn projectId={id} apps={apps.data} files={files} />}

          <Section
            title="How to run it"
            sub="What it needs, and how to install, run and test it, each from the file that says so. The environment it reads, against what any file declares."
          >
            <Runbook projectId={id} />
          </Section>

          <div className="grid grid-cols-1 gap-x-10 gap-y-10 2xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
            <Section
              title="Where an edit would hurt"
              sub="Files ranked by how much of the code reaches them within three hops, and whether any test does. Each opens in the knowledge graph."
            >
              <RiskList projectId={id} />
            </Section>

            <div className="flex min-w-0 flex-col gap-10">
              <Section title="Built with" sub="Languages from the files themselves; frameworks, datastores and infrastructure as the architecture pass named them.">
                <BuiltWith project={p} projectId={id} />
              </Section>
              <Section title="What it talks to" sub="Datastores and outside services the code reaches. Each opens the line that does it.">
                <TalksTo projectId={id} />
              </Section>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-x-10 gap-y-10 2xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
            <Section
              title="Where danger collects"
              sub="Files that changed most often, weighted by how much of the code depends on them and whether a test reaches them. Each opens in the knowledge graph."
            >
              <Hotspots projectId={id} />
            </Section>
            <Section
              title="Over time"
              sub="Each kept reading: how big the code is, how many imports run between parts, and how many run against the columns. A point opens what changed at that step."
              right={
                <Link to={`/app/projects/${id}/history`} className="inline-flex items-center gap-1.5 text-[12.5px] text-ink-mid transition-colors hover:text-ink">
                  <Icon name="history" size={14} /> Every reading
                </Link>
              }
            >
              <Timeline projectId={id} />
            </Section>
          </div>

          <Section title="What the reading found" sub="Every fact analysis extracted, by kind. Select one to list them with where each is declared.">
            <FactsFound projectId={id} />
          </Section>

          <Section title="Written by analysis" sub="Prose about how the codebase fits together, written once per reading and reused by every app.">
            <NarrativeList projectId={id} />
          </Section>

          <Section
            title="For coding agents"
            sub="The file an agent reads first, written from this reading: what the codebase is, its parts and which way imports run, how to run it, how things are done here, and the files to edit with care."
          >
            <AgentGuide projectId={id} />
          </Section>

          {modules.data?.available && (
            <Section
              title="Modules"
              sub={`${modules.data.modules.length} modules, each with the summary analysis wrote for it.`}
              right={
                <button
                  type="button"
                  onClick={() => setShowModules(v => !v)}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-line-2 px-3 py-1.5 text-[12.5px] font-medium text-ink-mid transition-colors hover:bg-hover hover:text-ink"
                >
                  <Icon name={showModules ? 'chevron-down' : 'chevron-right'} size={14} />
                  {showModules ? 'Hide' : 'Show'} the list
                </button>
              }
            >
              {showModules && (
                <div className="overflow-hidden rounded-xl border border-rule">
                  <ModuleExplorer data={modules.data} projectId={id} />
                </div>
              )}
            </Section>
          )}
        </>
      )}

      <Section
        title="Recent runs"
        right={
          <Link to={`/app/jobs?project=${p.id}`} className="flex items-center gap-1 text-[12.5px] text-ink-mid hover:text-ink">
            All {p.stats?.job_count ?? 0} <Icon name="chevron-right" size={14} />
          </Link>
        }
      >
        {jobs.loading && <SkeletonPanel rows={3} />}
        {!jobs.loading && !jobs.data?.length && <p className="text-[13px] text-ink-dim">Nothing has run yet.</p>}
        <ul className="flex flex-col">
          {(jobs.data ?? []).map(j => (
            <li key={j.id}>
              <Link
                to={`/app/projects/${p.id}/jobs/${j.id}`}
                className="flex items-center gap-3 border-b border-rule px-1 py-2.5 transition-colors hover:bg-hover"
              >
                <IconTile icon={j.job_type === 'analysis' ? 'radar' : 'pencil'} size={30} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13.5px] font-medium text-ink">
                    {humanize(j.job_type)} <span className="font-mono text-[12px] font-normal text-ink-dim">#{j.id}</span>
                  </span>
                  <span className="block truncate text-[12px] text-ink-dim">
                    {describeJobScope(j) ?? relativeTime(j.created_at)}
                  </span>
                </span>
                <StatusBadge status={j.status} />
              </Link>
            </li>
          ))}
        </ul>
      </Section>
    </div>
  )
}
