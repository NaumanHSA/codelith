import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { REHYPE_PLUGINS, REMARK_PLUGINS } from '../Markdown'
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

/**
 * A `##` is the unit a reader points at.
 *
 * It is what the planner decides, what the reader sees as "a section", and what
 * `anchor_id` addresses — so it is the only depth that carries a rewrite affordance.
 * `#` is the page and `###` is the writer's own sub-structure inside a section;
 * neither maps onto something the pipeline can revise on its own.
 */
const heading = (
  depth: 1 | 2 | 3,
  revise?: (anchor: string, title: string) => void,
  selected?: string | null,
  busy?: string | null,
) =>
  function H({ children }: { children?: React.ReactNode }) {
    const text = String(children)
    const anchor = anchorId(text)
    const Tag = `h${depth}` as 'h1' | 'h2' | 'h3'
    const size =
      depth === 1
        ? 'mt-8 mb-3 text-[22px]'
        : depth === 2
          ? 'mt-7 mb-2.5 border-b border-rule pb-1.5 text-[16px]'
          : 'mt-5 mb-2 text-[13.5px]'

    const revisable = depth === 2 && Boolean(revise)
    const isSelected = revisable && selected === anchor
    // Selected is not the same as working. The chip used to say "revising" for as
    // long as the panel was open against a heading, which meant it still said so
    // after the rewrite had landed — the reader had no way to tell a finished
    // section from one still being written.
    const isBusy = revisable && busy === anchor

    return (
      <Tag
        id={anchor}
        className={`group/h scroll-mt-28 font-bold tracking-tight text-ink ${size} ${
          revisable ? 'flex items-center gap-2 pr-1' : ''
        } ${isSelected ? 'border-l-[3px] border-l-hot -ml-3 pl-[9px] bg-hot-wash/50' : ''}`}
      >
        <span className="min-w-0 flex-1">{children}</span>
        {revisable && (
          <button
            type="button"
            onClick={() => revise?.(anchor, text)}
            title={`Rewrite “${text}” with AI`}
            aria-label={`Rewrite ${text} with AI`}
            // Always visible. A hover-only control tells nobody the feature exists,
            // and on a touch screen there is no hover at all.
            className={`tag shrink-0 border px-1.5 py-[2px] font-normal transition-colors ${
              isBusy
                ? 'border-hot bg-hot text-paper'
                : isSelected
                  ? 'border-hot bg-hot-wash text-hot-ink'
                  : 'border-rule bg-panel text-ink-dim hover:border-hot hover:bg-hot-wash hover:text-hot-ink'
            }`}
          >
            {isBusy ? (
              <span className="flex items-center gap-1">
                <span className="anim-blink block size-[5px] rounded-full bg-paper" />
                rewriting
              </span>
            ) : (
              'rewrite'
            )}
          </button>
        )}
      </Tag>
    )
  }

export default function DocMarkdown({
  children,
  onRevise,
  selectedAnchor = null,
  busyAnchor = null,
}: {
  children: string
  /** Omitted on a frozen version or for a reader without write access. */
  onRevise?: (anchor: string, title: string) => void
  /** The heading the panel is open against — highlighted, but not necessarily busy. */
  selectedAnchor?: string | null
  /** The heading a run is rewriting right now. */
  busyAnchor?: string | null
}) {
  return (
    <ReactMarkdown
      remarkPlugins={REMARK_PLUGINS}
      rehypePlugins={REHYPE_PLUGINS}
      components={{
        h1: heading(1),
        h2: heading(2, onRevise, selectedAnchor, busyAnchor),
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
