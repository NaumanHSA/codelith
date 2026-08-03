import React from 'react';
import { AlertTriangle } from 'lucide-react';

interface Props {
  children: React.ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Without this, a render error anywhere unmounts the whole React tree and the
 * user sees a blank page. Keeps the shell alive so they can navigate away.
 */
export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('Render error:', error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="p-8">
        <div className="max-w-lg mx-auto mt-12 rounded-xl border border-destructive/30 bg-destructive/5 p-6">
          <div className="flex items-center gap-2.5 mb-3">
            <AlertTriangle size={18} className="text-destructive" />
            <h2 className="text-foreground" style={{ fontSize: '1rem', fontWeight: 600 }}>
              This page hit an error
            </h2>
          </div>
          <p className="text-muted-foreground mb-4" style={{ fontSize: '0.875rem' }}>
            The rest of the app is still running — use the sidebar to go somewhere else.
          </p>
          <pre
            className="p-3 rounded-lg bg-card border border-border text-destructive overflow-x-auto mb-4"
            style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem' }}
          >
            {error.message}
          </pre>
          <button
            onClick={() => this.setState({ error: null })}
            className="px-3.5 py-2 rounded-lg bg-primary text-primary-foreground hover:opacity-90 transition-opacity"
            style={{ fontSize: '0.8125rem', fontWeight: 500 }}
          >
            Try again
          </button>
        </div>
      </div>
    );
  }
}
