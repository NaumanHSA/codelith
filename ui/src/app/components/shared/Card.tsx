import React from 'react';

/**
 * Surface primitive used across the studio.
 *
 * Everything is driven by the theme tokens in styles/theme.css so cards stay
 * consistent — the previous pages each rolled their own border/padding/radius.
 */
export function Card({
  children,
  className = '',
  accent = false,
  onClick,
}: {
  children: React.ReactNode;
  className?: string;
  /** Draw a brand-tinted edge — use for the one card that matters on a screen. */
  accent?: boolean;
  onClick?: () => void;
}) {
  return (
    <div
      onClick={onClick}
      className={[
        'rounded-xl border bg-card transition-all',
        accent ? 'border-brand/40 shadow-lg shadow-brand/5' : 'border-border',
        onClick ? 'cursor-pointer hover:border-brand/40 hover:bg-card/80' : '',
        className,
      ].join(' ')}
    >
      {children}
    </div>
  );
}

export function CardHeader({
  title,
  subtitle,
  icon,
  actions,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  icon?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 px-5 pt-5 pb-3">
      <div className="flex items-start gap-3 min-w-0">
        {icon && (
          <div className="w-9 h-9 shrink-0 rounded-lg bg-brand/10 border border-brand/20 flex items-center justify-center text-brand">
            {icon}
          </div>
        )}
        <div className="min-w-0">
          <h3 className="text-foreground truncate" style={{ fontSize: '0.9375rem', fontWeight: 600 }}>
            {title}
          </h3>
          {subtitle && (
            <p className="text-muted-foreground mt-0.5" style={{ fontSize: '0.8125rem' }}>
              {subtitle}
            </p>
          )}
        </div>
      </div>
      {actions && <div className="shrink-0 flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function CardBody({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return <div className={`px-5 pb-5 ${className}`}>{children}</div>;
}

export function CardFooter({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-5 py-3 border-t border-border flex items-center justify-between gap-3">
      {children}
    </div>
  );
}

/** A labelled number. Used in rows to give a screen its at-a-glance summary. */
export function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
}) {
  return (
    <div className="min-w-0">
      <div
        className="text-foreground tabular-nums"
        style={{ fontSize: '1.375rem', fontWeight: 600, fontFamily: 'var(--font-mono)' }}
      >
        {value}
      </div>
      <div className="text-muted-foreground truncate" style={{ fontSize: '0.75rem' }}>
        {label}
      </div>
      {hint && (
        <div className="text-muted-foreground/70 truncate" style={{ fontSize: '0.6875rem' }}>
          {hint}
        </div>
      )}
    </div>
  );
}
