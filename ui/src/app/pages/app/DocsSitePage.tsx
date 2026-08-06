import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../../lib/api'
import { useAsync } from '../../lib/hooks'
import { useAuth } from '../../auth'
import { useRunningJobs } from '../../running-jobs'
import { shortSha } from '../../lib/format'
import {
  addressOf, coverage, findPage, headingsOf, isPending, neighbours, searchPages,
  type FlatPage,
} from '../../lib/site'
import type { SitePage, SitePageDetail } from '../../lib/types'
import { Button, Chip, Meter } from '../../components/ui'
import { EmptyState, ErrorState, SkeletonPanel } from '../../components/States'
import Coverage from '../../components/docs/Coverage'
import PageDiff from '../../components/docs/PageDiff'
import PageProgress from '../../components/docs/PageProgress'
import PageProvenance from '../../components/docs/PageProvenance'
import SiteNav from '../../components/docs/SiteNav'
import SiteToolbar from '../../components/docs/SiteToolbar'
import Toc from '../../components/docs/Toc'

/* ------------------------------------------------------------------ *
 * The documentation site.
 *
 * Four panes: a sticky bar of sections across the top, the pages of the
 * active section on the left, the page itself in the centre, its
 * headings on the right.
 *
 * The one rule that shapes all of it: **planned pages are part of the
 * site.** They appear in the nav, in the reading order and in coverage,
 * greyed, each one click from being written. Hiding what does not exist
 * yet is what turns a documentation site back into a folder of files.
 * ------------------------------------------------------------------ */

const DocMarkdown = lazy(() => import('../../components/docs/DocMarkdown'))

/** Polled while any page of this site is being written. */
const REFRESH_MS = 4000

