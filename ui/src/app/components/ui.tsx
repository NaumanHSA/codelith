import {
  useEffect, useId, useRef, type ReactNode,
} from 'react'
import { Icon } from '../lib/icons'
import { useFill } from '../lib/motion'

/* ------------------------------------------------------------------ *
 * Shared primitives, in the v3 language: rounded controls, sentence-case
 * labels in Inter, mono kept for micro labels and data. They used to be
 * brutalist (hard hairlines, zero radius, uppercase mono everywhere),
 * which is what made the studio read as a terminal.
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

/** A state as a pill: its word, in its signal colour, led by a dot, or by a
 *  spinner while it is still running. */
export function StatusBadge({ status, size = 'sm' }: { status: string; size?: 'sm' | 'md' }) {
  const c = SIGNAL[status] ?? SIGNAL.pending
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border font-medium whitespace-nowrap ${c.bg} ${c.bd} ${c.fg} ${
        size === 'md' ? 'h-7 px-3 text-[12.5px]' : 'h-[22px] px-2 text-[11.5px]'
      }`}
    >
      {status === 'running' ? (
        <span className="anim-spin block size-[9px] rounded-full border-[1.5px] border-current border-t-transparent" />
      ) : (
        <span className="block size-[6px] rounded-full bg-current" />
      )}
      {status.replace(/_/g, ' ')}
    </span>
  )
}

/** A small mono label over a section, with anything that acts on it at the
 *  far end. It used to draw a rule across the row, a blueprint habit. */
export function Eyebrow({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex items-center gap-3">
      <span className="tag shrink-0 text-ink-dim">{children}</span>
      <span className="flex-1" />
      {right}
    </div>
  )
}

/** A rounded panel with an optional header row. `index` is accepted and no
 *  longer drawn: the numbered sections belonged to the blueprint theme. */
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
        <header
          data-index={index}
          className="flex items-center gap-2.5 rounded-t-[10px] border-b border-rule px-4 py-3"
        >
          <h2 className="text-[14px] font-semibold text-ink">{title}</h2>
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
    <div className="flex items-baseline justify-between gap-3 border-b border-rule px-4 py-2 last:border-b-0">
      <span className="text-[12.5px] text-ink-mid">{k}</span>
      <span className={`text-[13px] font-medium tabular-nums ${hot ? 'text-hot-ink' : 'text-ink'}`}>{v}</span>
    </div>
  )
}

/** A filled bar to pct. `segments` sets its width (five pixels each) so the
 *  callers written for the old segmented meter keep their layout. */
export function Meter({ pct, segments = 20 }: { pct: number; segments?: number }) {
  const shown = useFill(Math.max(0, Math.min(100, pct)))
  return (
    <span
      className="inline-block h-1.5 overflow-hidden rounded-full bg-rule align-middle"
      style={{ width: segments * 5 }}
      aria-hidden
    >
      <span
        className="block h-full rounded-full bg-hot transition-[width] duration-[420ms] ease-[cubic-bezier(0.2,0,0,1)]"
        style={{ width: `${shown}%` }}
      />
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
    'inline-flex items-center gap-1.5 rounded-md border px-2 py-[3px] text-[12px] font-medium transition-colors duration-150 whitespace-nowrap'
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
      className={`${base} ${tones} cursor-pointer hover:border-line-2 hover:text-ink`}
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
    hot: 'bg-hot text-on-hot border-hot hover:bg-hot-ink hover:border-hot-ink',
    solid: 'bg-ink text-on-ink border-ink hover:bg-ink-mid hover:border-ink-mid',
    ghost: 'bg-sunk text-ink border-line-2 hover:bg-hover',
    danger: 'bg-bad-wash text-bad border-bad/40 hover:border-bad hover:bg-bad hover:text-on-hot',
  }[variant]
  return (
    <button
      type={type}
      title={title}
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center justify-center gap-2 rounded-lg border px-3.5 py-[7px] text-[13px] font-medium whitespace-nowrap transition-[background-color,border-color,color,transform] duration-150 active:translate-y-px disabled:cursor-not-allowed disabled:border-rule disabled:bg-sunk disabled:text-ink-dim disabled:active:translate-y-0 ${v} ${className}`}
    >
      {children}
    </button>
  )
}

