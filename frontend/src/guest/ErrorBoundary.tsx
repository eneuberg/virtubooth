/**
 * A render error anywhere in the guest app shows "Etwas ist schiefgelaufen" with
 * "Seite neu laden" instead of a blank page. The raw error is never shown (it goes
 * to the ?debug=1 log).
 */
import { Component, type ErrorInfo, type ReactNode } from 'react';
import { debugLog } from '@/sdk/debug';
import { ErrorScreen } from './SessionGate';

interface State {
  error: unknown;
}

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  override state: State = { error: null };

  static getDerivedStateFromError(error: unknown): State {
    return { error: error ?? new Error('unknown') };
  }

  override componentDidCatch(error: unknown, info: ErrorInfo): void {
    debugLog('render error', error, info.componentStack ?? '');
  }

  override render(): ReactNode {
    // a plain Error (not an ApiError) gets the generic copy, never its message
    if (this.state.error) return <ErrorScreen error={new Error('render')} />;
    return this.props.children;
  }
}
