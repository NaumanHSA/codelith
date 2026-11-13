import type { IconName } from './icons'
import type { BrandName } from './brands'

/* ------------------------------------------------------------------ *
 * What every kind of file looks like, on every screen.
 *
 * The atlas draws each node as its kind's icon in its kind's colour, and
 * the risk list, the codebase page and the assistant's citations use the
 * same pair, so a config file is a lime gear wherever it appears.
 *
 * The kinds are the server's (`FILE_KINDS` in codelith/knowledge/atlas.py):
 * read from the facts analysis stored, the module's role, and only then
 * the file's name.
 *
 * The colours are data, like the brand colours. Checked 2026-11-12: every
 * one is at least 6:1 on the panel, and the closest pair for normal vision
 * is 21.7 delta-E apart (env and outside service were lightened for it).
 * Under simulated protanopia and deuteranopia several still converge
 * (service, store, API): thirteen hues cannot all survive that, which is
 * why every node is drawn as its own icon and labelled, never as a dot.
 * ------------------------------------------------------------------ */

export interface Kind {
  label: string
  /** Plural, for a legend or a count: "4 datastores". */
  plural: string
  color: string
  icon: IconName
}

export const KINDS = {
  service: { label: 'Service', plural: 'Services', color: '#a78bfa', icon: 'layers' },
  api: { label: 'API route', plural: 'API routes', color: '#60a5fa', icon: 'route' },
  data: { label: 'Data access', plural: 'Data access', color: '#f472b6', icon: 'database' },
  store: { label: 'Datastore', plural: 'Datastores', color: '#e879f9', icon: 'hard-drive' },
  model: { label: 'Model or schema', plural: 'Models and schemas', color: '#fbbf24', icon: 'braces' },
  config: { label: 'Config', plural: 'Config', color: '#a3e635', icon: 'settings' },
  env: { label: 'Env file', plural: 'Env files', color: '#fde68a', icon: 'key-round' },
  test: { label: 'Test', plural: 'Tests', color: '#2dd4bf', icon: 'flask-conical' },
  cli: { label: 'Command line', plural: 'Command line', color: '#fb923c', icon: 'square-terminal' },
  entry: { label: 'Entry point', plural: 'Entry points', color: '#f4f4f5', icon: 'play' },
  util: { label: 'Utility', plural: 'Utilities', color: '#94a3b8', icon: 'wrench' },
  ui: { label: 'Screen', plural: 'Screens', color: '#fda4af', icon: 'app-window' },
  external: { label: 'Outside service', plural: 'Outside services', color: '#c7d2fe', icon: 'globe' },
  // Project files: what it takes to install, configure and run the code.
  manifest: { label: 'Manifest', plural: 'Manifests', color: '#86efac', icon: 'package' },
  lockfile: { label: 'Lockfile', plural: 'Lockfiles', color: '#a8a29e', icon: 'lock' },
  deploy: { label: 'Deployment file', plural: 'Deployment', color: '#22d3ee', icon: 'container' },
  ci: { label: 'CI workflow', plural: 'CI', color: '#7dd3fc', icon: 'workflow' },
  tooling: { label: 'Tool settings', plural: 'Tooling', color: '#cbd5e1', icon: 'file-cog' },
  docs: { label: 'Guide', plural: 'Guides', color: '#f5d0fe', icon: 'book-open' },
} as const satisfies Record<string, Kind>

export type KindName = keyof typeof KINDS

/** What a file declares, at the atlas's closest zoom and in its outline. */
const SYMBOL_TABLE = {
  class: { label: 'Class', plural: 'Classes', color: '#fbbf24', icon: 'box' },
  interface: { label: 'Interface', plural: 'Interfaces', color: '#fbbf24', icon: 'braces' },
  type: { label: 'Type', plural: 'Types', color: '#fbbf24', icon: 'braces' },
  function: { label: 'Function', plural: 'Functions', color: '#60a5fa', icon: 'square-function' },
  method: { label: 'Method', plural: 'Methods', color: '#a78bfa', icon: 'square-function' },
  constructor: { label: 'Constructor', plural: 'Constructors', color: '#a78bfa', icon: 'square-function' },
  property: { label: 'Property', plural: 'Properties', color: '#94a3b8', icon: 'braces' },
} as const satisfies Record<string, Kind>

// Widened on purpose: looked up by whatever kind the graph stored. (A `constructor`
// key also loses its literal types under a plain Record annotation, because
// Object's own `constructor` member wins the contextual type.)
export const SYMBOL_KINDS: Record<string, Kind> = SYMBOL_TABLE

export function symbolKindOf(kind: string | null | undefined): Kind {
  return (kind && SYMBOL_KINDS[kind]) || SYMBOL_KINDS.function
}

/** An unknown kind draws as a utility rather than failing: the API may learn a
 *  kind before the studio does. */
export function kindOf(name: string | null | undefined): Kind {
  return (name && (KINDS as Record<string, Kind>)[name]) || KINDS.util
}

/* ------------------------------------------------------------------ *
 * Facts that are not files: what the code talks to. A recognised name gets
 * its brand's logo, a few generic ones a better glyph than the kind's, and
 * the rest the kind's own icon.
 * ------------------------------------------------------------------ */

