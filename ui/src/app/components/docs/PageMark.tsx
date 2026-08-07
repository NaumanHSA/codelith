import type { PageStatus } from '../../lib/types'

/**
 * A small square whose colour says what state a page is in.
 *
 * Its own file because both the site nav and the job page show page state, and the
 * two must agree — a page that reads as "writing" in one place and "queued" in the
 * other is worse than either alone.
 */
export function PageMark({ status }: { status: PageStatus | string }) {
  const tone =
    status === 'ready'
      ? 'bg-ok'
      : status === 'generating'
        ? 'bg-hot anim-pulse'
        : status === 'stale'
          ? 'bg-warn'
          : status === 'failed'
            ? 'bg-bad'
            : status === 'orphaned'
              ? 'bg-ink-dim'
              : 'bg-rule'
  return <span className={`block size-[5px] shrink-0 rotate-45 ${tone}`} aria-hidden />
}

export default PageMark
