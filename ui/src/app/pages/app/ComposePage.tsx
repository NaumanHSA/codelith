import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../../lib/api'
import { useAsync } from '../../lib/hooks'
import { useAuth } from '../../auth'
import { useRunningJobs } from '../../running-jobs'
import { countLabel, relativeTime } from '../../lib/format'
import { confidenceLabel, docTypeMeta, DOC_TYPES, OUTPUT_FORMATS } from '../../lib/docTypes'
import { coverage, isPending } from '../../lib/site'
import type { DocType, OutputFormat, SitePage } from '../../lib/types'
import { Button, Chip, Eyebrow, Meter, PageHead, Panel } from '../../components/ui'
import { EmptyState, ErrorState, SkeletonPanel } from '../../components/States'

/* ------------------------------------------------------------------ *
 * What is missing, and what to write next.
 *
 * Composition used to be a picker bolted to the bottom of the project
 * page — a menu of document types with no memory of what had already
 * been written. This is the other way round: it opens on the *state of
 * the documentation*, and the actions come out of the gaps.
 *
 * Anything already written is greyed but still selectable, because
 * rewriting a page against a newer commit is a normal thing to want —
 * it just should not be the default.
 * ------------------------------------------------------------------ */

export default function ComposePage() {
  const { projectId } = useParams()
  const id = Number(projectId)
  const navigate = useNavigate()
  const { can } = useAuth()
  const { track } = useRunningJobs()

  const project = useAsync(() => api.project(id), [id])
  const kb = useAsync(s => api.knowledgeBase(id, s), [id])
  const site = useAsync(s => api.site(id, null, s), [id])

  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [formats, setFormats] = useState<OutputFormat[]>(['markdown'])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const canRun = can('manager')
  const cov = useMemo(() => coverage(site.data ?? null), [site.data])

  /** Every page of the site, flattened, with what state it is in. */
  const pages = useMemo(
    () =>
      (site.data?.sections ?? []).flatMap(s =>
        s.pages.map(p => ({ page: p, section: s, address: `${s.slug}/${p.slug}` })),
      ),
    [site.data],
  )
  const gaps = pages.filter(p => isPending(p.page.status))
  const stale = pages.filter(p => p.page.status === 'stale')
  const done = pages.filter(p => p.page.status === 'ready')

  const toggle = (address: string) =>
    setPicked(prev => {
      const next = new Set(prev)
      if (next.has(address)) next.delete(address)
      else next.add(address)
      return next
    })

  const start = async (slugs: string[]) => {
    if (!slugs.length) return
    setBusy(true)
    setError(null)
    try {
      const job = await api.compose(id, {
        page_slugs: slugs,
        output_formats: formats,
        human_review: false,
      })
      track(job, project.data?.name)
      navigate(`/app/projects/${id}/jobs/${job.id}`)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not start writing.')
      setBusy(false)
    }
  }

  if (project.loading || site.loading || kb.loading) {
    return (
      <div className="mx-auto max-w-[1100px] p-5">
        <SkeletonPanel rows={8} />
      </div>
    )
  }

  const noKb = !kb.data
  const noSite = !site.data || !site.data.sections.length

  return (
    <div className="mx-auto max-w-[1100px] p-5">
      <PageHead
        index="→"
        title="Compose"
        sub={
          noSite
            ? 'Nothing planned yet.'
            : `${cov.ready + cov.stale} of ${cov.total - cov.orphaned} pages written · ${countLabel(gaps.length, 'gap')}`
        }
        back={{
          label: `back to ${project.data?.name ?? 'project'}`,
          onClick: () => navigate(`/app/projects/${id}`),
        }}
        right={
          !noSite ? (
            <Button variant="ghost" onClick={() => navigate(`/app/projects/${id}/docs`)}>
              Read the site →
            </Button>
          ) : null
        }
      />

      {error && <ErrorState message={error} compact />}

      {noKb && (
        <EmptyState
          title="This project has not been analysed"
          body="Nothing can be written until the codebase has been read. Analysis extracts the modules, routes and dependencies every page is written from, and proposes the site's shape."
          action={
            <Button variant="hot" onClick={() => navigate(`/app/projects/${id}`)}>
              Go and analyse it
            </Button>
          }
        />
      )}

      {!noKb && noSite && (
        <EmptyState
          title="No pages planned yet"
          body="This project was analysed before the site planner existed, so there is no map to write into. Re-analysing proposes one."
          action={
            <Button variant="hot" onClick={() => navigate(`/app/projects/${id}`)}>
              Re-analyse
            </Button>
          }
        />
      )}

      {!noSite && (
        <>
          {/* ── where the documentation stands ──────────────────────── */}
          <Panel title="Where this is" index="01">
            <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-3 py-3">
              <span className="flex items-center gap-2">
                <Meter pct={cov.pct} segments={26} />
                <span className="text-[13px] font-semibold text-ink">{cov.pct}%</span>
              </span>
              <Legend n={cov.ready} label="written" tone="bg-ok" />
              <Legend n={cov.stale} label="out of date" tone="bg-warn" />
              <Legend n={cov.generating} label="writing now" tone="bg-hot" />
              <Legend n={cov.failed} label="failed" tone="bg-bad" />
              <Legend n={cov.planned} label="not written" tone="bg-rule" />
            </div>
          </Panel>

          {/* ── what to write next ──────────────────────────────────── */}
          <div className="mt-3">
            <Panel
              title="What to write next"
              index="02"
              action={
                <span className="tag text-ink-dim">
                  {picked.size ? countLabel(picked.size, 'page') + ' selected' : 'nothing selected'}
                </span>
              }
            >
              <div className="p-3">
                {stale.length > 0 && (
                  <>
                    <Eyebrow right={
                      canRun && (
                        <button
                          onClick={() => setPicked(new Set(stale.map(p => p.address)))}
                          className="tag text-hot-ink hover:underline"
                        >
                          select all
                        </button>
                      )
                    }>
                      Out of date — the code moved on
                    </Eyebrow>
                    <div className="mt-2 mb-4 grid grid-cols-1 gap-2 md:grid-cols-2">
                      {stale.map(p => (
                        <PageCard
                          key={p.address}
                          page={p.page}
                          sectionTitle={p.section.title}
                          address={p.address}
                          on={picked.has(p.address)}
                          onClick={() => toggle(p.address)}
                        />
                      ))}
                    </div>
                  </>
                )}

                {gaps.length > 0 && (
                  <>
                    <Eyebrow right={
                      canRun && (
                        <button
                          onClick={() => setPicked(new Set(gaps.map(p => p.address)))}
                          className="tag text-hot-ink hover:underline"
                        >
                          select all
                        </button>
                      )
                    }>
                      Not written yet
                    </Eyebrow>
                    <div className="mt-2 mb-4 grid grid-cols-1 gap-2 md:grid-cols-2">
                      {gaps.map(p => (
                        <PageCard
                          key={p.address}
                          page={p.page}
                          sectionTitle={p.section.title}
                          address={p.address}
                          on={picked.has(p.address)}
                          onClick={() => toggle(p.address)}
                        />
                      ))}
                    </div>
                  </>
                )}

                {done.length > 0 && (
                  <>
                    <Eyebrow>Already written — pick one to write a fresh version</Eyebrow>
                    <div className="mt-2 grid grid-cols-1 gap-2 md:grid-cols-2">
                      {done.map(p => (
                        <PageCard
                          key={p.address}
                          page={p.page}
                          sectionTitle={p.section.title}
                          address={p.address}
                          on={picked.has(p.address)}
                          onClick={() => toggle(p.address)}
                          muted
                        />
                      ))}
                    </div>
                  </>
                )}

                {gaps.length === 0 && stale.length === 0 && done.length > 0 && (
                  <p className="mt-3 border-t border-rule pt-3 font-sans text-[12px] text-ink-mid">
                    Every planned page is written and current. Re-analyse to propose more,
                    or pick a page above to rewrite it.
                  </p>
                )}
              </div>

              <footer className="flex flex-wrap items-center gap-3 border-t border-rule bg-sunk/60 px-3 py-2.5">
                <span className="flex items-center gap-1.5">
                  <span className="tag text-ink-dim">formats</span>
                  {OUTPUT_FORMATS.map(f => (
                    <Chip
                      key={f.value}
                      active={formats.includes(f.value)}
                      title={f.note}
                      onClick={() =>
                        setFormats(p =>
                          p.includes(f.value) ? p.filter(x => x !== f.value) : [...p, f.value],
                        )
                      }
                    >
                      {f.label}
                    </Chip>
                  ))}
                </span>
                <span className="tag text-ink-dim">
                  {picked.size
                    ? `roughly ${Math.max(2, picked.size * 3)} min on a local model`
                    : 'select a page to write'}
                </span>
                <Button
                  variant="hot"
                  className="ml-auto"
                  disabled={!picked.size || !formats.length || busy || !canRun}
                  onClick={() => start([...picked])}
                >
                  {busy ? 'starting…' : `Write ${picked.size || ''} →`}
                </Button>
              </footer>
            </Panel>
          </div>

          {/* ── a whole section at once ─────────────────────────────── */}
          <div className="mt-3">
            <Panel title="Or write a whole section" index="03">
              <ul className="divide-y divide-rule">
                {(site.data?.sections ?? []).map(s => {
                  const remaining = s.pages.filter(p => isPending(p.status)).length
                  return (
                    <li key={s.slug} className="flex items-center gap-3 px-3 py-2">
                      <span className="min-w-0 flex-1">
                        <span className="block text-[12px] font-semibold text-ink">{s.title}</span>
                        <span className="tag block text-ink-dim">
                          {s.pages.length} pages · {remaining || 'none'} remaining
                        </span>
                      </span>
                      <Button
                        variant="ghost"
                        disabled={!remaining || busy || !canRun}
                        onClick={() => start([s.slug])}
                      >
                        {remaining ? `write ${remaining}` : 'complete'}
                      </Button>
                    </li>
                  )
                })}
              </ul>
              <p className="border-t border-rule px-3 py-2 text-[10.5px] leading-snug text-ink-dim">
                A section writes only the pages that are unwritten and anchored on real
                files. Pages already written are left alone — select one above to redo it.
              </p>
            </Panel>
          </div>

          {site.data?.updated_at && (
            <p className="mt-3 text-[10.5px] text-ink-dim">
              Map last updated {relativeTime(site.data.updated_at)}.
            </p>
          )}
        </>
      )}
    </div>
  )
}

