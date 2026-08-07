import { useRef, useState, type ReactNode } from 'react'

/* ------------------------------------------------------------------ *
 * A tooltip that belongs to this studio.
 *
 * The native `title` attribute renders as the operating system's black
 * box, in the OS font, after a delay nobody chose — the one piece of a
 * page that ignores every token in `theme.css`. Where the text is worth
 * reading (a page's intent, truncated in a nav) it is worth drawing
 * properly.
 *
 * Deliberately not a general popover: no portal, no flipping, no arrow.
 * It positions above or below its trigger and wraps to a readable
 * measure, which is all any caller here needs.
 * ------------------------------------------------------------------ */

export default function Tooltip({
  content,
  children,
  side = 'bottom',
  className = '',
}: {
  /** Nothing renders when this is empty, so callers need not check. */
  content: ReactNode
  children: ReactNode
  side?: 'top' | 'bottom'
  className?: string
}) {
  const [open, setOpen] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  if (!content) return <>{children}</>

  const show = () => {
    // A short delay, or every pass of the mouse across a list flashes a tooltip.
    clearTimeout(timer.current)
    timer.current = setTimeout(() => setOpen(true), 320)
  }
  const hide = () => {
    clearTimeout(timer.current)
    setOpen(false)
  }

  return (
    <span
      className={`relative ${className}`}
      onMouseEnter={show}
      onMouseLeave={hide}
      // Keyboard users get it too, and without the delay: focus is deliberate in a
      // way that moving a mouse across a row is not.
      onFocus={() => setOpen(true)}
      onBlur={hide}
    >
      {children}
      {open && (
        <span
          role="tooltip"
          className={`pointer-events-none absolute left-0 z-50 w-[260px] border border-rule bg-panel px-2.5 py-1.5 text-[11px] leading-relaxed font-normal tracking-normal text-ink-mid shadow-lg ${
            side === 'top' ? 'bottom-full mb-1.5' : 'top-full mt-1.5'
          }`}
        >
          <span className="absolute top-0 left-0 h-full w-[2px] bg-hot" aria-hidden />
          <span className="block pl-1.5 normal-case">{content}</span>
        </span>
      )}
    </span>
  )
}
