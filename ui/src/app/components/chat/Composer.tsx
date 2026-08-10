import { useEffect, useRef } from 'react'
import { ContextWheel } from './ContextWheel'

/* ------------------------------------------------------------------ *
 * The thing you type into.
 *
 * Grows with the question and stops: a textarea that keeps growing
 * eventually pushes the conversation off the screen, and one that never
 * grows makes a five-line question unreadable while it is being written.
 * Past the ceiling it scrolls inside itself.
 *
 * The attachment button is present and disabled. A control that looks
 * live and does nothing is worse than one that says what it is — the
 * tooltip is doing the honest work here.
 * ------------------------------------------------------------------ */

const MIN_HEIGHT = 24
const MAX_HEIGHT = 200

export function Composer({
  value,
  onChange,
  onSend,
  onStop,
  busy,
  used,
  total,
  autoFocus = false,
  placeholder = 'Ask about this codebase…',
}: {
  value: string
  onChange: (next: string) => void
  onSend: () => void
  onStop: () => void
  busy: boolean
  used: number
  total: number
  autoFocus?: boolean
  placeholder?: string
}) {
  const ref = useRef<HTMLTextAreaElement>(null)

  // Height follows content. Reset to `auto` first or `scrollHeight` reports the
  // previous height and the box only ever grows.
  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(Math.max(el.scrollHeight, MIN_HEIGHT), MAX_HEIGHT)}px`
  }, [value])

  useEffect(() => {
    if (autoFocus) ref.current?.focus()
  }, [autoFocus])

  const canSend = value.trim().length > 0 && !busy

  return (
    // The wrapper carries the focus state, not the textarea. An outline follows
    // the focused element's own radius, so a square field inside a rounded panel
    // drew a rectangle cutting across the corners — see `.focus-ring-inherit`.
    <div className="rounded-xl border border-rule bg-panel shadow-sm transition-colors focus-within:border-hot focus-within:ring-1 focus-within:ring-hot/25">
      <textarea
        ref={ref}
        value={value}
        onChange={e => onChange(e.target.value)}
        onKeyDown={e => {
          // Enter sends; Shift+Enter is a newline. A question about code is
          // often several lines, so the modifier has to do something useful.
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            if (canSend) onSend()
          }
        }}
        rows={1}
        placeholder={placeholder}
        className="focus-ring-inherit block w-full resize-none bg-transparent px-4 pt-3.5 text-[13px] leading-relaxed text-ink outline-none placeholder:text-ink-dim"
        style={{ maxHeight: MAX_HEIGHT, overflowY: 'auto' }}
      />

      <div className="flex items-center justify-between px-3 pb-2.5 pt-1">
        <div className="flex items-center gap-1">
          <button
            type="button"
            disabled
            title="Attachments are not wired up yet"
            className="flex h-7 w-7 items-center justify-center rounded-md text-ink-dim opacity-40"
            aria-label="Attach a file (not available yet)"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
            </svg>
          </button>
          <span className="hidden text-[10px] text-ink-dim sm:inline">
            Enter to send · Shift+Enter for a new line
          </span>
        </div>

        <div className="flex items-center gap-3">
          <ContextWheel used={used} total={total} />
          {busy ? (
            <button
              type="button"
              onClick={onStop}
              className="flex h-7 items-center gap-1.5 rounded-md border border-rule px-2.5 text-[11px] text-ink-mid hover:border-hot hover:text-hot-ink"
            >
              <span className="block h-2 w-2 rounded-[1px] bg-current" />
              stop
            </button>
          ) : (
            <button
              type="button"
              onClick={onSend}
              disabled={!canSend}
              aria-label="Send"
              className="flex h-7 w-7 items-center justify-center rounded-md bg-hot text-white transition-opacity disabled:opacity-30"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path d="M12 19V5M5 12l7-7 7 7" />
              </svg>
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
