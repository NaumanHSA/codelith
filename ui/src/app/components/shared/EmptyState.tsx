import type { ReactNode } from 'react';

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}

export function EmptyState({ icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-4 text-center">
      {icon && (
        <div className="mb-4 text-muted-foreground opacity-40">
          {icon}
        </div>
      )}
      <h3 className="text-foreground mb-1" style={{ fontSize: '1rem', fontWeight: 500 }}>{title}</h3>
      {description && (
        <p className="text-muted-foreground mb-6 max-w-sm" style={{ fontSize: '0.875rem' }}>{description}</p>
      )}
      {action}
    </div>
  );
}
