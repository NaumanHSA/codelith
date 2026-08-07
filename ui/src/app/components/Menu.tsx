import { useEffect, useId, useRef, useState, type ReactNode } from 'react'

/* ------------------------------------------------------------------ *
 * A small actions menu, opened by a button that is always visible.
 *
 * It replaced a `✕` that only appeared on hover, which is a fine way to
 * keep a list clean and a poor way to tell anyone the action exists —
 * on a touch screen there is no hover at all, so it existed for nobody.
 * The trigger stays quiet until you look at it, but it is always there.
 *
 * Closes on Escape, on a click outside, and on choosing something.
 * ------------------------------------------------------------------ */

export interface MenuItem {
  label: string
  onSelect: () => void
  /** Marks the entry as destructive — rendered in the bad tone. */
  danger?: boolean
  disabled?: boolean
  /** Shown greyed under the label; use it to say *why* something is disabled. */
  hint?: string
}

export default function Menu({
  items,
  label = 'Actions',
  align = 'right',
  trigger,
}: {
  items: MenuItem[]
  label?: string
  align?: 'left' | 'right'
  /** Defaults to the three-dot button. */
  trigger?: ReactNode
}) {
  const [open, setOpen] = useState(false)
  const wrap = useRef<HTMLDivElement>(null)
  const id = useId()

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    // `mousedown`, not `click`: a menu that survives until mouseup flickers when the
    // press lands on the element behind it.
    const onDown = (e: MouseEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown)
    }
  }, [open])

  const usable = items.filter(i => !i.disabled || i.hint)
  if (!usable.length) return null

  return (
    <div ref={wrap} className="relative shrink-0">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        aria-label={label}
        title={label}
        onClick={e => {
          e.stopPropagation()
          e.preventDefault()
          setOpen(o => !o)
        }}
        className={`flex h-[22px] w-[20px] items-center justify-center border text-[13px] leading-none transition-colors ${
          open
            ? 'border-hot bg-hot-wash text-hot-ink'
            : 'border-transparent text-ink-dim hover:border-rule hover:bg-panel hover:text-ink'
        }`}
      >
        {trigger ?? <span aria-hidden>⋯</span>}
      </button>

      {open && (
        <ul
          id={id}
          role="menu"
          className={`absolute top-full z-40 mt-1 min-w-[190px] border border-rule bg-panel py-1 shadow-lg ${
            align === 'right' ? 'right-0' : 'left-0'
          }`}
        >
          {items.map(item => (
            <li key={item.label} role="none">
              <button
                role="menuitem"
                disabled={item.disabled}
                onClick={e => {
                  e.stopPropagation()
                  e.preventDefault()
                  setOpen(false)
                  item.onSelect()
                }}
                className={`block w-full px-3 py-[6px] text-left text-[11.5px] transition-colors ${
                  item.disabled
                    ? 'cursor-not-allowed text-ink-dim/60'
                    : item.danger
                      ? 'text-bad hover:bg-bad/10'
                      : 'text-ink-mid hover:bg-hot-wash hover:text-hot-ink'
                }`}
              >
                {item.label}
                {item.hint && (
                  <span className="mt-[1px] block text-[10px] leading-snug text-ink-dim">
                    {item.hint}
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
