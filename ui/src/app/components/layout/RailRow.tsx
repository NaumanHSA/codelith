import { Link } from 'react-router-dom'

/* ------------------------------------------------------------------ *
 * One row in the rail, and one secondary action under a section.
 *
 * Four sections list codebases in the same shape. Three of them had
 * grown their own copy of the markup and had already drifted apart on
 * marker size and hover colour, so the shape lives here now.
 * ------------------------------------------------------------------ */

export function RailRow({
  to,
  active,
  label,
  sub,
  title,
}: {
  to: string
  active: boolean
  label: string
  /** Second line. Say something true about this row, or omit it. */
  sub?: string
  title?: string
}) {
  return (
    <Link
      to={to}
      title={title ?? label}
      className={`group relative flex items-center gap-2 py-[6px] pr-2 pl-4 transition-colors ${
        active ? 'bg-hot-wash' : 'hover:bg-sunk'
      }`}
    >
      {active && <span className="absolute top-0 left-0 h-full w-[3px] bg-hot" />}
      <span
        className={`block size-[5px] shrink-0 rotate-45 ${
          active ? 'bg-hot' : 'bg-rule group-hover:bg-hot'
        }`}
      />
      <span className="min-w-0 flex-1">
        <span
          className={`block truncate text-[12px] ${
            active ? 'font-semibold text-hot-ink' : 'text-ink-mid group-hover:text-ink'
          }`}
        >
          {label}
        </span>
        {sub && <span className="block truncate text-[10px] text-ink-dim">{sub}</span>}
      </span>
    </Link>
  )
}

/** A section's secondary action — "View all", "Published documents". */
export function RailAction({
  to,
  children,
  active = false,
}: {
  to: string
  children: React.ReactNode
  active?: boolean
}) {
  return (
    <Link
      to={to}
      className={`group flex items-center gap-2 py-[6px] pr-2 pl-4 text-[11.5px] transition-colors ${
        active
          ? 'font-semibold text-hot-ink'
          : 'text-ink-dim hover:bg-sunk hover:text-ink'
      }`}
    >
      {children}
    </Link>
  )
}

/** What a section says when it has nothing to list. */
export function RailNote({ children }: { children: React.ReactNode }) {
  return (
    <p className="px-4 py-1 text-[10.5px] leading-snug text-ink-dim">{children}</p>
  )
}
