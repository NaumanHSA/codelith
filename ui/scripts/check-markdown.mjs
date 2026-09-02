// What a documentation page is allowed to render.
//
// Two properties, and they pull against each other: diagrams are embedded as
// `data:` image URIs and have to survive, while the markdown around them was
// written by a model and must not be able to inject script.
//
// It renders the ACTUAL components rather than reassembling the pipeline. Vite compiles the TSX and resolves the same module
// graph the browser gets, so this exercises react-markdown's urlTransform — the gate
// the previous hand-rolled unified pipeline ran outside of, which is why it passed
// while the page stayed broken.
import { createServer } from 'vite'
import { renderToStaticMarkup } from 'react-dom/server'
import React from 'react'

const vite = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'error' })
const { Markdown } = await vite.ssrLoadModule('/src/app/components/Markdown.tsx')
const DocMarkdown = (await vite.ssrLoadModule('/src/app/components/docs/DocMarkdown.tsx')).default

const md = `### Module Dependencies

![Module Dependencies](data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciLz4=)

<details>
<summary>Diagram source</summary>

\`\`\`d2
a -> b
\`\`\`

</details>

<script>alert('xss')</script>

![bad](data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)

[link](javascript:alert(1))
`

let bad = 0
for (const [label, Comp] of [['Markdown', Markdown], ['DocMarkdown', DocMarkdown]]) {
const html = renderToStaticMarkup(React.createElement(Comp, null, md))
const checks = [
  ['diagram img keeps its data: src', /<img[^>]*src="data:image\/svg\+xml;base64,/.test(html)],
  ['<details> rendered',              html.includes('<details>')],
  ['<summary> rendered',              html.includes('<summary>')],
  ['<script> stripped',               !html.includes('<script')],
  ['data:text/html blocked',          !html.includes('data:text/html')],
  ['javascript: href blocked',        !html.includes('javascript:')],
]
for (const [name, ok] of checks) { if (!ok) bad++; console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}: ${name}`) }
}
await vite.close()
process.exit(bad ? 1 : 0)
