// ============================================
// Musically — Badge Component
// Status badge: queued=gray, downloading=blue,
// downloaded=green, stalled=yellow, rejected=red
// ============================================

import type { AlbumStatus } from '@/types';

interface BadgeProps {
  status: AlbumStatus;
  className?: string;
}

const statusConfig: Record<AlbumStatus, { label: string; bg: string; text: string; dot: string }> = {
  queued: {
    label: 'Queued',
    bg: 'bg-soft-stone',
    text: 'text-ink',
    dot: 'bg-ink',
  },
  downloading: {
    label: 'Downloading',
    bg: 'bg-action-blue',
    text: 'text-white',
    dot: 'bg-white',
  },
  downloaded: {
    label: 'Downloaded',
    bg: 'bg-deep-green',
    text: 'text-white',
    dot: 'bg-white',
  },
  stalled: {
    label: 'Stalled',
    bg: 'bg-yellow-500',
    text: 'text-white',
    dot: 'bg-white',
  },
  rejected: {
    label: 'Rejected',
    bg: 'bg-hairline',
    text: 'text-muted',
    dot: 'bg-muted',
  },
};

export function Badge({ status, className = '' }: BadgeProps) {
  const config = statusConfig[status];

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${config.bg} ${config.text} ${className}`}
    >
      <span className={`inline-block w-1.5 h-1.5 rounded-full ${config.dot}`} />
      {config.label}
    </span>
  );
}
