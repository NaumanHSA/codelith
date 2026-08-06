import { useState } from 'react'
import { ApiError } from '../lib/api'
import { Button, Dialog, inputClass } from './ui'
import { ErrorState } from './States'

/* ------------------------------------------------------------------ *
 * One confirmation for everything destructive.
 *
 * Deleting a project takes its jobs, documents and whole site with it,
 * so that one asks the user to type the name — the standard friction
 * for an action with no undo. Deleting a job is recoverable in the only
 * sense that matters (the pages it wrote survive), so it only asks.
 * ------------------------------------------------------------------ */

export default function ConfirmDelete({
  open,
  onClose,
  onConfirm,
  title,
  body,
  /** When set, the user must type this exactly. Use for anything that cascades. */
  confirmText,
  actionLabel = 'Delete',
}: {
  open: boolean
  onClose: () => void
  onConfirm: () => Promise<void>
  title: string
  body: React.ReactNode
  confirmText?: string
  actionLabel?: string
}) {
  const [typed, setTyped] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const armed = !confirmText || typed.trim() === confirmText

  const close = () => {
    setTyped('')
    setError(null)
    onClose()
  }

  const run = async () => {
    if (!armed) return
    setBusy(true)
    setError(null)
    try {
      await onConfirm()
      setTyped('')
      onClose()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not work. Try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onClose={close} title={title} width={460}>
      <div className="p-3">
        {error && <ErrorState message={error} compact />}

        <div className="font-sans text-[12.5px] leading-relaxed text-ink-mid">{body}</div>

        {confirmText && (
          <label className="mt-3 block">
            <span className="tag mb-1 block text-ink-dim">
              type <span className="text-ink">{confirmText}</span> to confirm
            </span>
            <input
              value={typed}
              onChange={e => setTyped(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && armed && run()}
              className={inputClass}
              aria-label={`Type ${confirmText} to confirm`}
            />
          </label>
        )}

        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={close}>
            Keep it
          </Button>
          <Button variant="danger" onClick={run} disabled={busy || !armed}>
            {busy ? 'deleting…' : actionLabel}
          </Button>
        </div>
      </div>
    </Dialog>
  )
}
