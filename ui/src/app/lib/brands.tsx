import {
  siAnthropic,
  siBitbucket,
  siDjango,
  siDocker,
  siFastapi,
  siFlask,
  siGithub,
  siGitlab,
  siGo,
  siGooglegemini,
  siHuggingface,
  siJavascript,
  siLangchain,
  siLmstudio,
  siMongodb,
  siMysql,
  siNodedotjs,
  siOllama,
  siOpenjdk,
  siPostgresql,
  siPydantic,
  siPython,
  siReact,
  siRedis,
  siRust,
  siSqlite,
  siTypescript,
  siVite,
  type SimpleIcon,
} from 'simple-icons'
import { Icon, type IconName } from './icons'

/* ------------------------------------------------------------------ *
 * Brand logos: languages, frameworks, datastores, hosts and providers.
 *
 * simple-icons (CC0) for the marks. Two rules learned in the prototype:
 *
 * - A brand colour below 3:1 against the panel is drawn in ink instead.
 *   GitHub, Anthropic, SQLite, Django, OpenJDK and Rust are near-black
 *   and would vanish on the dark ground.
 * - A mark that is a wordmark is unreadable at 16px, and a brand
 *   simple-icons does not carry cannot be drawn at all. Both get a Lucide
 *   glyph in the brand's colour: SQLAlchemy is a database, and OpenAI, which
 *   simple-icons 16 no longer carries, is a sparkle.
 *
 * The colours here are data, the one place a hex value is allowed outside
 * theme.css, because they belong to the brands rather than to the studio.
 * ------------------------------------------------------------------ */

export interface Brand {
  title: string
  /** A CSS colour, already checked for contrast on the dark ground. */
  color: string
  /** The simple-icons path, drawn in a 24-unit box. */
  path?: string
  /** A Lucide glyph instead, when there is no usable mark. */
  icon?: IconName
}

/** --panel, the darkest surface a logo sits on. */
const GROUND = [0x12, 0x12, 0x15]

function luminance([r, g, b]: number[]): number {
  const lin = (c: number) => {
    const s = c / 255
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
}

/** The brand's own colour if it reads on the ground at 3:1, otherwise ink. */
function readable(hex: string): string {
  const rgb = [0, 2, 4].map(i => parseInt(hex.slice(i, i + 2), 16))
  const ratio = (luminance(rgb) + 0.05) / (luminance(GROUND) + 0.05)
  return ratio >= 3 ? `#${hex}` : 'var(--ink)'
}

const mark = (si: SimpleIcon): Brand => ({
  title: si.title,
  color: readable(si.hex),
  path: si.path,
})

const glyph = (title: string, icon: IconName, hex: string): Brand => ({
  title,
  icon,
  color: readable(hex),
})

export const BRANDS = {
  // languages — one per provider in codelith/languages/providers
  python: mark(siPython),
  typescript: mark(siTypescript),
  javascript: mark(siJavascript),
  go: mark(siGo),
  java: mark(siOpenjdk),
  rust: mark(siRust),
  nodejs: mark(siNodedotjs),

  // frameworks and libraries
  fastapi: mark(siFastapi),
  django: mark(siDjango),
  flask: mark(siFlask),
  pydantic: mark(siPydantic),
  sqlalchemy: glyph('SQLAlchemy', 'database', 'D71F00'),
  langchain: mark(siLangchain),
  react: mark(siReact),
  vite: mark(siVite),

  // datastores
  sqlite: mark(siSqlite),
  postgresql: mark(siPostgresql),
  mysql: mark(siMysql),
  mongodb: mark(siMongodb),
  redis: mark(siRedis),
  docker: mark(siDocker),

  // where code comes from
  github: mark(siGithub),
  gitlab: mark(siGitlab),
  bitbucket: mark(siBitbucket),

  // model providers
  openai: glyph('OpenAI', 'sparkles', 'ECECEE'),
  anthropic: mark(siAnthropic),
  gemini: mark(siGooglegemini),
  ollama: mark(siOllama),
  lmstudio: mark(siLmstudio),
  huggingface: mark(siHuggingface),
} satisfies Record<string, Brand>

export type BrandName = keyof typeof BRANDS

/** The language names the probe and the knowledge base report, mapped to a logo. */
const LANGUAGE_BRAND: Record<string, BrandName> = {
  python: 'python',
  typescript: 'typescript',
  javascript: 'javascript',
  go: 'go',
  java: 'java',
  rust: 'rust',
}

export function languageBrand(language: string | null | undefined): BrandName | null {
  return (language && LANGUAGE_BRAND[language.toLowerCase()]) || null
}

/** Where a source lives. `local` has no brand; it is a folder. */
export function sourceBrand(sourceType: string | null | undefined): BrandName | null {
  return sourceType === 'github' || sourceType === 'gitlab' || sourceType === 'bitbucket'
    ? sourceType
    : null
}

/**
 * A brand's mark at icon size. Labelled with the brand's name, because unlike an
 * interface icon a logo is often the only thing saying which language it is.
 */
export function BrandMark({
  name,
  size = 16,
  className = '',
  decorative = false,
}: {
  name: BrandName
  size?: number
  className?: string
  /** True when the name is already written beside the mark. */
  decorative?: boolean
}) {
  const brand: Brand = BRANDS[name]
  const label = decorative ? undefined : brand.title
  if (brand.icon) {
    return (
      <Icon
        name={brand.icon}
        size={size}
        className={className}
        style={{ color: brand.color }}
        aria-label={label}
      />
    )
  }
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill={brand.color}
      className={`shrink-0 ${className}`}
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      {label && <title>{label}</title>}
      <path d={brand.path} />
    </svg>
  )
}
