import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../lib/api'
import { useAsync } from '../../lib/hooks'
import { docTypeMeta } from '../../lib/docTypes'
import { countLabel, humanize, relativeTime } from '../../lib/format'
import type { Doc } from '../../lib/types'
import { Chip, PageHead, StatusBadge } from '../../components/ui'
import { EmptyState, ErrorState, SkeletonGrid } from '../../components/States'

/** Rough reading time — the only number the reader actually wants. */
function readMinutes(markdown: string) {
  return Math.max(1, Math.round(markdown.trim().split(/\s+/).length / 220))
}

function DocCard({ d, i, onOpen }: { d: Doc; i: number; onOpen: () => void }) {
  const meta = docTypeMeta(d.doc_type)
  // First non-heading line makes a better preview than the title again.
  const preview =
    d.content_markdown
      .split('\n')
      .map(l => l.trim())
      .find(l => l && !l.startsWith('#') && !l.startsWith('```')) ?? meta.blurb

  return (
    <button
      onClick={onOpen}
      style={{ animationDelay: `${Math.min(i, 12) * 40}ms` }}
      className="plate plate-lift anim-rise flex flex-col text-left"
    >
      <span className="flex items-center gap-2 border-b border-rule bg-sunk/60 px-3 py-2">
        <span className="tag text-hot-ink">{humanize(d.doc_type)}</span>
        <span className="tag ml-auto text-ink-dim">v{d.version}</span>
        <StatusBadge status={d.status} />
      </span>
      <span className="flex-1 px-3 py-2.5">
        <span className="block truncate text-[13px] font-bold tracking-tight text-ink">
          {d.title}
        </span>
        <span className="mt-1.5 line-clamp-3 block font-sans text-[11.5px] leading-relaxed text-ink-mid">
          {preview}
        </span>
      </span>
      <span className="flex items-center gap-2 border-t border-rule px-3 py-1.5">
        <span className="tag text-ink-dim">{readMinutes(d.content_markdown)} min read</span>
        <span className="tag ml-auto text-ink-dim">{relativeTime(d.created_at)}</span>
      </span>
    </button>
  )
}

export default function DocumentsPage() {
  const navigate = useNavigate()
  const { data, error, loading, reload } = useAsync(() => api.documents(undefined, 50, 0), [])
  const [type, setType] = useState<string>('all')
  const [q, setQ] = useState('')

  const types = useMemo(
    () => Array.from(new Set((data ?? []).map(d => d.doc_type))),
    [data],
  )

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return (data ?? []).filter(
      d =>
        (type === 'all' || d.doc_type === type) &&
        (!needle || d.title.toLowerCase().includes(needle)),
    )
  }, [data, type, q])

  return (
    <div className="mx-auto max-w-[1180px] p-5">
      <PageHead
        index="03"
        title="Documents"
        sub="Single documents, written before sites existed — across every project."
        back={{ label: 'back to projects', onClick: () => navigate('/app/projects') }}
      />

      <div className="mb-4 flex flex-wrap items-center gap-2 border border-rule bg-panel px-2 py-1.5">
        <span className="tag pl-1 text-hot">/</span>
        <input
          value={q}
          onChange={e => setQ(e.target.value)}
          placeholder="filter documents…"
          className="min-w-[140px] flex-1 bg-transparent py-1 text-[12px] text-ink placeholder:text-ink-dim focus:outline-none"
        />
        <span className="tag text-ink-dim">{countLabel(filtered.length, 'document')}</span>
        <span className="h-4 w-px bg-rule" />
        <Chip active={type === 'all'} onClick={() => setType('all')}>
          all
        </Chip>
        {types.map(t => (
          <Chip key={t} active={type === t} onClick={() => setType(t)}>
            {humanize(t)}
          </Chip>
        ))}
      </div>

      {loading && <SkeletonGrid count={6} />}
      {!loading && error && <ErrorState message={error} onRetry={reload} />}

      {!loading && !error && filtered.length === 0 && (
        <EmptyState
          title={data?.length ? 'Nothing matches that filter' : 'No documents yet'}
          body={
            data?.length
              ? 'Try another document type, or clear the filter.'
              : 'Analyse a project, choose what to write, and finished documents land here.'
          }
        />
      )}

      {!loading && !error && filtered.length > 0 && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {filtered.map((d, i) => (
            <DocCard key={d.id} d={d} i={i} onOpen={() => navigate(`/app/documents/${d.id}`)} />
          ))}
        </div>
      )}
    </div>
  )
}
