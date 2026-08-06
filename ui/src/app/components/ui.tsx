import {
  useEffect, useId, useRef, type ReactNode,
} from 'react'

/* ------------------------------------------------------------------ *
 * Shared brutalist primitives. Hard hairlines, zero radius, mono type.
 * All colour comes from tokens in styles/theme.css.
 * ------------------------------------------------------------------ */

const SIGNAL: Record<string, { fg: string; bg: string; bd: string }> = {
  completed: { fg: 'text-ok', bg: 'bg-ok-wash', bd: 'border-ok/35' },
  ready: { fg: 'text-ok', bg: 'bg-ok-wash', bd: 'border-ok/35' },
  published: { fg: 'text-ok', bg: 'bg-ok-wash', bd: 'border-ok/35' },
  active: { fg: 'text-ok', bg: 'bg-ok-wash', bd: 'border-ok/35' },
  running: { fg: 'text-hot-ink', bg: 'bg-hot-wash', bd: 'border-hot-edge' },
  pending: { fg: 'text-ink-dim', bg: 'bg-sunk', bd: 'border-rule' },
  queued: { fg: 'text-ink-dim', bg: 'bg-sunk', bd: 'border-rule' },
  draft: { fg: 'text-ink-dim', bg: 'bg-sunk', bd: 'border-rule' },
  skipped: { fg: 'text-ink-dim', bg: 'bg-sunk', bd: 'border-rule' },
  failed: { fg: 'text-bad', bg: 'bg-bad-wash', bd: 'border-bad/35' },
  cancelled: { fg: 'text-ink-dim', bg: 'bg-sunk', bd: 'border-rule' },
  degraded: { fg: 'text-warn', bg: 'bg-warn-wash', bd: 'border-warn/35' },
  stale: { fg: 'text-warn', bg: 'bg-warn-wash', bd: 'border-warn/35' },
  review: { fg: 'text-warn', bg: 'bg-warn-wash', bd: 'border-warn/35' },
  awaiting_review: { fg: 'text-warn', bg: 'bg-warn-wash', bd: 'border-warn/35' },
}

export function StatusBadge({ status, size = 'sm' }: { status: string; size?: 'sm' | 'md' }) {
  const c = SIGNAL[status] ?? SIGNAL.pending
  return (
    <span
      className={`tag inline-flex shrink-0 items-center gap-1.5 border ${c.bg} ${c.bd} ${c.fg} ${
        size === 'md' ? 'px-2 py-1' : 'px-1.5 py-[3px]'
      }`}
    >
      {status === 'running' && (
        <span className="anim-spin block size-[7px] rounded-full border border-current border-t-transparent" />
      )}
      {status === 'completed' && <span className="block size-[5px] bg-ok" />}
      {status.replace(/_/g, ' ')}
    </span>
  )
}

/** Uppercase tracked section eyebrow with a rule that fills the row. */
export function Eyebrow({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex items-center gap-3">
      <span className="tag shrink-0 text-ink-dim">{children}</span>
      <span className="h-px flex-1 bg-rule" />
      {right}
    </div>
  )
}

/** Boxed panel with a hairline header strip. */
export function Panel({
  title, index, action, children, className = '', bodyClass = '',
}: {
  title?: ReactNode
  index?: string
  action?: ReactNode
  children: ReactNode
  className?: string
  bodyClass?: string
}) {
  return (
    <section className={`plate ${className}`}>
      {title && (
        <header className="flex items-center gap-2.5 border-b border-rule bg-sunk/60 px-3 py-2">
          {index && <span className="tag text-hot-ink">{index}</span>}
          <h2 className="text-[11.5px] font-semibold tracking-tight text-ink">{title}</h2>
          <div className="ml-auto flex items-center gap-2">{action}</div>
        </header>
      )}
      <div className={bodyClass}>{children}</div>
    </section>
  )
}

/** Dense key/value row used across sidebars. */
export function Stat({ k, v, hot = false }: { k: string; v: ReactNode; hot?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-rule px-3 py-1.5 last:border-b-0">
      <span className="tag text-ink-dim">{k}</span>
      <span className={`text-[12px] font-semibold ${hot ? 'text-hot-ink' : 'text-ink'}`}>{v}</span>
    </div>
  )
}

