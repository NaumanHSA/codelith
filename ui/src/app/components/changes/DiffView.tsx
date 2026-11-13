import { Fragment, useMemo, useState } from 'react'
import { highlightLines } from '../../lib/highlight'
import type { DiffRow } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * One file, line by line: split or unified, every line kept by both
 * readings, with long runs of unchanged lines folded until asked for.
 *
 * Each side is highlighted as a whole file (`highlightLines` gets a
 * block comment right only when it sees all of it) and then looked up
 * by line number. A line paired with the one it replaced shows the
 * words that changed instead of syntax colours: that is what a reader
 * is looking for on that line.
 * ------------------------------------------------------------------ */

/** Unchanged lines kept around each change before a run is folded. */
const CONTEXT = 3
/** Lines a fold opens by when asked; a fold smaller than this opens whole. */
const STEP = 20

type Item =
  | { type: 'row'; row: DiffRow }
  | { type: 'pair'; left: DiffRow | null; right: DiffRow | null }
  | { type: 'fold'; id: number; rows: DiffRow[] }

function escapeHtml(s: string) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

/** A line with its changed character ranges wrapped, as escaped HTML. */
function marked(text: string, marks: [number, number][], kind: 'add' | 'del') {
  let out = ''
  let at = 0
  for (const [a, b] of marks) {
    out += escapeHtml(text.slice(at, a))
    out += `<mark class="diff-mark diff-mark-${kind}">${escapeHtml(text.slice(a, b))}</mark>`
    at = b
  }
  return out + escapeHtml(text.slice(at))
}

/** Context runs longer than the context on both sides fold, except at a changed file's edges. */
function fold(rows: DiffRow[], opened: Map<number, number>): (DiffRow | { fold: number; rows: DiffRow[] })[] {
  const out: (DiffRow | { fold: number; rows: DiffRow[] })[] = []
  let i = 0
  let id = 0
  while (i < rows.length) {
    if (rows[i].kind !== 'context') {
      out.push(rows[i++])
      continue
    }
    let j = i
    while (j < rows.length && rows[j].kind === 'context') j++
    const run = rows.slice(i, j)
    const head = i === 0 ? 0 : CONTEXT
    const tail = j === rows.length ? 0 : CONTEXT
    const shown = opened.get(id) ?? 0
    if (run.length - head - tail - shown > 4) {
      out.push(...run.slice(0, head + shown))
      out.push({ fold: id, rows: run.slice(head + shown, run.length - tail) })
      out.push(...run.slice(run.length - tail))
    } else out.push(...run)
    id++
    i = j
  }
  return out
}

