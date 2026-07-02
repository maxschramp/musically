// ============================================
// Musically — Dashboard Page
// Stats cards with API data + recent activity placeholder
// ============================================

import type { ReactNode } from 'react';
import { BarChart3, Disc3, Download, Clock, Users, Music } from 'lucide-react';
import { Card } from '@/components/shared/Card';
import { useApiQuery } from '@/hooks/useApi';
import { formatNumber, formatRelativeTime } from '@/utils/format';
import type { Album, PaginatedResponse, Stats } from '@/types';

// ============================================
// Stat Card
// ============================================

interface StatCardProps {
  icon: ReactNode;
  label: string;
  value: string;
  color: string;
}

function StatCard({ icon, label, value, color }: StatCardProps) {
  return (
    <Card className="flex items-center gap-4" padding="md">
      <div className={`flex items-center justify-center w-12 h-12 rounded-sm ${color}`}>
        {icon}
      </div>
      <div>
        <p className="text-xs text-muted uppercase tracking-wider">
          {label}
        </p>
        <p className="text-2xl font-display text-ink tracking-tight">
          {value}
        </p>
      </div>
    </Card>
  );
}

// ============================================
// Skeleton Stat Card (loading state)
// ============================================

function StatCardSkeleton({ icon, label, color }: Omit<StatCardProps, 'value'>) {
  return (
    <Card className="flex items-center gap-4" padding="md">
      <div className={`flex items-center justify-center w-12 h-12 rounded-sm ${color}`}>
        {icon}
      </div>
      <div>
        <p className="text-xs text-muted uppercase tracking-wider">
          {label}
        </p>
        <p className="text-2xl font-display text-ink tracking-tight animate-pulse">
          —
        </p>
      </div>
    </Card>
  );
}

// ============================================
// Status Color Helpers
// ============================================

function statusDotColor(status: string): string {
  switch (status) {
    case 'queued': return 'bg-yellow-400';
    case 'downloading': return 'bg-action-blue animate-pulse';
    case 'downloaded': return 'bg-deep-green';
    case 'stalled': return 'bg-coral';
    case 'rejected': return 'bg-hairline';
    default: return 'bg-muted';
  }
}

function statusBadgeColor(status: string): string {
  switch (status) {
    case 'queued': return 'bg-yellow-100 text-yellow-800';
    case 'downloading': return 'bg-blue-100 text-blue-800';
    case 'downloaded': return 'bg-green-100 text-green-800';
    case 'stalled': return 'bg-red-100 text-red-800';
    case 'rejected': return 'bg-gray-100 text-gray-500';
    default: return 'bg-gray-100 text-gray-600';
  }
}

// ============================================
// Dashboard Page
// ============================================

