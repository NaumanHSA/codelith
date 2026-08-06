import { useMemo, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../../lib/api'
import { useAsync } from '../../lib/hooks'
import { useAuth } from '../../auth'
import { formatDateTime, humanize } from '../../lib/format'
import { anchorId, headingsOf } from '../../lib/site'
import { Button, PageHead, StatusBadge } from '../../components/ui'
import { ErrorState, SkeletonPanel } from '../../components/States'
import DocMarkdown from '../../components/docs/DocMarkdown'
import Toc from '../../components/docs/Toc'

/* ------------------------------------------------------------------ *
 * The legacy single-document reader.
 *
 * Documents written before the site existed, and anything the
 * doc-type composition path still produces, are read here. The reading
 * surface itself is shared with the documentation site — the two must
 * be indistinguishable, because they are the same thing at two
 * granularities.
 *
 * Lazily loaded: markdown, syntax highlighting and Mermaid together are
 * larger than the rest of the studio combined, and most sessions never
 * open a document.
 * ------------------------------------------------------------------ */

export default function DocumentReaderPage() {
  const { documentId } = useParams()
  const id = Number(documentId)
  const navigate = useNavigate()
  const location = useLocation()
  const { can } = useAuth()

  const { data: doc, error, loading, reload, setData } = useAsync(() => api.document(id), [id])
  const [publishing, setPublishing] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  // Where the reader came from, so "back" returns there rather than
  // dumping them on the documents list every time.
  const origin = (location.state ?? {}) as { from?: string; label?: string }

  const toc = useMemo(() => headingsOf(doc?.content_markdown), [doc])

  const publish = async () => {
    setPublishing(true)
    setActionError(null)
    try {
      setData(await api.publishDocument(id))
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : 'Could not publish the document.')
    } finally {
      setPublishing(false)
    }
  }

  const download = () => {
    if (!doc) return
    // Built entirely in the browser — nothing is uploaded to produce it.
    const blob = new Blob([doc.content_markdown], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${anchorId(doc.title) || 'document'}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  if (loading) {
    return (
      <div className="mx-auto max-w-[1100px] p-5">
        <SkeletonPanel rows={8} />
      </div>
    )
  }

  if (error || !doc) {
    return (
      <div className="mx-auto max-w-[1100px] p-5">
        <ErrorState message={error ?? 'Document not found.'} onRetry={reload} />
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-[1100px] p-5">
      <PageHead
        index={humanize(doc.doc_type).slice(0, 3).toUpperCase()}
        title={doc.title}
        sub={
          <>
            v{doc.version} · written {formatDateTime(doc.created_at)}
          </>
        }
        back={{
          label: origin.label ?? 'back to documents',
          onClick: () => navigate(origin.from ?? '/app/documents'),
        }}
        right={
          <div className="flex items-center gap-2">
            <StatusBadge status={doc.status} size="md" />
            <Button variant="ghost" onClick={download}>
              ↓ Markdown
            </Button>
            {doc.status !== 'published' && can('reviewer') && (
              <Button variant="hot" onClick={publish} disabled={publishing}>
                {publishing ? 'publishing…' : 'Publish'}
              </Button>
            )}
          </div>
        }
      />

      {actionError && <ErrorState message={actionError} compact />}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1fr_210px]">
        <article className="doc min-w-0 border border-rule bg-panel px-5 py-4 md:px-8 md:py-6">
          <DocMarkdown>{doc.content_markdown}</DocMarkdown>
        </article>

        <Toc headings={toc} className="hidden lg:block" top="top-24" />

      </div>
    </div>
  )
}
