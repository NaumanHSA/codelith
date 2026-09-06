import { useEffect, useMemo, useRef } from 'react'
import { highlightLines } from '../../lib/highlight'
import type { CodeSegment, SourceFile } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * The source, with the holes in it left open.
 *
 * The product's claim is that it read the repository. This is the first
 * surface that shows any of what it read, which makes being straight
 * about what is missing more important than looking complete.
 *
 * Analysis discards the clone, so there is no file to open: what
 * arrives is a reconstruction from stored chunks, and those chunks
 * overlap in places and leave holes in others. A hole is drawn as a
 * hole, with the line numbers it spans. Closing it by sliding the next
 * chunk up would show line 17 directly under line 15 and a reader would
 * have no way to know.
 *
 * On this codebase the holes are almost always the blank line between
 * two declarations. "Almost always" is not a thing worth guessing on
 * somebody's behalf.
 * ------------------------------------------------------------------ */

/** A single line longer than this is a minified bundle, not something anyone is
 *  reading left to right. Truncated with the count, rather than handed to the
 *  browser as a two-hundred-thousand-pixel row. */
const LINE_LIMIT = 2_000

type Props = {
  file: SourceFile
  /** From the URL hash, so a citation can point at lines. */
  range: [number, number] | null
  onPickLine: (line: number, extend: boolean) => void
}

export default function CodeView({ file, range, onPickLine }: Props) {
  const scroller = useRef<HTMLDivElement>(null)
  const anchor = useRef<HTMLDivElement>(null)

  // Highlighted per segment rather than per file: the segments are not contiguous,
  // so joining them to highlight in one pass would let a string opened before a gap
  // colour everything after it.
  const highlighted = useMemo(
    () =>
      file.segments.map(s => {
        if (s.kind !== 'code') return []
        // Trimmed here, before the highlighter sees it. Truncating the HTML
        // afterwards would cut mid-tag or mid-entity and hand the browser markup
        // to guess at.
        const text = trimLongLines(s.text)
        return highlightLines(text, file.language)
      }),
    [file],
  )

  const coloured = useMemo(
    () => highlighted.some(lines => lines.some(line => line.includes('hljs-'))),
    [highlighted],
  )

  // A linked range is only useful if you land on it.
  useEffect(() => {
    if (range && anchor.current) {
      anchor.current.scrollIntoView({ block: 'center', behavior: 'auto' })
    } else if (scroller.current) {
      scroller.current.scrollTop = 0
    }
  }, [range, file.path])

  if (!file.indexed) {
    return (
      <div className="p-6 text-center">
        <p className="font-sans text-[12.5px] text-ink-mid">
          Analysis saw <span className="font-semibold text-ink">{file.path}</span> and kept
          no source for it.
        </p>
        <p className="mx-auto mt-1.5 max-w-[46ch] font-sans text-[11.5px] leading-relaxed text-ink-dim">
          The repository is cloned, read and discarded, so the indexed chunks are the
          only copy of anything. A file with no code chunks was seen but not stored.
        </p>
      </div>
    )
  }

  let seen = 0

  return (
    <div ref={scroller} className="max-h-[70vh] overflow-auto">
      <div className="min-w-full font-mono text-[11.5px] leading-[1.55]">
        {file.segments.map((segment, index) =>
          segment.kind === 'gap' ? (
            <Gap key={`g${segment.start}`} segment={segment} />
          ) : (
            <div key={`c${segment.start}`}>
              {highlighted[index].map((html, i) => {
                const line = segment.start + i
                const on = !!range && line >= range[0] && line <= range[1]
                const first = !!range && line === range[0]
                if (on) seen++
                return (
                  <div
                    key={line}
                    ref={first ? anchor : undefined}
                    id={`L${line}`}
                    className={`flex ${on ? 'bg-hot-wash' : ''}`}
                  >
                    <button
                      type="button"
                      onClick={e => onPickLine(line, e.shiftKey)}
                      title="Link to this line. Shift-click to extend."
                      className={`w-[52px] shrink-0 select-none border-r border-rule px-2 text-right tabular-nums ${
                        on ? 'bg-hot-wash text-hot-ink' : 'bg-sunk/40 text-ink-dim'
                      } hover:text-hot-ink`}
                    >
                      {line}
                    </button>
                    <code
                      className="whitespace-pre px-3 text-ink"
                      dangerouslySetInnerHTML={{ __html: html }}
                    />
                  </div>
                )
              })}
            </div>
          ),
        )}
      </div>

      {/* Asked of the output rather than recomputed from the limit: the guard is
          per segment, so a file can be part coloured, and the label should say
          what happened rather than what was predicted. */}
      <Footnote file={file} highlighted={coloured} linked={range ? seen : 0} />
    </div>
  )
}

/** A run of lines nothing stored. Drawn at the width of the file so it reads as a
 *  break in it, not as a note beside it. */
function Gap({ segment }: { segment: CodeSegment }) {
  const n = segment.end - segment.start + 1
  return (
    <div className="flex items-center gap-2 border-y border-dashed border-rule bg-sunk/30 py-[3px]">
      <span className="w-[52px] shrink-0 select-none border-r border-rule px-2 text-right text-ink-dim">
        ⋯
      </span>
      <span className="px-1 text-[10.5px] tracking-wide text-ink-dim">
        {n === 1 ? `line ${segment.start}` : `lines ${segment.start}-${segment.end}`} not
        indexed
      </span>
    </div>
  )
}

/** What the reader is looking at, and what they are not. */
function Footnote({
  file,
  highlighted,
  linked,
}: {
  file: SourceFile
  highlighted: boolean
  linked: number
}) {
  return (
    <div className="sticky bottom-0 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-rule bg-panel/95 px-3 py-1.5 backdrop-blur">
      <span className="tag text-ink-dim">
        {file.lines_indexed.toLocaleString()} lines from {file.chunks} chunk
        {file.chunks === 1 ? '' : 's'}
      </span>
      {file.lines_missing > 0 && (
        <span className="tag text-warn">{file.lines_missing} not indexed</span>
      )}
      {linked > 0 && <span className="tag text-hot-ink">{linked} linked</span>}
      {!highlighted && <span className="tag text-ink-dim">too large to highlight</span>}
      {file.commit_sha && (
        <span className="tag text-ink-dim">as read at {file.commit_sha.slice(0, 7)}</span>
      )}
    </div>
  )
}

/** A 205 KB line is a minified bundle, and this codebase has one. Handed to the
 *  browser whole it makes a row nothing can scroll past; the count says what was
 *  cut, so the reader knows the line continues rather than assuming it ended. */
function trimLongLines(text: string): string {
  if (text.length <= LINE_LIMIT) return text
  return text
    .split('\n')
    .map(line =>
      line.length <= LINE_LIMIT
        ? line
        : `${line.slice(0, LINE_LIMIT)} … ${(line.length - LINE_LIMIT).toLocaleString()} more characters on this line`,
    )
    .join('\n')
}
