/**
 * Display helpers.
 *
 * Durations especially: the backend now records `started_at`/`completed_at` on every
 * job step, so "time taken" is real data rather than something the UI has to guess.
 */

/** `12.4s`, `3m 05s`, `1h 12m`. Sub-10s keeps a decimal; longer rounds. */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) return '—';
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
  if (seconds < 10) return `${seconds.toFixed(1)}s`;
  if (seconds < 60) return `${Math.round(seconds)}s`;

  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  if (mins < 60) return `${mins}m ${String(secs).padStart(2, '0')}s`;

  const hours = Math.floor(mins / 60);
  return `${hours}h ${String(mins % 60).padStart(2, '0')}m`;
}

/** Elapsed time between two timestamps, or from `start` to now while running. */
export function elapsedSeconds(start?: string | null, end?: string | null): number | null {
  if (!start) return null;
  const from = new Date(start).getTime();
  const to = end ? new Date(end).getTime() : Date.now();
  if (Number.isNaN(from) || Number.isNaN(to)) return null;
  return Math.max(0, (to - from) / 1000);
}

export function formatCount(n: number | null | undefined): string {
  if (n == null) return '—';
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

/** Words that should stay upper-case rather than being title-cased to "Api". */
const ACRONYMS = new Set([
  'api', 'ui', 'cli', 'db', 'http', 'url', 'id', 'sql', 'qa', 'llm', 'kb', 'sdk', 'io',
]);

/** `architecture` → `Architecture`, `getting_started` → `Getting Started`, `api` → `API`. */
export function humanize(value: string): string {
  return value
    .split(/[_\-\s]+/)
    .filter(Boolean)
    .map(w => (ACRONYMS.has(w.toLowerCase()) ? w.toUpperCase() : w[0].toUpperCase() + w.slice(1)))
    .join(' ');
}

export function formatBytes(bytes: number | null | undefined): string {
  if (!bytes) return '—';
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}
