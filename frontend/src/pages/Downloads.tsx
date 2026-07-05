// ============================================
// Musically — Downloads Pipeline Page
// Live view of the download pipeline: downloading,
// up next (queued), and recently downloaded.
// Auto-refreshes every 10 seconds.
// ============================================

import { useState, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Download,
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  Disc3,
  RefreshCw,
  ChevronRight,
  Loader2,
} from 'lucide-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { useApiQuery } from '@/hooks/useApi';
import { useIsMobile } from '@/hooks/useMediaQuery';
import { Badge } from '@/components/shared/Badge';
import { Card } from '@/components/shared/Card';
import { Button } from '@/components/shared/Button';
import { EmptyState } from '@/components/shared/EmptyState';
import { ErrorState } from '@/components/shared/ErrorState';
import { PageLoading } from '@/components/shared/LoadingSpinner';
import { formatRelativeTime, formatNumber, truncate } from '@/utils/format';
import type { Album, PaginatedResponse } from '@/types';

// ============================================
// Constants
// ============================================

const MAX_VISIBLE_PER_SECTION = 10;
const REFETCH_INTERVAL = 10_000; // 10 seconds

// ============================================
// Section Header
// ============================================

interface SectionHeaderProps {
  dotColor: string;
  label: string;
  count: number;
  icon: React.ReactNode;
}

function SectionHeader({ dotColor, label, count, icon }: SectionHeaderProps) {
  return (
    <div className="flex items-center gap-2.5 px-1 py-3">
      <span className={`inline-block w-2.5 h-2.5 rounded-full ${dotColor}`} />
      <span className="text-sm font-medium text-ink tracking-wide uppercase">
        {icon}
      </span>
      <h2 className="text-sm font-medium text-ink tracking-wide uppercase flex items-center gap-1.5">
        {label}
        <span className="inline-flex items-center justify-center min-w-[22px] h-[22px] px-1.5 rounded-full bg-soft-stone text-xs font-medium text-muted">
          {formatNumber(count)}
        </span>
      </h2>
    </div>
  );
}

// ============================================
// Pipeline Item Row
// ============================================

interface PipelineItemProps {
  album: Album;
  onDownloadNow?: (id: string) => void;
  isDownloadingNow?: boolean;
}

function PipelineItem({ album, onDownloadNow, isDownloadingNow }: PipelineItemProps) {
  const [imgError, setImgError] = useState(false);
  const isMobile = useIsMobile();

  const artworkUrl = imgError
    ? null
    : `/api/albums/${album.id}/artwork`;

  return (
    <div className="flex items-center gap-3 px-3 py-2.5 hover:bg-soft-stone/50 rounded-sm transition-colors duration-150 group">
      {/* Album Artwork */}
      <div className="w-10 h-10 rounded-sm bg-soft-stone overflow-hidden shrink-0 flex items-center justify-center">
        {artworkUrl && !imgError ? (
          <img
            src={artworkUrl}
            alt={`${album.title} artwork`}
            className="w-full h-full object-cover"
            onError={() => setImgError(true)}
            loading="lazy"
          />
        ) : (
          <Disc3 className="w-5 h-5 text-muted" />
        )}
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <p className="text-sm text-ink truncate leading-snug">
          <span className="font-medium">{truncate(album.artist_name, 24)}</span>
          <span className="text-muted mx-1">—</span>
          <span className="text-body-muted">{truncate(album.title, 36)}</span>
        </p>
        <div className="flex items-center gap-2 mt-0.5">
          {/* Queue type pill */}
          <span
            className={`inline-flex items-center px-1.5 py-px rounded-sm text-[10px] font-medium uppercase tracking-wide ${
              album.queue_type === 'auto'
                ? 'bg-pale-blue text-action-blue'
                : album.queue_type === 'manual'
                  ? 'bg-pale-green text-deep-green'
                  : 'bg-soft-stone text-slate'
            }`}
          >
            {album.queue_type}
          </span>
          {/* Relative time */}
          <span className="text-[11px] text-muted">
            {formatRelativeTime(album.status === 'downloaded' && album.downloaded_at ? album.downloaded_at : album.created_at)}
          </span>
        </div>

        {/* Indeterminate progress bar for downloading items */}
        {album.status === 'downloading' && (
          <div className="mt-1.5">
            <div className="w-full bg-soft-stone rounded-full h-1.5 overflow-hidden">
              <div className="bg-action-blue h-1.5 rounded-full animate-pulse w-full" />
            </div>
            <p className="text-[10px] text-muted mt-0.5">Downloading…</p>
          </div>
        )}
      </div>

      {/* Action buttons */}
      <div className="shrink-0 flex items-center gap-1.5">
        {album.status === 'queued' && onDownloadNow && (
          <button
            onClick={(e) => { e.stopPropagation(); onDownloadNow(album.id); }}
            disabled={isDownloadingNow}
            className="p-1.5 rounded-sm text-muted hover:text-action-blue hover:bg-pale-blue transition-colors opacity-0 group-hover:opacity-100 disabled:opacity-100 disabled:text-action-blue"
            title="Download now"
          >
            {isDownloadingNow ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Download className="w-4 h-4" />
            )}
          </button>
        )}
        {/* Status pill (hidden on mobile) */}
        {!isMobile && <Badge status={album.status} />}
      </div>
    </div>
  );
}