/** Segmented confidence meter — discrete ticks, filled to pct. */
export function Meter({ pct, segments = 20 }: { pct: number; segments?: number }) {
  const filled = Math.round((Math.max(0, Math.min(100, pct)) / 100) * segments)
  return (
    <span className="inline-flex items-center gap-[2px]" aria-hidden>
      {Array.from({ length: segments }, (_, i) => (
        <span
          key={i}
          className={`block h-[9px] w-[3px] transition-colors duration-150 ${
            i < filled ? 'bg-hot' : 'bg-rule'
          }`}
        />
      ))}
    </span>
  )
}

export function Chip({
  children, tone = 'plain', onClick, active, title,
}: {
  children: ReactNode
  tone?: 'plain' | 'hot' | 'bad' | 'warn'
  onClick?: () => void
  active?: boolean
  title?: string
}) {
  const base =
    'tag border px-1.5 py-[3px] transition-colors duration-150 whitespace-nowrap normal-case tracking-[0.04em]'
  const tones =
    active || tone === 'hot'
      ? 'border-hot-edge bg-hot-wash text-hot-ink'
      : tone === 'bad'
        ? 'border-bad/35 bg-bad-wash text-bad'
        : tone === 'warn'
          ? 'border-warn/35 bg-warn-wash text-warn'
          : 'border-rule bg-sunk text-ink-mid'
  return onClick ? (
    <button
      type="button"
      title={title}
      onClick={onClick}
      className={`${base} ${tones} cursor-pointer hover:border-ink hover:text-ink`}
    >
      {children}
    </button>
  ) : (
    <span title={title} className={`${base} ${tones}`}>
      {children}
    </span>
  )
}

export function Button({
  children, onClick, variant = 'ghost', disabled, type = 'button', className = '', title,
}: {
  children: ReactNode
  onClick?: () => void
  variant?: 'hot' | 'ghost' | 'solid' | 'danger'
  disabled?: boolean
  type?: 'button' | 'submit'
  className?: string
  title?: string
}) {
  const v = {
    hot: 'bg-hot text-on-hot border-hot hover:bg-hot-press hover:border-hot-press',
    solid: 'bg-ink text-paper border-ink hover:bg-hot hover:border-hot',
    ghost: 'bg-panel text-ink-mid border-rule hover:border-ink hover:text-ink',
    danger: 'bg-bad-wash text-bad border-bad/40 hover:border-bad hover:bg-bad hover:text-on-hot',
  }[variant]
  return (
    <button
      type={type}
      title={title}
      onClick={onClick}
      disabled={disabled}
      className={`tag inline-flex items-center justify-center gap-1.5 border px-3 py-[7px] transition-colors duration-150 disabled:cursor-not-allowed disabled:border-rule disabled:bg-sunk disabled:text-ink-dim ${v} ${className}`}
    >
      {children}
    </button>
  )
}

/** Page header: oversized index numeral + title + breadcrumb rail. */
export function PageHead({
  index, title, sub, back, right,
}: {
  index: string
  title: string
  sub?: ReactNode
  back?: { label: string; onClick: () => void }
  right?: ReactNode
}) {
  // Sticky, because the actions that live here — back, publish, export — were
  // unreachable on a long document without scrolling all the way up again. The
  // scroll container is the shell's main pane, so `top-0` pins to the top of the
  // reading area. The negative top margin and matching padding let the surface
  // cover content passing beneath it without adding a visible gap when unstuck.
  return (
    <header className="sticky top-0 z-20 -mt-5 mb-4 border-b border-rule bg-paper pt-5 pb-3">
      {back && (
        <button
          onClick={back.onClick}
          className="tag mb-2 flex items-center gap-1.5 text-ink-dim transition-colors hover:text-hot-ink"
        >
          <span aria-hidden>←</span> {back.label}
        </button>
      )}
      <div className="flex flex-wrap items-end gap-x-4 gap-y-2">
        <span className="text-[34px] leading-[0.8] font-bold tracking-tighter text-rule select-none">
          {index}
        </span>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-[19px] leading-tight font-bold tracking-tight text-ink">
            {title}
          </h1>
          {sub && <div className="mt-1 text-[11.5px] text-ink-dim">{sub}</div>}
        </div>
        {right && <div className="flex flex-wrap items-center gap-2">{right}</div>}
      </div>
    </header>
  )
}

