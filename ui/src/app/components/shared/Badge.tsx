import React from 'react';

export type BadgeTone = 'neutral' | 'brand' | 'success' | 'warning' | 'danger' | 'muted';

/**
 * Small status pill.
 *
 * Tones map to the dark theme's palette rather than raw Tailwind colours so badges
 * stay legible against `--card` — the previous ad-hoc `bg-gray-100 text-gray-600`
 * pills were nearly invisible in dark mode.
 */
const TONES: Record<BadgeTone, { bg: string; fg: string; ring: string }> = {
  neutral: { bg: 'rgba(255,255,255,0.06)', fg: 'var(--foreground)', ring: 'var(--border)' },
  brand: { bg: 'rgba(79,142,247,0.14)', fg: '#7aa9f8', ring: 'rgba(79,142,247,0.35)' },
  success: { bg: 'rgba(52,211,153,0.13)', fg: '#4ade80', ring: 'rgba(52,211,153,0.32)' },
  warning: { bg: 'rgba(251,191,36,0.13)', fg: '#fbbf24', ring: 'rgba(251,191,36,0.32)' },
  danger: { bg: 'rgba(239,68,68,0.13)', fg: '#f87171', ring: 'rgba(239,68,68,0.32)' },
  muted: { bg: 'rgba(255,255,255,0.04)', fg: 'var(--muted-foreground)', ring: 'var(--border)' },
};

export function Badge({
  children,
  tone = 'neutral',
  icon,
  mono = false,
  pulse = false,
}: {
  children: React.ReactNode;
  tone?: BadgeTone;
  icon?: React.ReactNode;
  mono?: boolean;
  /** Show a pulsing dot — for states that are actively changing. */
  pulse?: boolean;
}) {
  const t = TONES[tone];
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md border whitespace-nowrap"
      style={{
        background: t.bg,
        color: t.fg,
        borderColor: t.ring,
        fontSize: '0.6875rem',
        fontWeight: 500,
        fontFamily: mono ? 'var(--font-mono)' : undefined,
      }}
    >
      {pulse && (
        <span className="relative flex w-1.5 h-1.5">
          <span
            className="absolute inline-flex w-full h-full rounded-full opacity-75 animate-ping"
            style={{ background: t.fg }}
          />
          <span className="relative inline-flex w-1.5 h-1.5 rounded-full" style={{ background: t.fg }} />
        </span>
      )}
      {icon}
      {children}
    </span>
  );
}

const JOB_TONES: Record<string, BadgeTone> = {
  completed: 'success',
  ready: 'success',
  running: 'brand',
  pending: 'muted',
  awaiting_review: 'warning',
  degraded: 'warning',
  stale: 'muted',
  failed: 'danger',
  cancelled: 'muted',
};

export function StatusPill({ status }: { status: string }) {
  const tone = JOB_TONES[status] ?? 'neutral';
  return (
    <Badge tone={tone} pulse={status === 'running' || status === 'pending'}>
      {status.replace(/_/g, ' ')}
    </Badge>
  );
}
