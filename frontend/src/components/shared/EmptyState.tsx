// ============================================
// Musically — EmptyState Component
// Icon + message + optional action button for empty lists
// ============================================

import type { ReactNode } from 'react';
import { Disc3 } from 'lucide-react';
import { Button } from './Button';

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
}

export function EmptyState({
  icon,
  title,
  description,
  actionLabel,
  onAction,
}: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-4 text-center">
      <div className="text-muted mb-4">
        {icon ?? <Disc3 className="w-16 h-16" />}
      </div>
      <h3 className="text-lg font-medium text-ink mb-2">
        {title}
      </h3>
      {description && (
        <p className="text-sm text-body-muted max-w-sm mb-6">
          {description}
        </p>
      )}
      {actionLabel && onAction && (
        <Button variant="primary" size="md" onClick={onAction}>
          {actionLabel}
        </Button>
      )}
    </div>
  );
}
