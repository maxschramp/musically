// ============================================
// Musically — LoadingSpinner Component
// Cohere-styled loading indicator
// ============================================

import { Loader2 } from 'lucide-react';

interface LoadingSpinnerProps {
  size?: 'sm' | 'md' | 'lg';
  className?: string;
  label?: string;
}

const sizeClasses: Record<string, string> = {
  sm: 'w-4 h-4',
  md: 'w-8 h-8',
  lg: 'w-12 h-12',
};

export function LoadingSpinner({ size = 'md', className = '', label }: LoadingSpinnerProps) {
  return (
    <div className={`flex flex-col items-center justify-center gap-3 ${className}`}>
      <Loader2 className={`animate-spin text-muted ${sizeClasses[size]}`} />
      {label && (
        <p className="text-sm text-body-muted">
          {label}
        </p>
      )}
    </div>
  );
}

/**
 * Full-page loading state with centered spinner.
 */
export function PageLoading() {
  return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <LoadingSpinner size="lg" label="Loading…" />
    </div>
  );
}
