import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import { useState } from 'react'

/* ------------------------------------------------------------------ *
 * Markdown, without a reading surface around it.
 *
 * `DocMarkdown` is the *documentation* renderer: it stamps anchor ids
 * on headings and hangs a rewrite button off each `##`, because a page
 * is something you revise. A chat message is not — the same buttons on
 * an answer would offer to rewrite a sentence nobody wrote.
 *
 * So the react-markdown configuration lives here once and both callers
 * use it, rather than the chat duplicating a config that would drift
 * the first time either changed.
 * ------------------------------------------------------------------ */

function Copy({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      onClick={() => {
        navigator.clipboard?.writeText(text)
        setCopied(true)
        setTimeout(() => setCopied(false), 1200)
      }}
      className="absolute right-2 top-2 rounded border border-rule bg-panel px-1.5 py-0.5 text-[10px] text-ink-dim opacity-0 transition-opacity group-hover:opacity-100 hover:text-hot-ink"
    >
      {copied ? 'copied' : 'copy'}
    </button>
  )
}

export function Markdown({ children }: { children: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeHighlight]}
      components={{
        pre({ children, ...props }) {
          // The copy button needs a positioned ancestor, and a code block a
          // reader cannot copy out of is a code block they retype by hand.
          const text = extractText(children)
          return (
            <div className="group relative">
              <pre {...props}>{children}</pre>
              {!!text && <Copy text={text} />}
            </div>
          )
        },
        table({ children, ...props }) {
          // Wide tables scroll inside their own box rather than pushing the
          // whole column sideways.
          return (
            <div className="doc-table">
              <table {...props}>{children}</table>
            </div>
          )
        },
        a({ children, href, ...props }) {
          const external = href?.startsWith('http')
          return (
            <a
              href={href}
              {...props}
              {...(external ? { target: '_blank', rel: 'noreferrer' } : {})}
            >
              {children}
            </a>
          )
        },
      }}
    >
      {children}
    </ReactMarkdown>
  )
}

/** The text inside a `<pre>`, for the clipboard. */
function extractText(node: unknown): string {
  if (typeof node === 'string') return node
  if (Array.isArray(node)) return node.map(extractText).join('')
  const el = node as { props?: { children?: unknown } } | null
  return el?.props?.children ? extractText(el.props.children) : ''
}
