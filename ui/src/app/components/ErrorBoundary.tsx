import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Button } from './ui'

/* ------------------------------------------------------------------ *
 * Route-level error boundary.
 *
 * A previous build typed integer IDs as strings, called .slice() on one,
 * and blanked the entire app. This fails to a readable screen instead of
 * a white page, and offers a way out that does not require a reload.
 * ------------------------------------------------------------------ */

interface Props {
  children: ReactNode
  /** Changing this resets the boundary — pass the current route key. */
  resetKey?: string
}

interface State {
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidUpdate(prev: Props) {
    // Navigating away from a broken screen should clear the error.
    if (this.state.error && prev.resetKey !== this.props.resetKey) {
      this.setState({ error: null })
    }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Local-only: this never leaves the machine.
    console.error('Route crashed:', error, info.componentStack)
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children

    return (
      <div className="bp-grid flex min-h-full items-center justify-center p-6">
        <div className="plate max-w-[560px] p-5">
          <div className="mb-3 flex items-center gap-2">
            <span className="block size-2.5 rotate-45 bg-bad" />
            <span className="tag text-bad">Screen failed to render</span>
          </div>
          <h1 className="mb-2 text-[19px] leading-tight font-bold tracking-tight text-ink">
            This screen hit an error.
          </h1>
          <p className="mb-3 font-sans text-[13px] leading-relaxed text-ink-mid">
            The rest of the studio is still running — you can go back and carry on. If it keeps
            happening, the message below is the useful part.
          </p>
          <pre className="mb-4 max-h-40 overflow-auto border border-rule bg-sunk px-2.5 py-2 text-[11px] leading-relaxed whitespace-pre-wrap text-ink-mid">
            {error.message || String(error)}
          </pre>
          <div className="flex flex-wrap gap-2">
            <Button variant="hot" onClick={() => this.setState({ error: null })}>
              ↻ Retry this screen
            </Button>
            <Button variant="ghost" onClick={() => window.history.back()}>
              ← Go back
            </Button>
          </div>
        </div>
      </div>
    )
  }
}