const FACT_BRANDS: [RegExp, BrandName][] = [
  [/openai/i, 'openai'],
  [/anthropic|claude/i, 'anthropic'],
  [/gemini|generativelanguage|googleapis/i, 'gemini'],
  [/github/i, 'github'],
  [/gitlab/i, 'gitlab'],
  [/bitbucket/i, 'bitbucket'],
  [/sqlite/i, 'sqlite'],
  [/postgres/i, 'postgresql'],
  [/mysql/i, 'mysql'],
  [/mongo/i, 'mongodb'],
  [/redis/i, 'redis'],
  [/ollama/i, 'ollama'],
  [/huggingface|hugging face/i, 'huggingface'],
  [/docker/i, 'docker'],
  [/lm ?studio/i, 'lmstudio'],
  [/fastapi/i, 'fastapi'],
  [/django/i, 'django'],
  [/flask/i, 'flask'],
  [/pydantic/i, 'pydantic'],
  [/langchain/i, 'langchain'],
  [/^react|react\.js/i, 'react'],
  [/^vite/i, 'vite'],
  [/node\.?js/i, 'nodejs'],
  [/sqlalchemy/i, 'sqlalchemy'],
]

/** A recognised brand for a name: a framework, a datastore, a host, a provider. */
export function brandFor(name: string): BrandName | null {
  for (const [re, brand] of FACT_BRANDS) if (re.test(name)) return brand
  return null
}

const FACT_ICONS: [RegExp, IconName][] = [
  [/modelcontextprotocol|\bmcp\b/i, 'plug'],
  [/smithery/i, 'boxes'],
  [/serp|search/i, 'search'],
  [/chroma|qdrant|vector|pinecone|weaviate|sqlalchemy|db-api|\bsql\b/i, 'database'],
  [/\.env/i, 'key-round'],
  [/pyproject|package\.json|cargo\.toml|go\.mod|pom\.xml|requirements/i, 'package'],
]

/** How a node is drawn: a brand's logo, or an icon in its kind's colour. */
export type Look = { brand: BrandName; icon?: undefined } | { icon: IconName; brand?: undefined }

export function lookOf(node: { kind: string; fact: string | null; path: string }): Look {
  if (node.fact) {
    for (const [re, brand] of FACT_BRANDS) if (re.test(node.path)) return { brand }
    for (const [re, icon] of FACT_ICONS) if (re.test(node.path)) return { icon }
  }
  return { icon: kindOf(node.kind).icon }
}

/* ------------------------------------------------------------------ *
 * The facts analysis extracts (`EntityKind` on the server), and the
 * narrative topics it writes about. Same rule: one icon and one colour
 * each, here and nowhere else.
 * ------------------------------------------------------------------ */

const FACT_TABLE = {
  route: { label: 'Route', plural: 'Routes', color: '#60a5fa', icon: 'route' },
  entrypoint: { label: 'Entry point', plural: 'Entry points', color: '#f4f4f5', icon: 'play' },
  service: { label: 'Service', plural: 'Services', color: '#a78bfa', icon: 'layers' },
  dependency: { label: 'Dependency', plural: 'Dependencies', color: '#94a3b8', icon: 'package' },
  env_var: { label: 'Env var', plural: 'Env vars', color: '#fde68a', icon: 'key-round' },
  config_file: { label: 'Config file', plural: 'Config files', color: '#a3e635', icon: 'settings' },
  datastore: { label: 'Datastore', plural: 'Datastores', color: '#e879f9', icon: 'hard-drive' },
  external_api: { label: 'Outside service', plural: 'Outside services', color: '#c7d2fe', icon: 'globe' },
  cli_command: { label: 'Command', plural: 'Commands', color: '#fb923c', icon: 'square-terminal' },
  scheduled_task: { label: 'Scheduled task', plural: 'Scheduled tasks', color: '#2dd4bf', icon: 'timer' },
  event: { label: 'Event', plural: 'Events', color: '#f472b6', icon: 'zap' },
  infra_resource: { label: 'Infrastructure', plural: 'Infrastructure', color: '#a3e635', icon: 'container' },
  test_suite: { label: 'Test suite', plural: 'Test suites', color: '#2dd4bf', icon: 'flask-conical' },
} as const satisfies Record<string, Kind>

export const FACT_KINDS: Record<string, Kind> = FACT_TABLE

export function factKindOf(kind: string): Kind {
  return FACT_KINDS[kind] ?? { label: kind, plural: kind, color: '#94a3b8', icon: 'hash' }
}

export const TOPIC_ICONS: Record<string, IconName> = {
  overview: 'telescope',
  architecture: 'layers',
  request_lifecycle: 'route',
  data_model: 'database',
  configuration: 'settings',
  testing: 'flask-conical',
  cli_usage: 'square-terminal',
  state_management: 'hard-drive',
  error_handling: 'triangle-alert',
  observability: 'activity',
  deployment: 'rocket',
  integrations: 'plug',
  security: 'shield',
  extension_points: 'git-fork',
}

/** The four ways into a codebase, as they appear on every page that offers them. */
export const APP_LOOKS = {
  graph: { label: 'Knowledge graph', icon: 'waypoints', color: 'var(--hot)' },
  assistant: { label: 'Ask the code', icon: 'message-square', color: '#2dd4bf' },
  changes: { label: 'Changes', icon: 'git-compare-arrows', color: '#f472b6' },
  documentation: { label: 'Documentation', icon: 'book-open', color: '#a78bfa' },
  qa: { label: 'QA', icon: 'shield-check', color: '#60a5fa' },
} as const satisfies Record<string, { label: string; icon: IconName; color: string }>
