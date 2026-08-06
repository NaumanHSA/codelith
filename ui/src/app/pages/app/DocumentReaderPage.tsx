import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import { api, ApiError } from '../../lib/api'
import { useAsync } from '../../lib/hooks'
import { useAuth } from '../../auth'
import { formatDateTime, humanize } from '../../lib/format'
import { Button, PageHead, StatusBadge } from '../../components/ui'
import { ErrorState, SkeletonPanel } from '../../components/States'

/* ------------------------------------------------------------------ *
 * The reader is lazily loaded: markdown, syntax highlighting and
 * Mermaid together are larger than the rest of the studio combined,
 * and most sessions never open a document.
 * ------------------------------------------------------------------ */

/** Renders one Mermaid block. mermaid is imported only when one exists. */
function Mermaid({ code }: { code: string }) {
  const [svg, setSvg] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)
  const idRef = useRef(`m${Math.random().toString(36).slice(2)}`)

  useEffect(() => {
    let live = true
    import('mermaid')
      .then(async ({ default: mermaid }) => {
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: 'strict',
          theme: 'base',
          fontFamily: 'JetBrains Mono, monospace',
          themeVariables: {
            primaryColor: '#fff0e9',
            primaryBorderColor: '#ff6b35',
            primaryTextColor: '#14120f',
            lineColor: '#8a847c',
            background: '#ffffff',
          },
        })
        const { svg } = await mermaid.render(idRef.current, code)
        if (live) setSvg(svg)
      })
      .catch(() => live && setFailed(true))
    return () => {
      live = false
    }
  }, [code])

  // A diagram that will not parse should still show its source, not vanish.
  if (failed) return <pre className="overflow-x-auto bg-sunk p-3 text-[11px]">{code}</pre>

  return (
    <div className="my-4 overflow-x-auto border border-rule bg-panel p-4">
      {svg ? (
        <div dangerouslySetInnerHTML={{ __html: svg }} />
      ) : (
        <span className="tag text-ink-dim">drawing diagram…</span>
      )}
    </div>
  )
}

const slug = (s: string) =>
  s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')

export default function DocumentReaderPage() {
  const { documentId } = useParams()
  const id = Number(documentId)
  const navigate = useNavigate()
  const location = useLocation()
  const { can } = useAuth()

  const { data: doc, error, loading, reload, setData } = useAsync(() => api.document(id), [id])
  const [publishing, setPublishing] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [active, setActive] = useState<string | null>(null)

  // Where the reader came from, so "back" returns there rather than
  // dumping them on the documents list every time.
  const origin = (location.state ?? {}) as { from?: string; label?: string }

  const toc = useMemo(() => {
    if (!doc) return []
    const out: { depth: number; text: string; id: string }[] = []
    let inFence = false
    for (const line of doc.content_markdown.split('\n')) {
      if (line.trim().startsWith('```')) inFence = !inFence
      if (inFence) continue
      const m = /^(#{1,3})\s+(.*)$/.exec(line)
      if (m) out.push({ depth: m[1].length, text: m[2].trim(), id: slug(m[2].trim()) })
    }
    return out
  }, [doc])

  // Highlight the heading currently on screen.
  useEffect(() => {
    if (!toc.length) return
    const obs = new IntersectionObserver(
      entries => {
        const visible = entries.filter(e => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
        if (visible[0]) setActive(visible[0].target.id)
      },
      { rootMargin: '-64px 0px -70% 0px' },
    )
    for (const h of toc) {
      const el = document.getElementById(h.id)
      if (el) obs.observe(el)
    }
    return () => obs.disconnect()
  }, [toc])

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
    a.download = `${slug(doc.title) || 'document'}.md`
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

  const heading = (depth: 1 | 2 | 3) =>
    function H({ children }: { children?: React.ReactNode }) {
      const text = String(children)
      const Tag = `h${depth}` as 'h1' | 'h2' | 'h3'
      const size =
        depth === 1
          ? 'mt-8 mb-3 text-[22px]'
          : depth === 2
            ? 'mt-7 mb-2.5 border-b border-rule pb-1.5 text-[16px]'
            : 'mt-5 mb-2 text-[13.5px]'
      return (
        <Tag id={slug(text)} className={`scroll-mt-28 font-bold tracking-tight text-ink ${size}`}>
          {children}
        </Tag>
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
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeHighlight]}
            components={{
              h1: heading(1),
              h2: heading(2),
              h3: heading(3),
              code({ className, children, ...props }) {
                const text = String(children).replace(/\n$/, '')
                if (className?.includes('language-mermaid')) return <Mermaid code={text} />
                // Inline and block code are both styled in the .doc layer; the
                // distinction is made there by `:not(pre) > code`.
                return (
                  <code className={className} {...props}>
                    {children}
                  </code>
                )
              },
              pre({ children, ...props }) {
                // A Mermaid block renders its own framed container, so it must not
                // also be wrapped in a terminal surface.
                const child = Array.isArray(children) ? children[0] : children
                const inner = (child as { props?: { className?: string } } | null)?.props
                if (inner?.className?.includes('language-mermaid')) return <>{children}</>
                return <pre {...props}>{children}</pre>
              },
              table({ children, ...props }) {
                // Wide tables scroll inside their own box rather than pushing the
                // whole reading column sideways.
                return (
                  <div className="doc-table">
                    <table {...props}>{children}</table>
                  </div>
                )
              },
            }}
          >
            {doc.content_markdown}
          </ReactMarkdown>
        </article>

        {toc.length > 1 && (
          <nav className="hidden lg:block">
            <div className="sticky top-24">
              <span className="tag mb-2 block text-ink-dim">On this page</span>
              <ul className="border-l border-rule">
                {toc.map(h => (
                  <li key={h.id + h.text}>
                    <a
                      href={`#${h.id}`}
                      onClick={e => {
                        e.preventDefault()
                        document.getElementById(h.id)?.scrollIntoView({ behavior: 'smooth' })
                      }}
                      style={{ paddingLeft: `${(h.depth - 1) * 9 + 9}px` }}
                      className={`block border-l-2 py-[3px] pr-1 text-[11px] leading-snug transition-colors ${
                        active === h.id
                          ? 'border-hot text-hot-ink'
                          : 'border-transparent text-ink-dim hover:text-ink'
                      }`}
                    >
                      {h.text}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          </nav>
        )}
      </div>
    </div>
  )
}