export default function DocsSitePage() {
  const { projectId, sectionSlug, pageSlug } = useParams()
  const id = Number(projectId)
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  // A lens over the same addresses rather than a path segment, so every page
  // URL keeps working — and dropping it returns you to the live site.
  const version = params.get('v')
  const { can } = useAuth()
  const { track } = useRunningJobs()

  const { data: project } = useAsync(() => api.project(id), [id])
  const { data: site, error, loading, reload } = useAsync(
    s => api.site(id, version, s),
    [id, version],
  )

  const [generating, setGenerating] = useState<string | null>(null)
  const [generatingSection, setGeneratingSection] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [query, setQuery] = useState('')

  // Nothing in a frozen snapshot can be regenerated: it is a record, not a draft.
  const canGenerate = can('manager') && !version
  const current = useMemo(
    () => findPage(site ?? null, sectionSlug, pageSlug),
    [site, sectionSlug, pageSlug],
  )
  const activeSection = useMemo(
    () => site?.sections.find(s => s.slug === sectionSlug) ?? null,
    [site, sectionSlug],
  )
  const showCoverage = !sectionSlug

  // Fetched separately from the map: a thirty-page site's markdown is
  // megabytes and the nav re-renders on every navigation.
  const address = current?.address
  const { data: page, loading: pageLoading, reload: reloadPage } = useAsync(
    s =>
      address
        ? api.sitePage(id, address.split('/')[0], address.split('/')[1], version, s)
        : Promise.resolve(null),
    [id, address, version],
  )

  const headings = useMemo(() => headingsOf(page?.content_markdown), [page])
  const { prev, next } = useMemo(() => neighbours(site ?? null, current), [site, current])
  const results = useMemo(() => searchPages(site ?? null, query), [site, query])
  const cov = useMemo(() => coverage(site ?? null), [site])

  // While anything is being written, the map is out of date the moment a
  // page lands. Poll until nothing is in flight.
  const busy = (site?.page_counts?.generating ?? 0) > 0
  const reloadRef = useRef(reload)
  reloadRef.current = reload
  useEffect(() => {
    if (!busy) return
    const t = setInterval(() => reloadRef.current(), REFRESH_MS)
    return () => clearInterval(t)
  }, [busy])

  // The open page finished being written: pull both the map (its status and
  // word count changed) and the page itself (it now has prose). Sitting on a
  // page waiting for it is the common case, and having to reload by hand is
  // the thing that made it feel broken.
  const reloadPageRef = useRef(reloadPage)
  reloadPageRef.current = reloadPage
  const pageFinished = () => {
    reloadRef.current()
    reloadPageRef.current()
  }

  // Scrolled content should not persist across a navigation.
  const scroller = useRef<HTMLDivElement>(null)
  useEffect(() => {
    scroller.current?.scrollTo({ top: 0 })
  }, [address])

  const suffix = version ? `?v=${encodeURIComponent(version)}` : ''
  const open = (section: string, p: SitePage) =>
    navigate(`/app/projects/${id}/docs/${section}/${p.slug}${suffix}`)

  const compose = async (slugs: string[], mark: () => void, clear: () => void) => {
    setActionError(null)
    mark()
    try {
      const job = await api.compose(id, {
        page_slugs: slugs,
        output_formats: ['markdown'],
        human_review: false,
      })
      track(job, project?.name)
      reload()
    } catch (e) {
      setActionError(
        e instanceof ApiError ? e.message : 'Could not start writing. Try again.',
      )
      clear()
    }
  }

  const generatePage = (p: SitePage) => {
    const addr = addressOf(p)
    void compose([addr], () => setGenerating(addr), () => setGenerating(null))
  }

  const generateSection = (slug: string) =>
    void compose([slug], () => setGeneratingSection(slug), () => setGeneratingSection(null))

  if (loading) {
    return (
      <div className="mx-auto max-w-[1100px] p-5">
        <SkeletonPanel rows={8} />
      </div>
    )
  }

  if (error) {
    return (
      <div className="mx-auto max-w-[1100px] p-5">
        <ErrorState message={error} onRetry={reload} />
      </div>
    )
  }

  if (!site || !site.sections.length) {
    return (
      <div className="mx-auto max-w-[1100px] p-5">
        <EmptyState
          title="No documentation site yet"
          body="Analysis proposes the sections and pages this project warrants. Run it, and the site appears as a map you can fill in a section at a time."
          action={
            <Button variant="hot" onClick={() => navigate(`/app/projects/${id}`)}>
              Go to the project
            </Button>
          }
        />
      </div>
    )
  }

  return (
    <div className="flex min-h-full flex-col">
      {/* ── top: project, sections, search, coverage ─────────────────── */}
      <header className="sticky top-0 z-20 border-b border-rule bg-paper">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 pt-3 pb-2">
          <button
            onClick={() => navigate(`/app/projects/${id}`)}
            className="tag text-ink-dim transition-colors hover:text-hot-ink"
          >
            ← {project?.name ?? 'project'}
          </button>
          <h1 className="truncate text-[14px] font-bold tracking-tight text-ink">{site.title}</h1>

          <div className="relative ml-auto">
            <input
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="search pages…"
              aria-label="Search pages"
              className="w-[190px] border border-rule bg-sunk/60 px-2.5 py-[5px] font-mono text-[11px] text-ink transition-colors placeholder:text-ink-dim focus:border-hot focus:bg-panel focus:outline-none"
            />
            {results.length > 0 && (
              <ul className="absolute top-full right-0 z-30 mt-1 w-[320px] border border-rule bg-panel shadow-lg">
                {results.map(r => (
                  <li key={r.address}>
                    <button
                      onClick={() => {
                        setQuery('')
                        open(r.section.slug, r.page)
                      }}
                      className="flex w-full items-baseline gap-2 px-2.5 py-1.5 text-left transition-colors hover:bg-sunk"
                    >
                      <span className="truncate text-[11.5px] text-ink">{r.page.title}</span>
                      <span className="tag ml-auto shrink-0 text-ink-dim">{r.address}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <button
            onClick={() => navigate(`/app/projects/${id}/docs${suffix}`)}
            title="The whole map: what is built, planned and stale"
            className="flex items-center gap-2 border border-rule bg-panel px-2 py-[4px] transition-colors hover:border-ink"
          >
            <Meter pct={cov.pct} segments={12} />
            <span className="tag text-ink-dim">{cov.pct}%</span>
          </button>

          <SiteToolbar
            site={site}
            projectId={id}
            version={version}
            onVersion={label => {
              // A version is a lens, so switching keeps you on the page you
              // were reading rather than dumping you at the overview.
              const next = new URLSearchParams(params)
              if (label) next.set('v', label)
              else next.delete('v')
              setParams(next, { replace: true })
            }}
            canManage={canGenerate}
            onVersionCreated={reload}
          />
        </div>

        {/*
          The sections are the site's spine, so they sit centred and read as
          navigation rather than as controls — spaced text with an underline on
          the active one, deliberately unlike the bordered buttons used
          everywhere else in the studio.
        */}
        <nav className="flex justify-center overflow-x-auto border-t border-rule px-4">
          <div className="flex items-stretch gap-7">
            <SectionTab
              label="Overview"
              active={showCoverage}
              onClick={() => navigate(`/app/projects/${id}/docs${suffix}`)}
            />
            {site.sections.map(s => (
              <SectionTab
                key={s.slug}
                label={s.title}
                active={s.slug === sectionSlug}
                onClick={() => {
                  const first = s.pages[0]
                  navigate(
                    first
                      ? `/app/projects/${id}/docs/${s.slug}/${first.slug}${suffix}`
                      : `/app/projects/${id}/docs/${s.slug}${suffix}`,
                  )
                }}
              />
            ))}
          </div>
        </nav>
      </header>

      {version && (
        <div className="flex flex-wrap items-center gap-2 border-b border-rule bg-sunk px-4 py-1.5">
          <span className="tag text-ink-dim">reading version</span>
          <span className="text-[11.5px] font-semibold text-ink">{version}</span>
          <span className="text-[11px] text-ink-dim">
            frozen — nothing here can be rewritten
          </span>
          <button
            onClick={() => {
              const next = new URLSearchParams(params)
              next.delete('v')
              setParams(next, { replace: true })
            }}
            className="tag ml-auto text-hot-ink hover:underline"
          >
            back to the live site →
          </button>
        </div>
      )}

      {actionError && (
        <div className="px-4 pt-3">
          <ErrorState message={actionError} compact />
        </div>
      )}

      {showCoverage ? (
        <div className="mx-auto w-full max-w-[1100px] p-5">
          <Coverage
            site={site}
            onOpen={open}
            onGenerateSection={generateSection}
            generatingSection={generatingSection}
            canGenerate={canGenerate}
            home={
              site.home_markdown ? (
                // Home is derived from the map on every read, so it can never
                // fall behind the nav — it has no stored copy to go stale.
                <article className="doc min-w-0 border border-rule bg-panel px-5 py-4 md:px-8 md:py-6">
                  <Suspense fallback={<SkeletonPanel rows={4} />}>
                    <DocMarkdown>{site.home_markdown}</DocMarkdown>
                  </Suspense>
                </article>
              ) : null
            }
          />
        </div>
      ) : (
        /*
          One centred column with the page list and the heading list either
          side of it. They are the same kind of thing — where you are in the
          section, where you are in the page — so they are laid out as a pair
          and sit against the document rather than against the shell.

          Below `lg` both collapse above the prose in reading order: which
          page, then the page. The ToC only earns its column at `xl`; at `lg`
          the reading measure matters more.
        */
        <div ref={scroller} className="min-w-0 flex-1 p-5">
          <div className="mx-auto grid max-w-[1240px] grid-cols-1 gap-6 lg:grid-cols-[220px_minmax(0,1fr)] xl:grid-cols-[220px_minmax(0,1fr)_200px]">
            <aside className="lg:sticky lg:top-[86px] lg:h-fit lg:self-start">
              <SiteNav
                section={activeSection}
                activeSlug={pageSlug}
                onOpen={p => open(p.section_slug, p)}
                onGenerate={generatePage}
                generating={generating}
                canGenerate={canGenerate}
              />
            </aside>

            <div className="min-w-0">
              {!current ? (
                <EmptyState
                  title="Nothing planned here yet"
                  body="This section has no pages. Re-run analysis to propose some."
                />
              ) : pageLoading ? (
                <SkeletonPanel rows={10} />
              ) : (
                <PageBody
                  flat={current}
                  page={page ?? null}
                  projectId={id}
                  onGenerate={() => generatePage(current.page)}
                  generating={generating === current.address}
                  canGenerate={canGenerate}
                  onFinished={pageFinished}
                />
              )}

              {/* ── prev / next ────────────────────────────────── */}
              {(prev || next) && (
                <div className="mt-6 grid grid-cols-2 gap-px border border-rule bg-rule">
                  {prev ? (
                    <button
                      onClick={() => open(prev.section.slug, prev.page)}
                      className="bg-panel px-3 py-2.5 text-left transition-colors hover:bg-sunk"
                    >
                      <span className="tag block text-ink-dim">← {prev.section.title}</span>
                      <span className="mt-0.5 block truncate text-[12px] text-ink">
                        {prev.page.title}
                      </span>
                    </button>
                  ) : (
                    <span className="bg-panel" />
                  )}
                  {next ? (
                    <button
                      onClick={() => open(next.section.slug, next.page)}
                      className="bg-panel px-3 py-2.5 text-right transition-colors hover:bg-sunk"
                    >
                      <span className="tag block text-ink-dim">{next.section.title} →</span>
                      <span className="mt-0.5 block truncate text-[12px] text-ink">
                        {next.page.title}
                      </span>
                    </button>
                  ) : (
                    <span className="bg-panel" />
                  )}
                </div>
              )}
            </div>

            <Toc headings={headings} />
          </div>
        </div>
      )}
    </div>
  )
}

/**
 * A section in the top nav.
 *
 * Text with a rule under the active one, not a button — these are places in a
 * document, and dressing them as controls made them read as a toolbar and
 * disappear against the real toolbar beside them.
 */
function SectionTab({
  label, active, onClick,
}: {
  label: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      aria-current={active ? 'page' : undefined}
      className={`relative shrink-0 py-2.5 text-[13px] tracking-tight whitespace-nowrap transition-colors ${
        active ? 'font-semibold text-ink' : 'text-ink-dim hover:text-ink'
      }`}
    >
      {label}
      {active && <span className="absolute inset-x-0 -bottom-px h-[2px] bg-hot" />}
    </button>
  )
}

/* ------------------------------------------------------------------ *
 * One page: either its prose, or what it is going to say.
 * ------------------------------------------------------------------ */

function PageBody({
  flat, page: detail, projectId, onGenerate, generating, canGenerate, onFinished,
}: {
  flat: FlatPage
  page: SitePageDetail | null
  projectId: number
  onGenerate: () => void
  generating: boolean
  canGenerate: boolean
  onFinished: () => void
}) {
  const { page, section } = flat
  const pending = isPending(page.status)
  const markdown = detail?.content_markdown ?? null
  const previous = detail?.previous_markdown ?? null
  const [showDiff, setShowDiff] = useState(false)
  // Server-derived, so it is true however you arrived at this page — including
  // in a second tab, or after a reload that lost whatever button you pressed.
  const inFlight = page.status === 'generating'

  return (
    <>
      <div className="mb-4 border-b border-rule pb-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="tag text-ink-dim">
            {section.title} / {page.slug}
          </span>
          {page.status !== 'ready' && page.status !== 'stale' && (
            <Chip tone={page.status === 'failed' ? 'bad' : 'plain'}>{page.status}</Chip>
          )}
          {previous && (
            <button
              onClick={() => setShowDiff(d => !d)}
              className="tag border border-rule bg-sunk px-1.5 py-[3px] text-ink-mid transition-colors hover:border-ink hover:text-ink"
            >
              {showDiff ? 'hide changes' : 'what changed?'}
            </button>
          )}
        </div>
        <h1 className="mt-1.5 text-[21px] leading-tight font-bold tracking-tight text-ink">
          {page.title}
        </h1>
        {page.intent && <p className="mt-1.5 text-[12px] text-ink-mid">{page.intent}</p>}
      </div>

      {inFlight && (
        <PageProgress
          projectId={projectId}
          page={page}
          onFinished={onFinished}
          onRetry={onGenerate}
          canGenerate={canGenerate}
        />
      )}

      {/* Staleness is per page, so the offer is precise: refresh *this* one. */}
      {page.status === 'stale' && (
        <div className="mb-4 flex flex-wrap items-center gap-2 border border-warn/40 bg-warn-wash px-3 py-2">
          <span className="tag text-warn">out of date</span>
          <span className="font-sans text-[11.5px] text-ink-mid">
            The code this page was written from has changed since {shortSha(page.commit_sha)}.
          </span>
          {canGenerate && (
            <Button variant="ghost" className="ml-auto" onClick={onGenerate} disabled={generating}>
              {generating ? 'rewriting…' : '↻ Rewrite'}
            </Button>
          )}
        </div>
      )}

      {showDiff && previous && markdown ? (
        <PageDiff before={previous} after={markdown} onClose={() => setShowDiff(false)} />
      ) : markdown ? (
        <article className="doc min-w-0 border border-rule bg-panel px-5 py-4 md:px-8 md:py-6">
          <Suspense fallback={<SkeletonPanel rows={8} />}>
            <DocMarkdown>{markdown}</DocMarkdown>
          </Suspense>
        </article>
      ) : (
        <section className="plate p-5">
          {/* `generating` is not listed: PageProgress above already says so, in
              far more detail than a three-word tag could. */}
          <span className="tag text-ink-dim">
            {page.status === 'failed'
              ? 'this page could not be written'
              : inFlight
                ? 'what it will say'
                : 'not written yet'}
          </span>
          <p className="mt-2 max-w-[60ch] text-[12px] leading-relaxed text-ink-mid">
            {page.reason
              ? `Analysis proposed this page because ${page.reason.charAt(0).toLowerCase()}${page.reason.slice(1)}`
              : 'Analysis proposed this page from the knowledge base.'}
          </p>

          {!!page.key_files?.length && (
            <div className="mt-4">
              <span className="tag block text-ink-dim">It will be written from</span>
              <ul className="mt-1.5 space-y-0.5">
                {page.key_files.map(f => (
                  <li key={f} className="font-mono text-[11px] text-ink-mid">
                    {f}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {pending && canGenerate && !inFlight && (
            <div className="mt-5">
              <Button variant="hot" onClick={onGenerate} disabled={generating}>
                {generating ? 'writing…' : 'Write this page'}
              </Button>
            </div>
          )}
        </section>
      )}

      {detail && markdown && <PageProvenance page={detail} />}
    </>
  )
}