/** Page header: title, a line under it, and the page's actions. `index` is
 *  accepted and no longer drawn: the shell's breadcrumbs say where you are. */
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
          className="mb-2 flex items-center gap-1.5 text-[12.5px] text-ink-dim transition-colors hover:text-ink"
        >
          <Icon name="arrow-left" size={14} /> {back.label}
        </button>
      )}
      <div data-index={index} className="flex flex-wrap items-end gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-[22px] leading-tight font-semibold text-ink">{title}</h1>
          {sub && <div className="mt-1 text-[13px] text-ink-mid">{sub}</div>}
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
  'w-full rounded-lg border border-line-2 bg-sunk px-3 py-[7px] text-[13px] text-ink transition-[border-color,box-shadow] placeholder:text-ink-dim focus:border-hot focus:shadow-[0_0_0_3px_var(--hot-wash)] focus:outline-none disabled:opacity-60'

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
      <span className="mb-1.5 block text-[12.5px] font-medium text-ink-mid">{label}</span>
      {children}
      {error ? (
        <span className="mt-1.5 block text-[12px] leading-snug text-bad">{error}</span>
      ) : help ? (
        <span className="mt-1.5 block text-[12px] leading-snug text-ink-dim">{help}</span>
      ) : null}
    </label>
  )
}

/* ------------------------------------------------------------------ *
 * Dialog — focus trapped, Escape closes, scroll locked.
 * ------------------------------------------------------------------ */

export function Dialog({
  open, onClose, title, children, width = 520, bodyClass = 'px-4 py-3.5',
}: {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  width?: number
  /** Override when the content pads itself, or needs to reach the edges. */
  bodyClass?: string
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
    // Centred, and still scrollable when the content is taller than the window.
    // `items-center` directly on a scroll container clips the top of anything too
    // tall to fit; the inner `min-h-full` wrapper is what makes both true at once.
    // It used to be `items-start`, which pinned every dialog under the top edge.
    <div className="fixed inset-0 z-100 overflow-y-auto p-4 sm:p-8">
      <div
        className="fixed inset-0 bg-paper/75 backdrop-blur-[3px]"
        onClick={onClose}
        aria-hidden
      />
      <div className="relative flex min-h-full items-center justify-center">
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        style={{ maxWidth: width }}
        className="anim-rise relative w-full rounded-xl border border-line-2 bg-panel shadow-[0_28px_70px_-16px_var(--shadow)]"
      >
        <header className="flex items-center gap-2.5 border-b border-rule px-4 py-3">
          <h2 id={titleId} className="text-[15px] font-semibold text-ink">
            {title}
          </h2>
          <button
            onClick={onClose}
            aria-label="Close dialog"
            title="Close (Esc)"
            className="ml-auto flex size-7 items-center justify-center rounded-md text-ink-dim transition-colors hover:bg-hover hover:text-ink"
          >
            <Icon name="x" size={16} />
          </button>
        </header>
        {/* Padded here rather than by every caller. Two of the three were doing it
            already and the third was not, which is how one dialog shipped with its
            text against the border. */}
        <div className={bodyClass}>{children}</div>
      </div>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ *
 * Marks
 * ------------------------------------------------------------------ */

/**
 * The Codelith mark — a monolith with a `</>` cut into it.
 *
 * Inlined from `docs/assets/codelith-logo.svg` rather than loaded as a file:
 * the product's claim is that nothing leaves the machine, and an inline mark
 * cannot 404, cannot flash, and costs no request. The two fills are bound to
 * theme tokens instead of the source file's hex, so the mark follows the theme
 * when a dark variant lands.
 */
export const Logo = ({ size = 18 }: { size?: number }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 150 150"
    fill="none"
    aria-hidden
    className="shrink-0"
  >
    {/* The slab, and the thinner leaf standing behind it. */}
    <path
      fill="var(--hot)"
      d="m52.6 142.8c-1.4-0.6-12.6-4.8-20.2-7.4-2.8-1.1-5.2-4.3-5.2-8.4v-92.6c0-5.5 3.6-10.5 8.1-11.7l58.7-15.3c1.4-0.4 3.4-0.4 4.8-0.1l14.4 4.6 0.3 0.1-56.4 16.2c-5.3 1.4-10 6.7-10 13.5v93.1c0 4.5 2 7.2 5.5 8z"
    />
    <path
      fill="var(--hot)"
      d="m114.6 124.3-56.4 16.1c-4.2 1-8-1.5-8-6v-92.4c0-5 3.7-9.7 8-11.1l56.4-15.9c4.6-1.4 8 1.3 8 6.1v91.9c0.1 5.4-3.4 10.2-8 11.3z"
    />
    {/* `</>` knocked out of the slab, so it reads as cut rather than drawn. */}
    <path
      fill="var(--paper)"
      d="m74.8 62.3-14.4 17.4c-0.7 0.9-1.1 1.8-1 2.8s0.3 1.8 1.1 2.3l14.5 10.4v-8.1l-8.7-6.3 8.6-10.3v-8.2h-0.1z"
    />
    <polygon fill="var(--paper)" points="77.9 97 83.6 95.4 93.1 54.2 87.1 55.9" />
    <path
      fill="var(--paper)"
      d="m111 66.6-14.9-10.3v8.4l8.7 6.3-8.7 10.2v8.2l15-17.4c1.7-1.8 1.8-4.4-0.1-5.4z"
    />
  </svg>
)
