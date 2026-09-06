// What the code viewer is allowed to put on the page, and how fast.
//
// Two properties, and the second one is why this file exists. The viewer needs one
// element per line, so a highlighted block is split at newlines with its open spans
// carried across, and the result goes through `dangerouslySetInnerHTML`.
//
// The first version verified that output with
// `^(?:<span …>|</span>|[^<>]*)*$` - a group that can match the empty string under
// a `*`. On input that fails to match, that backtracks exponentially. It did not
// throw and it did not render wrongly: it pinned the browser's main thread so hard
// that Playwright could not take a screenshot of the page, and it took a request
// trace to find. A correctness test would have passed. So this one is also a clock.
import { createServer } from 'vite'

const vite = await createServer({
  server: { middlewareMode: true },
  appType: 'custom',
  logLevel: 'error',
})
const { highlightLines, splitHighlighted } = await vite.ssrLoadModule(
  '/src/app/lib/highlight.ts',
)

const js = `export const ErrorCode = Object.freeze({
  INVALID_CONFIG: "INVALID_CONFIG",
});

/* a block comment
   running over lines */
export function makeError(code, message) {
  const s = \`rgba(\${code}, 1)\`
  return { code, message, s }
}`

const checks = []
const check = (name, ok) => checks.push([name, ok])

// ── Line integrity ──────────────────────────────────────────────────────────
// A highlighter that loses or gains a line slides every line number after it, and
// the gutter would then be confidently wrong rather than merely unstyled.
const lines = highlightLines(js, 'javascript')
check('one entry per source line', lines.length === js.split('\n').length)
check('something was highlighted', lines.join('').includes('<span class="hljs-'))

// A multi-line comment must stay a comment on every line it covers. This is the
// whole reason the block is highlighted once rather than line by line.
const commentLines = lines.slice(4, 6)
check(
  'a block comment is a comment on both its lines',
  commentLines.every(l => l.includes('hljs-comment')),
)

// Every line has to be independently valid: spans opened earlier are closed at the
// end of the line and reopened on the next.
check(
  'each line balances its own spans',
  lines.every(l => (l.match(/<span/g) ?? []).length === (l.match(/<\/span>/g) ?? []).length),
)

// ── Escaping ────────────────────────────────────────────────────────────────
// Source is attacker-controlled in the only sense that matters: somebody analysed
// a repository they did not write.
const nasty = highlightLines('const x = "<script>alert(1)</script>"', 'javascript')
check('script tags in source are escaped', !nasty.join('').includes('<script'))

const unknown = highlightLines('<b>raw</b>', 'not-a-language')
check('unknown language falls back to escaped text', unknown[0] === '&lt;b&gt;raw&lt;/b&gt;')
check('empty language falls back too', highlightLines('<b>', '')[0] === '&lt;b&gt;')

// ── Splitting ───────────────────────────────────────────────────────────────
check(
  'a span crossing a newline becomes one per line',
  JSON.stringify(splitHighlighted('<span class="hljs-string">a\nb</span>')) ===
    JSON.stringify(['<span class="hljs-string">a</span>', '<span class="hljs-string">b</span>']),
)
check('plain text passes through', splitHighlighted('a\nb').join('|') === 'a|b')
check('no newline is one line', splitHighlighted('abc').length === 1)

// ── The clock ───────────────────────────────────────────────────────────────
// A minified bundle in the sample repository is 360 KB. Highlighting it, or
// deciding not to, must not take a perceptible amount of time - and must not take
// exponential time on input the verifier rejects.
const minified = `var a=1;${'x'.repeat(60_000)}<>${'y'.repeat(60_000)};\n`.repeat(3)
const started = Date.now()
highlightLines(minified, 'javascript')
const elapsed = Date.now() - started
check(`pathological input finishes fast (${elapsed}ms)`, elapsed < 2_000)

let bad = 0
for (const [name, ok] of checks) {
  if (!ok) bad++
  console.log(`${ok ? 'PASS' : 'FAIL'}  highlight: ${name}`)
}
await vite.close()
process.exit(bad ? 1 : 0)
