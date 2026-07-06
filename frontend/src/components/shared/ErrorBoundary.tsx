// ============================================
// Musically — Error Boundary
// Catches render errors and shows a friendly fallback
// ============================================

import { Component, type ReactNode, type ErrorInfo } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import { Button } from '@/components/shared/Button';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('[ErrorBoundary]', error, info.componentStack);
  }

  handleRetry = (): void => {
    this.setState({ hasError: false, error: null });
  };

  render(): ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;

      return (
        <div className="min-h-[400px] flex items-center justify-center p-8">
          <div className="text-center max-w-md">
            <div className="icon-chip icon-chip-coral mx-auto mb-4">
              <AlertTriangle className="w-6 h-6" />
            </div>
            <h2 className="font-display text-xl text-ink mb-2">
              Something went wrong
            </h2>
            <p className="text-sm text-body-muted mb-6">
              An unexpected error occurred while rendering this page.
              {this.state.error && (
                <span className="block mt-1 font-mono text-xs opacity-70">
                  {this.state.error.message}
                </span>
              )}
            </p>
            <Button
              variant="primary"
              size="md"
              leftIcon={<RefreshCw className="w-4 h-4" />}
              onClick={this.handleRetry}
            >
              Retry
            </Button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
