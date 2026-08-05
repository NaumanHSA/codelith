import type { ReactNode } from 'react'
import { Button } from './ui'

/* ------------------------------------------------------------------ *
 * Every list, panel and detail screen needs a designed empty, loading
 * and error state. These are those three, in the blueprint language.
 * ------------------------------------------------------------------ */

/** Shimmering hairline bar. Widths vary so a stack reads as content. */
export function SkeletonLine({ w = '100%', h = 11 }: { w?: string; h?: number }) {
  return <span className="skel block" style={{ width: w, height: h }} />
}

export function SkeletonPanel({ rows = 4 }: { rows?: number }) {
  const widths = ['92%', '68%', '81%', '54%', '74%', '63%']
  return (
    <div className="plate p-3" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading</span>
      <div className="mb-3 flex items-center gap-2">
        <span className="skel block size-2 rotate-45" />
        <SkeletonLine w="120px" h={9} />
      </div>
      <div className="flex flex-col gap-2">
        {Array.from({ length: rows }, (_, i) => (
          <SkeletonLine key={i} w={widths[i % widths.length]} />
        ))}
      </div>
    </div>
  )
}

export function SkeletonGrid({ count = 6 }: { count?: number }) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {Array.from({ length: count }, (_, i) => (
        <SkeletonPanel key={i} rows={3} />
      ))}
    </div>
  )
}

/** Hatched box with a rotated diamond — used wherever there is no data. */
export function EmptyState({
  title, body, action, compact = false,
}: {
  title: string
  body?: ReactNode
  action?: ReactNode
  compact?: boolean
}) {
  return (
    <div
      className={`bp-hatch flex flex-col items-center border border-rule text-center ${
        compact ? 'px-4 py-8' : 'px-6 py-14'
      }`}
    >
      <span className="mb-3 block size-4 rotate-45 border border-rule bg-panel" />
      <h3 className="text-[13px] font-bold tracking-tight text-ink">{title}</h3>
      {body && (
        <p className="mt-1.5 max-w-[46ch] font-sans text-[12px] leading-relaxed text-ink-mid">
          {body}
        </p>
      )}
      {action && <div className="mt-4 flex flex-wrap justify-center gap-2">{action}</div>}
    </div>
  )
}

/** Readable failure with a retry, never a blank screen. */
export function ErrorState({
  message, onRetry, compact = false,
}: {
  message: string
  onRetry?: () => void
  compact?: boolean
}) {
  return (
    <div
      role="alert"
      className={`flex flex-col items-start gap-2 border border-bad/35 bg-bad-wash ${
        compact ? 'px-3 py-2.5' : 'px-4 py-5'
      }`}
    >
      <span className="tag flex items-center gap-1.5 text-bad">
        <span className="block size-[6px] rotate-45 bg-bad" /> Something went wrong
      </span>
      <p className="font-sans text-[12.5px] leading-relaxed text-ink">{message}</p>
      {onRetry && (
        <Button variant="ghost" onClick={onRetry}>
          ↻ Try again
        </Button>
      )}
    </div>
  )
}

/** Inline spinner + label for in-flight actions inside a button row. */
export function Working({ label }: { label: string }) {
  return (
    <span className="tag flex items-center gap-2 text-ink-dim">
      <span className="anim-spin block size-[9px] rounded-full border border-hot border-t-transparent" />
      {label}
    </span>
  )
}