/* ------------------------------------------------------------------ *
 * Form controls
 * ------------------------------------------------------------------ */

export const inputClass =
  'w-full border border-rule bg-sunk/60 px-2.5 py-[7px] font-mono text-[12px] text-ink transition-colors placeholder:text-ink-dim focus:border-hot focus:bg-panel focus:outline-none disabled:opacity-60'

export function Field({
  label, help, error, children,
}: {
  label: string
  help?: ReactNode
  error?: string | null
  children: ReactNode
}) {
  return (
    <label className="block">
      <span className="tag mb-1.5 block text-ink-dim">{label}</span>
      {children}
      {error ? (
        <span className="mt-1.5 block text-[10.5px] leading-snug text-bad">{error}</span>
      ) : help ? (
        <span className="mt-1.5 block text-[10.5px] leading-snug text-ink-dim">{help}</span>
      ) : null}
    </label>
  )
}

/* ------------------------------------------------------------------ *
 * Dialog — focus trapped, Escape closes, scroll locked.
 * ------------------------------------------------------------------ */

export function Dialog({
  open, onClose, title, children, width = 520,
}: {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  width?: number
}) {
  const ref = useRef<HTMLDivElement>(null)
  const titleId = useId()

  useEffect(() => {
    if (!open) return
    const previous = document.activeElement as HTMLElement | null
    document.body.style.overflow = 'hidden'

    // Focus the first control so keyboard users land inside the dialog.
    const focusables = () =>
      Array.from(
        ref.current?.querySelectorAll<HTMLElement>(
          'a[href],button:not([disabled]),input:not([disabled]),select,textarea,[tabindex]:not([tabindex="-1"])',
        ) ?? [],
      )
    focusables()[0]?.focus()

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onClose()
        return
      }
      if (e.key !== 'Tab') return
      const items = focusables()
      if (!items.length) return
      const first = items[0]
      const last = items[items.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('keydown', onKey, true)
      document.body.style.overflow = ''
      previous?.focus?.()
    }
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-100 flex items-start justify-center overflow-y-auto p-4 sm:p-8">
      <div
        className="fixed inset-0 bg-ink/45"
        onClick={onClose}
        aria-hidden
      />
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        style={{ maxWidth: width }}
        className="anim-rise relative w-full border border-ink bg-panel shadow-[6px_6px_0_0_var(--ink)]"
      >
        <header className="flex items-center gap-2.5 border-b border-rule bg-sunk/60 px-3 py-2">
          <span className="block size-2 rotate-45 bg-hot" />
          <h2 id={titleId} className="text-[12px] font-bold tracking-tight text-ink">
            {title}
          </h2>
          <button
            onClick={onClose}
            aria-label="Close dialog"
            className="tag ml-auto px-1 text-ink-dim transition-colors hover:text-hot-ink"
          >
            esc ✕
          </button>
        </header>
        {children}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ *
 * Marks
 * ------------------------------------------------------------------ */

export const GitHubMark = ({ size = 14 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden>
    <path d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" />
  </svg>
)

export const Logo = ({ size = 18 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 20 20" fill="none" aria-hidden>
    <rect x="0.5" y="0.5" width="19" height="19" stroke="currentColor" opacity="0.35" />
    <rect x="3" y="4" width="8" height="2" fill="var(--hot)" />
    <rect x="3" y="8" width="14" height="1.5" fill="currentColor" opacity="0.28" />
    <rect x="3" y="11.5" width="11" height="1.5" fill="currentColor" opacity="0.28" />
    <rect x="3" y="15" width="6" height="1.5" fill="currentColor" opacity="0.18" />
  </svg>
)