// ============================================
// Section "View All" Row
// ============================================

interface ViewAllRowProps {
  count: number;
  onClick: () => void;
}

function ViewAllRow({ count, onClick }: ViewAllRowProps) {
  return (
    <button
      onClick={onClick}
      className="w-full flex items-center justify-center gap-1.5 px-3 py-2.5 text-sm text-muted hover:text-ink hover:bg-soft-stone/50 rounded-sm transition-colors duration-150"
    >
      <span>...and {formatNumber(count)} more</span>
      <ChevronRight className="w-4 h-4" />
    </button>
  );
}

// ============================================
// Downloads Page
// ============================================

export function Downloads() {
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const queryClient = useQueryClient();

  const downloadNowMutation = useMutation({
    mutationFn: (id: string) => apiClient.post(`/queue/${id}/approve`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['queue'] });
      queryClient.invalidateQueries({ queryKey: ['queue', 'pipeline'] });
    },
  });

  const handleDownloadNow = useCallback((id: string) => {
    downloadNowMutation.mutate(id);
  }, [downloadNowMutation]);

  // Fetch items by status separately so all items appear regardless of creation date
  const { data: downloadingData } = useApiQuery<PaginatedResponse<Album>>(
    ['queue', 'pipeline', 'downloading'],
    '/queue',
    { status: 'downloading', sort: '-created_at', limit: 10 },
    { refetchInterval: REFETCH_INTERVAL },
  );

  const { data: downloadedData } = useApiQuery<PaginatedResponse<Album>>(
    ['queue', 'pipeline', 'downloaded'],
    '/queue',
    { status: 'downloaded', sort: '-downloaded_at', limit: 10 },
    { refetchInterval: REFETCH_INTERVAL },
  );

  const {
    data,
    isLoading,
    isError,
    refetch,
    isRefetching,
  } = useApiQuery<PaginatedResponse<Album>>(
    ['queue', 'pipeline', 'queued'],
    '/queue',
    { status: 'queued', sort: '-created_at', limit: 100 },
    { refetchInterval: REFETCH_INTERVAL },
  );

  // Split items by status from separate queries
  const { downloading, upNext, downloaded } = useMemo(() => ({
    downloading: downloadingData?.items ?? [],
    upNext: data?.items ?? [],
    downloaded: downloadedData?.items ?? [],
  }), [data, downloadingData, downloadedData]);

  // ---- Render helpers ----

  const renderSectionItems = useCallback(
    (items: Album[], maxVisible: number) => {
      const visible = items.slice(0, maxVisible);
      const remaining = items.length - maxVisible;

      return (
        <>
          {visible.map((album) => (
            <PipelineItem
              key={album.id}
              album={album}
              onDownloadNow={handleDownloadNow}
              isDownloadingNow={
                downloadNowMutation.isPending &&
                downloadNowMutation.variables === album.id
              }
            />
          ))}
          {remaining > 0 && (
            <ViewAllRow
              count={remaining}
              onClick={() => navigate('/queue')}
            />
          )}
        </>
      );
    },
    [navigate, handleDownloadNow, downloadNowMutation],
  );

  // ---- Loading state ----
  // Show page loading only if the main queued query is loading AND
  // there are no downloading/downloaded results to show yet.
  const hasCachedData = (downloadingData?.items?.length ?? 0) > 0 ||
    (downloadedData?.items?.length ?? 0) > 0;

  if (isLoading && !hasCachedData) return <PageLoading />;
  if (isError) {
    return (
      <ErrorState
        title="Failed to load pipeline"
        message="Could not fetch the download queue. Please check your connection and try again."
        onRetry={() => refetch()}
      />
    );
  }
  if (!data && !hasCachedData) return null;

  // ---- All sections empty ----

  const totalItems = downloading.length + upNext.length + downloaded.length;
  if (totalItems === 0) {
    return (
      <div className="space-y-6">
        {/* Page header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-display text-2xl text-ink">Downloads</h1>
            <p className="text-sm text-body-muted mt-1">
              Monitor your download pipeline in real time
            </p>
          </div>
          {/* Refresh button */}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => refetch()}
            loading={isRefetching}
            leftIcon={<RefreshCw className="w-4 h-4" />}
          >
            {isMobile ? '' : 'Refresh'}
          </Button>
        </div>

        <EmptyState
          icon={<Download className="w-16 h-16" />}
          title="No Downloads Yet"
          description="Albums queued for download will appear here. Use the Discover page to find music or wait for the rule engine to find matches."
        />
      </div>
    );
  }

  // ---- Main render ----

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl text-ink">Downloads</h1>
          <p className="text-sm text-body-muted mt-1 flex items-center gap-2">
            Live pipeline view
            {isRefetching && (
              <span className="inline-block w-2 h-2 rounded-full bg-coral animate-pulse" />
            )}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {/* Auto-refresh badge */}
          <span className="hidden sm:inline-flex items-center gap-1.5 text-[11px] text-muted bg-soft-stone px-2 py-1 rounded-full">
            <span className="w-1.5 h-1.5 rounded-full bg-deep-green animate-pulse" />
            Auto-refresh
          </span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => refetch()}
            loading={isRefetching}
            leftIcon={<RefreshCw className="w-4 h-4" />}
          >
            {isMobile ? '' : 'Refresh'}
          </Button>
        </div>
      </div>

      {/* ---- Section: Downloading ---- */}
      <Card padding="none" className="overflow-hidden">
        <div className="px-4 border-b border-hairline">
          <SectionHeader
            dotColor="bg-action-blue animate-pulse"
            label="Downloading"
            count={downloading.length}
            icon={<ArrowDown className="w-4 h-4 text-action-blue" />}
          />
        </div>
        <div className="divide-y divide-hairline/50">
          {downloading.length > 0 ? (
            renderSectionItems(downloading, MAX_VISIBLE_PER_SECTION)
          ) : (
            <div className="py-8 text-center">
              <p className="text-sm text-muted">No active downloads. Albums will appear here when the download pipeline picks them up.</p>
            </div>
          )}
        </div>
      </Card>

      {/* ---- Section: Up Next ---- */}
      <Card padding="none" className="overflow-hidden">
        <div className="px-4 border-b border-hairline">
          <SectionHeader
            dotColor="bg-yellow-500"
            label="Up Next"
            count={upNext.length}
            icon={<ArrowUp className="w-4 h-4 text-yellow-600" />}
          />
        </div>
        <div className="divide-y divide-hairline/50">
          {upNext.length > 0 ? (
            renderSectionItems(upNext, MAX_VISIBLE_PER_SECTION)
          ) : (
            <div className="py-8 text-center">
              <p className="text-sm text-muted">Queue is empty. Albums queued by the rule engine or manually added will appear here.</p>
            </div>
          )}
        </div>
      </Card>

      {/* ---- Section: Recently Downloaded ---- */}
      <Card padding="none" className="overflow-hidden">
        <div className="px-4 border-b border-hairline">
          <SectionHeader
            dotColor="bg-deep-green"
            label="Recently Downloaded"
            count={downloaded.length}
            icon={<CheckCircle2 className="w-4 h-4 text-deep-green" />}
          />
        </div>
        <div className="divide-y divide-hairline/50">
          {downloaded.length > 0 ? (
            renderSectionItems(downloaded, MAX_VISIBLE_PER_SECTION)
          ) : (
            <div className="py-8 text-center">
              <p className="text-sm text-muted">No downloads yet. Albums will appear here once downloaded and imported.</p>
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
