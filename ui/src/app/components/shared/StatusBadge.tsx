import type { JobStatus, DocStatus, StepStatus } from '../../lib/types';

type AnyStatus = JobStatus | DocStatus | StepStatus;

const statusConfig: Record<string, { label: string; className: string; dotClass: string }> = {
  pending: {
    label: 'Pending',
    className: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
    dotClass: 'bg-gray-400',
  },
  running: {
    label: 'Running',
    className: 'bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300',
    dotClass: 'bg-blue-500 animate-pulse',
  },
  awaiting_review: {
    label: 'Review',
    className: 'bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300',
    dotClass: 'bg-amber-500',
  },
  completed: {
    label: 'Completed',
    className: 'bg-green-50 text-green-700 dark:bg-green-950 dark:text-green-300',
    dotClass: 'bg-green-500',
  },
  failed: {
    label: 'Failed',
    className: 'bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300',
    dotClass: 'bg-red-500',
  },
  cancelled: {
    label: 'Cancelled',
    className: 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-500 line-through',
    dotClass: 'bg-gray-400',
  },
  draft: {
    label: 'Draft',
    className: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
    dotClass: 'bg-gray-400',
  },
  published: {
    label: 'Published',
    className: 'bg-green-50 text-green-700 dark:bg-green-950 dark:text-green-300',
    dotClass: 'bg-green-500',
  },
};

interface StatusBadgeProps {
  status: AnyStatus;
  size?: 'sm' | 'md';
}

export function StatusBadge({ status, size = 'md' }: StatusBadgeProps) {
  const config = statusConfig[status] || statusConfig.pending;
  const sizeClass = size === 'sm' ? 'text-xs px-2 py-0.5' : 'text-xs px-2.5 py-1';

  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full font-medium ${sizeClass} ${config.className}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${config.dotClass}`} />
      {config.label}
    </span>
  );
}
