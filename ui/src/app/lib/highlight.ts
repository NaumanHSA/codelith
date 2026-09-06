import hljs from 'highlight.js/lib/common'

/* ------------------------------------------------------------------ *
 * Syntax highlighting, one line at a time.
 *
 * The code viewer needs a DOM element per line: line numbers in a
 * gutter, a band behind a linked range, an anchor to scroll to. A
 * highlighter gives back one blob of HTML for a whole block, and the
 * naive fix - highlighting each line on its own - gets multi-line
 * constructs wrong. A block comment becomes a comment on its first line
 * and syntax on the rest; a template literal is worse.
 *
 * So the block is highlighted once, as it should be, and the result is
 * split at newlines with the open spans closed at the end of each line
 * and reopened at the start of the next. That is the standard trick and
 * it is exact, because the only tags highlight.js emits are its own
 * spans over text it has already escaped.
 *
 * "Already escaped" is load-bearing: this HTML goes through
 * `dangerouslySetInnerHTML`. `verify` re-checks it rather than trusting
 * the claim, and anything unexpected falls back to escaped plain text.
 * A file's contents are attacker-controlled in the only sense that
 * matters here - somebody analysed a repository they did not write.
 * ------------------------------------------------------------------ */

/**
 * The only tags highlight.js emits: its own opening spans and their closes.
 *
 * Written as a strip-and-check rather than a whole-string match. The obvious
 * `^(?:<span …>|</span>|[^<>]*)*$` is a group that can match the empty string
 * under a `*`, which backtracks exponentially the moment the string does *not*
 * match - and the first thing it was handed hung the browser's main thread hard
 * enough that Playwright could not take a screenshot. Removing the allowed tags
 * and asking whether an angle bracket survived is linear and answers the same
 * question.
 *
 * The class pattern is deliberately loose. highlight.js emits multiple classes on
 * one span and `language-…` for sublanguages, and a verifier narrower than the
 * thing it verifies just means falling back to unstyled text for no reason.
 */
const ALLOWED_TAG = /<span class="[A-Za-z0-9 _-]*">|<\/span>/g

function isHljsOnly(html: string): boolean {
  // Text is escaped by highlight.js, so a surviving bracket means a tag we did
  // not expect.
  return !/[<>]/.test(html.replace(ALLOWED_TAG, ''))
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

/**
 * Split highlighted HTML into one string per line, spans carried across.
 *
 * A span opened on line 4 and closed on line 9 becomes six spans, one per line,
 * so that every line is independently valid HTML and can be its own element.
 */
export function splitHighlighted(html: string): string[] {
  const lines: string[] = []
  const open: string[] = []
  let current = ''
  let i = 0

  while (i < html.length) {
    if (html[i] === '<') {
      const close = html.indexOf('>', i)
      if (close === -1) {
        // Truncated tag: nothing sane to do but keep the text and stop.
        current += html.slice(i)
        break
      }
      const tag = html.slice(i, close + 1)
      if (tag.startsWith('</')) open.pop()
      else if (!tag.endsWith('/>')) open.push(tag)
      current += tag
      i = close + 1
      continue
    }

    const newline = html.indexOf('\n', i)
    const nextTag = html.indexOf('<', i)
    const stop = Math.min(
      newline === -1 ? html.length : newline,
      nextTag === -1 ? html.length : nextTag,
    )

    current += html.slice(i, stop)
    if (stop === newline) {
      lines.push(current + '</span>'.repeat(open.length))
      current = open.join('')
      i = stop + 1
    } else {
      i = stop
    }
  }

  lines.push(current + '</span>'.repeat(open.length))
  return lines
}

/**
 * Past this, highlight.js is the bottleneck and it is not close.
 *
 * A 360 KB minified bundle in the sample repository takes highlight.js twenty-four
 * seconds, on the main thread, with nothing to show for it: a minified file has no
 * structure worth colouring. The limit lives here rather than in the component
 * because it is a fact about the highlighter, and a guard only one caller knows
 * about protects only that caller.
 */
export const HIGHLIGHT_LIMIT = 220_000

/**
 * A block of source as highlighted lines.
 *
 * An unknown or unsupported language is not an error, and neither is a file too
 * large to be worth it: the lines come back escaped and unstyled, which is what
 * the viewer should show for anything it cannot colour.
 */
export function highlightLines(code: string, language: string): string[] {
  const plain = () => code.split('\n').map(escapeHtml)

  if (code.length > HIGHLIGHT_LIMIT) return plain()

  const name = language.trim().toLowerCase()
  if (!name || !hljs.getLanguage(name)) return plain()

  try {
    const html = hljs.highlight(code, { language: name, ignoreIllegals: true }).value
    // Cheaper than parsing, and it fails closed: anything outside the grammar
    // above means the fallback renders escaped text instead.
    if (!isHljsOnly(html)) return plain()
    const lines = splitHighlighted(html)
    // A highlighter that lost or gained a line would slide every line number after
    // it. Better to show the file unstyled than to number it wrongly.
    return lines.length === code.split('\n').length ? lines : plain()
  } catch {
    return plain()
  }
}