function Legend({ n, label, tone }: { n: number; label: string; tone: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={`block size-[6px] rotate-45 ${tone}`} aria-hidden />
      <span className="tag text-ink-dim">
        {n} {label}
      </span>
    </span>
  )
}

function PageCard({
  page, sectionTitle, address, on, onClick, muted = false,
}: {
  page: SitePage
  sectionTitle: string
  address: string
  on: boolean
  onClick: () => void
  muted?: boolean
}) {
  return (
    <button
      onClick={onClick}
      aria-pressed={on}
      className={`plate plate-lift flex flex-col text-left ${on ? 'plate-hot' : ''} ${
        muted && !on ? 'opacity-55' : ''
      }`}
    >
      <span className="flex items-center gap-2 border-b border-rule px-2.5 py-1.5">
        <span
          className={`block size-[9px] shrink-0 rotate-45 border ${
            on ? 'border-hot bg-hot' : 'border-ink-dim bg-transparent'
          }`}
        />
        <span className="min-w-0 flex-1 truncate text-[12px] font-bold text-ink">
          {page.title}
        </span>
        <span className="tag shrink-0 text-ink-dim">{sectionTitle}</span>
      </span>
      <span className="flex-1 px-2.5 py-2">
        <span className="block font-sans text-[11.5px] leading-relaxed text-ink-mid">
          {page.intent || page.reason || address}
        </span>
        {!!page.key_files?.length && (
          <span className="mt-1.5 flex flex-wrap gap-1">
            {page.key_files.slice(0, 3).map(f => (
              <span key={f} className="tag border border-rule px-1 py-px text-ink-dim">
                {f.split('/').pop()}
              </span>
            ))}
          </span>
        )}
      </span>
      <span className="flex items-center gap-2 border-t border-rule px-2.5 py-1.5">
        <span className="tag text-ink-dim">{address}</span>
        {page.word_count > 0 && (
          <span className="tag ml-auto text-ink-dim">{page.word_count} words</span>
        )}
        {page.confidence != null && page.word_count === 0 && (
          <span className="tag ml-auto text-ink-dim">
            {confidenceLabel(page.confidence)}
          </span>
        )}
      </span>
    </button>
  )
}