export function DiffView({
  rows,
  language,
  mode,
}: {
  rows: DiffRow[]
  language: string | null
  mode: 'split' | 'unified'
}) {
  const [opened, setOpened] = useState<Map<number, number>>(new Map())

  // Each side whole, highlighted once, then read back by line number.
  const { oldHtml, newHtml } = useMemo(() => {
    const oldRows = rows.filter(r => r.old !== null)
    const newRows = rows.filter(r => r.new !== null)
    const lang = language ?? ''
    const oldLines = highlightLines(oldRows.map(r => r.text).join('\n'), lang)
    const newLines = highlightLines(newRows.map(r => r.text).join('\n'), lang)
    const o = new Map<number, string>()
    const n = new Map<number, string>()
    oldRows.forEach((r, i) => o.set(r.old!, oldLines[i] ?? escapeHtml(r.text)))
    newRows.forEach((r, i) => n.set(r.new!, newLines[i] ?? escapeHtml(r.text)))
    return { oldHtml: o, newHtml: n }
  }, [rows, language])

  const items: Item[] = useMemo(() => {
    const flat = fold(rows, opened)
    const out: Item[] = []
    if (mode === 'unified') {
      for (const r of flat) out.push('fold' in r ? { type: 'fold', id: r.fold, rows: r.rows } : { type: 'row', row: r })
      return out
    }
    // Split: a run of removed lines beside the run of added lines that replaced it.
    let i = 0
    while (i < flat.length) {
      const r = flat[i]
      if ('fold' in r) {
        out.push({ type: 'fold', id: r.fold, rows: r.rows })
        i++
      } else if (r.kind === 'context') {
        out.push({ type: 'pair', left: r, right: r })
        i++
      } else {
        const dels: DiffRow[] = []
        const adds: DiffRow[] = []
        while (i < flat.length && !('fold' in flat[i]) && (flat[i] as DiffRow).kind === 'del') dels.push(flat[i++] as DiffRow)
        while (i < flat.length && !('fold' in flat[i]) && (flat[i] as DiffRow).kind === 'add') adds.push(flat[i++] as DiffRow)
        for (let k = 0; k < Math.max(dels.length, adds.length); k++)
          out.push({ type: 'pair', left: dels[k] ?? null, right: adds[k] ?? null })
      }
    }
    return out
  }, [rows, opened, mode])

  const open = (id: number, size: number) =>
    setOpened(m => new Map(m).set(id, (m.get(id) ?? 0) + (size <= STEP + 4 ? size : STEP)))

  const html = (r: DiffRow, side: 'old' | 'new') => {
    if (r.marks.length && r.kind !== 'context') return marked(r.text, r.marks, r.kind === 'add' ? 'add' : 'del')
    return (side === 'old' ? oldHtml.get(r.old!) : newHtml.get(r.new!)) ?? escapeHtml(r.text)
  }

  const cell = (r: DiffRow | null, side: 'old' | 'new') => {
    if (!r) return <td colSpan={2} className="diff-empty" />
    const n = side === 'old' ? r.old : r.new
    const tone = r.kind === 'add' ? 'diff-add' : r.kind === 'del' ? 'diff-del' : ''
    return (
      <>
        <td className={`diff-num ${tone}`}>{n}</td>
        <td className={`diff-code ${tone}`}>
          <span className="diff-sign">{r.kind === 'add' ? '+' : r.kind === 'del' ? '-' : ' '}</span>
          <span dangerouslySetInnerHTML={{ __html: html(r, side) || '&nbsp;' }} />
        </td>
      </>
    )
  }

  return (
    <div className="diff overflow-x-auto">
      <table className={`diff-table ${mode === 'split' ? 'diff-split' : ''}`}>
        {/* A fixed layout takes its widths from the first row, which may be a fold
            spanning every column: the widths are set here instead. */}
        <colgroup>
          {mode === 'split' ? (
            <>
              <col className="diff-col-num" />
              <col />
              <col className="diff-col-num" />
              <col />
            </>
          ) : (
            <>
              <col className="diff-col-num" />
              <col className="diff-col-num" />
              <col />
            </>
          )}
        </colgroup>
        <tbody>
          {items.map((item, k) => {
            if (item.type === 'fold')
              return (
                <tr key={`f${item.id}-${k}`} className="diff-fold">
                  <td colSpan={mode === 'split' ? 4 : 3}>
                    <button type="button" onClick={() => open(item.id, item.rows.length)}>
                      {item.rows.length <= STEP + 4
                        ? `Show ${item.rows.length} unchanged lines`
                        : `Show ${STEP} more of ${item.rows.length} unchanged lines`}
                    </button>
                  </td>
                </tr>
              )
            if (item.type === 'pair')
              return (
                <tr key={k}>
                  {cell(item.left, 'old')}
                  {cell(item.right, 'new')}
                </tr>
              )
            const r = item.row
            const tone = r.kind === 'add' ? 'diff-add' : r.kind === 'del' ? 'diff-del' : ''
            return (
              <Fragment key={k}>
                <tr>
                  <td className={`diff-num ${tone}`}>{r.old}</td>
                  <td className={`diff-num ${tone}`}>{r.new}</td>
                  <td className={`diff-code ${tone}`}>
                    <span className="diff-sign">{r.kind === 'add' ? '+' : r.kind === 'del' ? '-' : ' '}</span>
                    <span dangerouslySetInnerHTML={{ __html: html(r, r.kind === 'del' ? 'old' : 'new') || '&nbsp;' }} />
                  </td>
                </tr>
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