export function Dashboard() {
  const {
    data: stats,
    isLoading,
    isError,
  } = useApiQuery<Stats>(['stats'], '/stats');

  const {
    data: queueData,
    isLoading: queueLoading,
    isError: queueError,
  } = useApiQuery<PaginatedResponse<Album>>(
    ['queue', 'recent'],
    '/queue',
    { sort: '-created_at', limit: 10 },
  );

  const queueItems = queueData?.items ?? [];
  const queueTotal = queueData?.total ?? 0;

  // Show "—" for errors or while loading
  const fmt = (n: number | undefined): string => {
    if (n === undefined || n === null) return '—';
    return formatNumber(n);
  };

  const statCards = [
    {
      icon: <Disc3 className="w-5 h-5 text-white" />,
      label: 'Total Albums',
      value: fmt(stats?.total_albums),
      color: 'bg-primary',
    },
    {
      icon: <Download className="w-5 h-5 text-white" />,
      label: 'Downloaded',
      value: fmt(stats?.downloaded_count),
      color: 'bg-deep-green',
    },
    {
      icon: <Clock className="w-5 h-5 text-white" />,
      label: 'Queued',
      value: fmt(stats?.queued_count),
      color: 'bg-coral',
    },
    {
      icon: <Users className="w-5 h-5 text-white" />,
      label: 'Subscribed Artists',
      value: fmt(stats?.subscribed_artists),
      color: 'bg-dark-navy',
    },
    {
      icon: <Music className="w-5 h-5 text-white" />,
      label: 'Track Plays',
      value: fmt(stats?.total_track_plays),
      color: 'bg-action-blue',
    },
    {
      icon: <BarChart3 className="w-5 h-5 text-white" />,
      label: 'Stalled',
      value: fmt(stats?.stalled_count),
      color: 'bg-yellow-500',
    },
  ];

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div>
        <h2 className="font-display text-xl text-ink tracking-tight">
          Dashboard
        </h2>
        <p className="text-sm text-body-muted mt-1">
          Overview of your music library and automation status.
        </p>
        {isError && (
          <p className="text-xs text-coral mt-2">
            Could not load stats. Showing cached or default values.
          </p>
        )}
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {isLoading
          ? statCards.map((card) => (
              <StatCardSkeleton
                key={card.label}
                icon={card.icon}
                label={card.label}
                color={card.color}
              />
            ))
          : statCards.map((card) => (
              <StatCard
                key={card.label}
                icon={card.icon}
                label={card.label}
                value={card.value}
                color={card.color}
              />
            ))}
      </div>

      {/* Pipeline Activity Feed */}
      <Card padding="lg">
        <h3 className="font-display text-lg text-ink tracking-tight mb-4">
          Pipeline Activity
        </h3>

        {queueLoading && (
          <div className="space-y-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="flex items-center gap-3 py-2 animate-pulse">
                <div className="w-2.5 h-2.5 rounded-full bg-hairline shrink-0" />
                <div className="flex-1 space-y-1.5">
                  <div className="h-4 bg-hairline rounded w-3/4" />
                  <div className="h-3 bg-hairline rounded w-1/2" />
                </div>
                <div className="h-5 w-16 bg-hairline rounded-full shrink-0" />
                <div className="h-3 w-12 bg-hairline rounded shrink-0" />
              </div>
            ))}
          </div>
        )}

        {queueError && !queueLoading && (
          <p className="text-sm text-coral">Failed to load activity.</p>
        )}

        {queueItems.length === 0 && !queueLoading && (
          <div className="flex flex-col items-center py-8 text-center">
            <Clock className="w-10 h-10 text-hairline mb-3" />
            <p className="text-sm text-body-muted">
              No activity yet. Connect Last.fm and sync to get started.
            </p>
          </div>
        )}

        <div className="space-y-2">
          {queueItems.map((album) => (
            <div
              key={album.id}
              className="flex items-center gap-3 py-2 border-b border-card-border last:border-0"
            >
              {/* Status dot */}
              <div
                className={`w-2.5 h-2.5 rounded-full shrink-0 ${statusDotColor(album.status)}`}
              />

              {/* Album info */}
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-ink truncate">
                  {album.artist_name} — {album.title}
                </p>
                <p className="text-xs text-muted truncate">
                  {album.reason || album.queue_type}
                </p>
              </div>

              {/* Status badge */}
              <span
                className={`text-xs px-2 py-0.5 rounded-full font-medium shrink-0 ${statusBadgeColor(album.status)}`}
              >
                {album.status}
              </span>

              {/* Time */}
              <span className="text-xs text-body-muted shrink-0 w-16 text-right">
                {formatRelativeTime(album.created_at)}
              </span>
            </div>
          ))}
        </div>

        {/* View all link */}
        {queueItems.length > 0 && (
          <div className="mt-4 pt-3 border-t border-card-border">
            <a href="/queue" className="text-xs text-action-blue hover:underline">
              View all {queueTotal} items in Queue →
            </a>
          </div>
        )}
      </Card>
    </div>
  );
}
