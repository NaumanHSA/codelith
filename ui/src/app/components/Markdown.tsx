import ReactMarkdown, { defaultUrlTransform } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import rehypeRaw from 'rehype-raw'
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize'
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

/* Diagrams reach a page as two things the default renderer throws away.
 *
 * The picture is `![name](data:image/svg+xml;base64,…)`. react-markdown sanitises
 * URLs to a protocol allowlist that does not include `data:`, so the src was blanked
 * and every diagram rendered as a broken-image icon — with a valid 30KB SVG sitting
 * in the markdown the whole time.
 *
 * The source underneath it is a `<details>` block, and react-markdown renders no raw
 * HTML at all without `rehype-raw`, so the tags arrived as literal text: readers saw
 * `</details>` printed on the page.
 *
 * Raw HTML in an LLM-written document is a script tag waiting to happen, so `rehypeRaw`
 * is followed by `rehypeSanitize` on a schema extended by exactly what is needed:
 * `details`/`summary`, `data:` image sources, and the class names `rehype-highlight`
 * puts on its spans (the default schema drops them, which would leave every code block
 * unstyled).
 */
const SCHEMA = {
  ...defaultSchema,
  tagNames: [...(defaultSchema.tagNames ?? []), 'details', 'summary'],
  attributes: {
    ...defaultSchema.attributes,
    // `data:` for the embedded diagrams. They are generated locally by d2 from the
    // import graph and embedded rather than served, so there is no asset URL to allow.
    img: [...(defaultSchema.attributes?.img ?? []), ['src', /^data:image\/(svg\+xml|png|jpeg|gif|webp);base64,/]],
    span: [...(defaultSchema.attributes?.span ?? []), ['className', /^hljs-/]],
    code: [...(defaultSchema.attributes?.code ?? []), ['className', /^(language-|hljs)/]],
    details: [['open']],
  },
  protocols: {
    ...defaultSchema.protocols,
    src: [...(defaultSchema.protocols?.src ?? []), 'data'],
  },
}

/** Exported, because the comment at the top of this file promised the config lived
 *  in one place and it did not: `DocMarkdown` kept its own copy and drifted, which is
 *  why documentation pages rendered `</details>` as text long after this was fixed
 *  anywhere else. Order matters — raw HTML is parsed, then sanitised, then
 *  highlighted. */
export const REHYPE_PLUGINS = [rehypeRaw, [rehypeSanitize, SCHEMA], rehypeHighlight] as never
export const REMARK_PLUGINS = [remarkGfm]

/** Embedded diagrams, past react-markdown's *own* URL guard.
 *
 *  This is a second, separate gate from the sanitize schema above, and missing it is
 *  why the first attempt at this fixed the `<details>` block and left the image just
 *  as broken. `rehypePlugins` run over the tree; then react-markdown applies
 *  `urlTransform` to every `src` and `href` on its way out, and its default strips
 *  everything outside `http`/`https`/`mailto`/`tel`. The picture had already survived
 *  sanitisation and was blanked afterwards.
 *
 *  Narrow on purpose: base64 image payloads only, everything else deferred to the
 *  default. `data:text/html` is a script tag by another name. */
const DATA_IMAGE = /^data:image\/(svg\+xml|png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]+$/

export function urlTransform(url: string): string {
  return DATA_IMAGE.test(url) ? url : defaultUrlTransform(url)
}

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
      remarkPlugins={REMARK_PLUGINS}
      rehypePlugins={REHYPE_PLUGINS}
      urlTransform={urlTransform}
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
