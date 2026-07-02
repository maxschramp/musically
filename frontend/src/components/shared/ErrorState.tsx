// ============================================
// Musically — ErrorState Component
// Error display with retry button
// ============================================

import { AlertTriangle } from 'lucide-react';
import { Button } from './Button';

interface ErrorStateProps {
  title?: string;
  message?: string;
  onRetry?: () => void;
  className?: string;
}

export function ErrorState({
  title = 'Something went wrong',
  message = 'An unexpected error occurred. Please try again.',
  onRetry,
  className = '',
}: ErrorStateProps) {
  return (
    <div className={`flex flex-col items-center justify-center py-16 px-4 text-center ${className}`}>
      <div className="text-coral mb-4">
        <AlertTriangle className="w-12 h-12" />
      </div>
      <h3 className="text-lg font-medium text-ink mb-2">
        {title}
      </h3>
      <p className="text-sm text-body-muted max-w-sm mb-6">
        {message}
      </p>
      {onRetry && (
        <Button variant="primary" size="md" onClick={onRetry}>
          Try Again
        </Button>
      )}
    </div>
  );
}
