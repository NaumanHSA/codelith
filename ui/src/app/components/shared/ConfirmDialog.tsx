import { useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { X, AlertTriangle } from 'lucide-react';

interface ConfirmDialogProps {
  trigger: React.ReactNode;
  title: string;
  description: string;
  confirmLabel?: string;
  variant?: 'danger' | 'default';
  onConfirm: () => void | Promise<void>;
}

export function ConfirmDialog({
  trigger,
  title,
  description,
  confirmLabel = 'Confirm',
  variant = 'default',
  onConfirm,
}: ConfirmDialogProps) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleConfirm = async () => {
    setLoading(true);
    try {
      await onConfirm();
      setOpen(false);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>{trigger}</Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 animate-in fade-in-0" />
        <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-md bg-card border border-border rounded-xl shadow-xl p-6 animate-in fade-in-0 zoom-in-95">
          <div className="flex items-start gap-3 mb-4">
            <div className={`mt-0.5 flex-shrink-0 ${variant === 'danger' ? 'text-destructive' : 'text-foreground'}`}>
              <AlertTriangle size={20} />
            </div>
            <div>
              <Dialog.Title className="text-foreground mb-1" style={{ fontSize: '1rem', fontWeight: 600 }}>{title}</Dialog.Title>
              <Dialog.Description className="text-muted-foreground" style={{ fontSize: '0.875rem' }}>{description}</Dialog.Description>
            </div>
          </div>
          <div className="flex justify-end gap-2 mt-6">
            <Dialog.Close asChild>
              <button className="px-4 py-2 rounded-lg border border-border text-foreground hover:bg-accent transition-colors" style={{ fontSize: '0.875rem' }}>
                Cancel
              </button>
            </Dialog.Close>
            <button
              onClick={handleConfirm}
              disabled={loading}
              className={`px-4 py-2 rounded-lg font-medium transition-colors disabled:opacity-50 ${
                variant === 'danger'
                  ? 'bg-destructive text-white hover:bg-destructive/90'
                  : 'bg-primary text-primary-foreground hover:bg-primary/90'
              }`}
              style={{ fontSize: '0.875rem' }}
            >
              {loading ? 'Loading...' : confirmLabel}
            </button>
          </div>
          <Dialog.Close asChild>
            <button className="absolute top-4 right-4 text-muted-foreground hover:text-foreground">
              <X size={16} />
            </button>
          </Dialog.Close>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
