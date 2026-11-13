import type { CSSProperties, ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { BrandMark, languageBrand, type BrandName } from '../lib/brands'
import { primaryLanguage } from '../lib/format'
import type { Project } from '../lib/types'
import { Icon, type IconName } from '../lib/icons'
import { useCountUp } from '../lib/motion'

/* ------------------------------------------------------------------ *
 * The v3 building blocks, shared by every rebuilt page.
 *
 * The prototype's rule: icons, tiles, pills, tables and lists carry the
 * page; a bordered rectangle frames only what you read or operate. So
 * there is no card here. `Panel` in ui.tsx is the one framed surface.
 *
 * Colours passed in (a kind's, a brand's) are data from lib/kinds.ts and
 * lib/brands.ts, handed to CSS as `--c`; nothing here writes a hex.
 * ------------------------------------------------------------------ */

type WithC = CSSProperties & { '--c'?: string }

/**
 * An icon or a logo in a rounded square. `tint` washes the tile in the colour,
 * for a kind; without it the tile is neutral and only the glyph is coloured,
 * which is what a brand logo wants.
 */
export function IconTile({
  icon,
  brand,
  color,
  size = 32,
  tint = false,
  label,
}: {
  icon?: IconName
  brand?: BrandName
  color?: string
  size?: number
  tint?: boolean
  /** Names the tile for assistive tech when nothing beside it does. */
  label?: string
}) {
  const glyph = Math.round(size * 0.5)
  const style: WithC = { width: size, height: size, borderRadius: size * 0.26 }
  if (color) style['--c'] = color
  return (
    <span
      style={style}
      role={label ? 'img' : undefined}
      aria-label={label}
      className={`grid shrink-0 place-items-center ${
        tint && color
          ? 'bg-[color-mix(in_srgb,var(--c)_12%,var(--panel))] shadow-[inset_0_0_0_1px_color-mix(in_srgb,var(--c)_32%,transparent)]'
          : 'bg-sunk shadow-[inset_0_0_0_1px_var(--line-2)]'
      }`}
    >
      {brand ? (
        <BrandMark name={brand} size={glyph} decorative={!!label} />
      ) : icon ? (
        <Icon
          name={icon}
          size={glyph}
          className={color ? 'text-[var(--c)]' : 'text-ink-mid'}
        />
      ) : null}
    </span>
  )
}

const PILL_TONE = {
  plain: 'text-ink-mid border-line-2',
  hot: 'text-hot-ink border-hot-edge',
  good: 'text-ok border-ok/35',
  warn: 'text-warn border-warn/35',
  bad: 'text-bad border-bad/35',
} as const

/** A short fact in a rounded outline: a count, a state, a language. */
export function Pill({
  children,
  tone = 'plain',
  icon,
  title,
}: {
  children: ReactNode
  tone?: keyof typeof PILL_TONE
  icon?: IconName
  title?: string
}) {
  return (
    <span
      title={title}
      className={`inline-flex h-6 shrink-0 items-center gap-1.5 rounded-full border px-2.5 text-[12px] font-medium whitespace-nowrap ${PILL_TONE[tone]}`}
    >
      {icon && <Icon name={icon} size={13} />}
      {children}
    </span>
  )
}

/**
 * One row of a list: what it is, what it is called, a line about it, and
 * anything at the far end. A link when `to` is given, a button with `onClick`,
 * and plain otherwise.
 */
export function ListRow({
  lead,
  title,
  sub,
  trail,
  to,
  onClick,
  active = false,
  style,
  className = '',
}: {
  lead?: ReactNode
  title: ReactNode
  sub?: ReactNode
  trail?: ReactNode
  to?: string
  onClick?: () => void
  active?: boolean
  style?: CSSProperties
  className?: string
}) {
  const cls = `flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors ${
    active ? 'bg-sunk shadow-[inset_0_0_0_1px_var(--rule)]' : to || onClick ? 'hover:bg-hover' : ''
  } ${className}`
  const body = (
    <>
      {lead}
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[14px] font-medium text-ink">{title}</span>
        {sub && <span className="block truncate text-[12.5px] text-ink-dim">{sub}</span>}
      </span>
      {trail}
    </>
  )
  if (to)
    return (
      <Link to={to} className={cls} style={style}>
        {body}
      </Link>
    )
  if (onClick)
    return (
      <button type="button" onClick={onClick} className={cls} style={style}>
        {body}
      </button>
    )
  return (
    <div className={cls} style={style}>
      {body}
    </div>
  )
}

/** A number that counts up when it arrives. Screen readers get the real value
 *  once, never the frames in between. */
export function CountUp({
  value,
  format = n => Math.round(n).toLocaleString(),
}: {
  value: number
  format?: (n: number) => string
}) {
  const shown = useCountUp(value)
  return (
    <>
      <span aria-hidden>{format(shown)}</span>
      <span className="sr-only">{format(value)}</span>
    </>
  )
}

/** A headline figure with its label, and optionally the icon of what it counts.
 *  Numbers count up; text values are shown as they are. */
export function StatBlock({
  value,
  label,
  icon,
  color,
}: {
  value: number | string
  label: ReactNode
  icon?: IconName
  color?: string
}) {
  return (
    <div className="flex items-center gap-3 px-1 py-4">
      {icon && <IconTile icon={icon} color={color} tint={!!color} size={36} />}
      <div className="min-w-0">
        <b className="font-head block text-[22px] leading-tight font-semibold tracking-[-0.02em] text-ink tabular-nums">
          {typeof value === 'number' ? <CountUp value={value} /> : value}
        </b>
        <span className="block text-[12.5px] text-ink-mid">{label}</span>
      </div>
    </div>
  )
}

/** A codebase's mark: its main language's logo, or a folder before it has been
 *  probed or when the language has no logo. */
export function CodebaseMark({ project, size = 15 }: { project: Pick<Project, 'sources'>; size?: number }) {
  const brand = languageBrand(primaryLanguage(project))
  return brand ? (
    <BrandMark name={brand} size={size} />
  ) : (
    <Icon name="folder" size={size} className="text-ink-dim" />
  )
}
