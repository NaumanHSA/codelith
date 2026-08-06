import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import { anchorId } from '../../lib/site'

/* ------------------------------------------------------------------ *
 * The reading surface.
 *
 * One implementation, used by both the legacy document reader and the
 * documentation site — they must look identical, because they are the
 * same thing at two granularities, and a reader moving between them
 * should not be able to tell which one they are on.
 *
 * Lazily loaded by both callers: markdown, syntax highlighting and
 * Mermaid together are larger than the rest of the studio combined.
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
      <Tag id={anchorId(text)} className={`scroll-mt-28 font-bold tracking-tight text-ink ${size}`}>
        {children}
      </Tag>
    )
  }

export default function DocMarkdown({ children }: { children: string }) {
  return (
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
      {children}
    </ReactMarkdown>
  )
}
