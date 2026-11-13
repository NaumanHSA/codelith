import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

/* ------------------------------------------------------------------ *
 * One row in the rail, and one secondary action under a section.
 *
 * Four sections list codebases in the same shape. Three of them had
 * grown their own copy of the markup and had already drifted apart on
 * marker size and hover colour, so the shape lives here now.
 *
 * A row leads with what it is — a language logo for a codebase, a book
 * for its documentation — rather than the bare diamond it used to share
 * with every other row.
 * ------------------------------------------------------------------ */

export const railRowClass = (active: boolean) =>
  `group flex items-center gap-2.5 rounded-[7px] px-2.5 py-[6px] transition-colors ${
    active ? 'bg-sunk text-ink shadow-[inset_0_0_0_1px_var(--rule)]' : 'text-ink-mid hover:bg-hover hover:text-ink'
  }`

export function RailRow({
  to,
  active,
  label,
  sub,
  title,
  lead,
  trail,
}: {
  to: string
  active: boolean
  label: string
  /** Second line. Say something true about this row, or omit it. */
  sub?: string
  title?: string
  /** An icon or logo for what the row is. */
  lead?: ReactNode
  /** A status mark at the far end. */
  trail?: ReactNode
}) {
  return (
    <Link to={to} title={title ?? label} className={railRowClass(active)}>
      {lead && <span className="flex size-4 shrink-0 items-center justify-center">{lead}</span>}
      <span className="min-w-0 flex-1">
        <span className={`block truncate text-[13px] ${active ? 'font-medium' : ''}`}>{label}</span>
        {sub && <span className="block truncate text-[11px] text-ink-dim">{sub}</span>}
      </span>
      {trail}
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
  children: ReactNode
  active?: boolean
}) {
  return (
    <Link
      to={to}
      className={`group flex items-center gap-2.5 rounded-[7px] px-2.5 py-[6px] text-[12.5px] transition-colors ${
        active ? 'bg-sunk text-ink' : 'text-ink-dim hover:bg-hover hover:text-ink'
      }`}
    >
      {children}
    </Link>
  )
}

/** What a section says when it has nothing to list. */
export function RailNote({ children }: { children: ReactNode }) {
  return <p className="px-2.5 py-1 text-[12px] leading-snug text-ink-dim">{children}</p>
}
