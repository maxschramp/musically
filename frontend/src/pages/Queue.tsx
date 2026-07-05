// ============================================
// Musically — Queue Page
// Filterable table with bulk actions for the download queue
// ============================================

import { useState, useMemo, useCallback } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Check, X, RotateCw, ListMusic, Trash2 } from 'lucide-react';
import { apiClient } from '@/api/client';
import { useIsMobile } from '@/hooks/useMediaQuery';
import { useInfiniteScroll } from '@/hooks/useInfiniteScroll';
import { Badge } from '@/components/shared/Badge';
import { Button } from '@/components/shared/Button';
import { Card } from '@/components/shared/Card';
import { EmptyState } from '@/components/shared/EmptyState';
import { ErrorState } from '@/components/shared/ErrorState';
import { LoadingSpinner } from '@/components/shared/LoadingSpinner';
import { formatDate } from '@/utils/format';
import type { Album } from '@/types';

type QueueTab = 'manual' | 'stalled';

const TABS: { key: QueueTab; label: string }[] = [
  { key: 'manual', label: 'Pending' },
  { key: 'stalled', label: 'Stalled' },
];

const EMPTY_MESSAGES: Record<QueueTab, { title: string; description: string }> = {
  manual: {
    title: 'No albums pending review',
    description:
      'Albums queued by the rule engine or from Spotify playlists will appear here for your approval. Auto-queued albums are downloaded automatically.',
  },
  stalled: {
    title: 'No stalled items',
    description: 'Stalled downloads will appear here for retry.',
  },
};

function ReasonTag({ reason }: { reason: string }) {
  return (
    <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-soft-stone text-ink whitespace-nowrap">
      {reason}
    </span>
  );
}

export function Queue() {
  const [activeTab, setActiveTab] = useState<QueueTab>('manual');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [approvingId, setApprovingId] = useState<string | null>(null);
  const [rejectingId, setRejectingId] = useState<string | null>(null);
  const [retryingId, setRetryingId] = useState<string | null>(null);

  const isMobile = useIsMobile();
  const queryClient = useQueryClient();

  // Build query params: pending filters by type+status, stalled filters by status
  const queryParams = useMemo(() => {
    const params: Record<string, string | number | boolean | undefined> = {
      sort: '-created_at',
    };
    if (activeTab === 'manual') {
      params.type = 'manual';
      params.status = 'queued';
    } else if (activeTab === 'stalled') {
      params.status = 'stalled';
    }
    return params;
  }, [activeTab]);

  const {
    items,
    isLoading,
    isLoadingMore,
    isError,
    hasMore,
    loaderRef,
    refetch,
    reset,
    total,
  } = useInfiniteScroll<Album>(
    ['queue', activeTab],
    '/queue',
    queryParams,
  );

  const invalidateQueue = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['queue'] });
  }, [queryClient]);

  // ---- Mutations ----

  const approveMutation = useMutation({
    mutationFn: async (id: string) => {
      setApprovingId(id);
      return apiClient.post<Album>(`/queue/${id}/approve`);
    },
    onSettled: () => setApprovingId(null),
    onSuccess: invalidateQueue,
  });

  const rejectMutation = useMutation({
    mutationFn: async (id: string) => {
      setRejectingId(id);
      return apiClient.post<Album>(`/queue/${id}/reject`);
    },
    onSettled: () => setRejectingId(null),
    onSuccess: invalidateQueue,
  });

  const retryMutation = useMutation({
    mutationFn: async (id: string) => {
      setRetryingId(id);
      return apiClient.post<Album>(`/queue/${id}/retry`);
    },
    onSettled: () => setRetryingId(null),
    onSuccess: invalidateQueue,
  });

  const bulkApproveMutation = useMutation({
    mutationFn: (ids: string[]) => apiClient.post('/queue/bulk-approve', { ids }),
    onSuccess: () => {
      setSelected(new Set());
      invalidateQueue();
    },
  });

  const bulkRejectMutation = useMutation({
    mutationFn: (ids: string[]) => apiClient.post('/queue/bulk-reject', { ids }),
    onSuccess: () => {
      setSelected(new Set());
      invalidateQueue();
    },
  });

  const clearStalledMutation = useMutation({
    mutationFn: () => apiClient.post('/queue/clear-stalled'),
    onSuccess: () => {
      reset();
      invalidateQueue();
    },
  });

  // ---- Handlers ----

  const handleTabChange = useCallback((tab: QueueTab) => {
    setActiveTab(tab);
    setSelected(new Set());
    reset();
  }, [reset]);

  const toggleSelect = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleSelectAll = useCallback(() => {
    setSelected((prev) => {
      if (prev.size === items.length) return new Set();
      return new Set(items.map((item: Album) => item.id));
    });
  }, [items]);

  // ---- Derived ----

  const allSelected = items.length > 0 && selected.size === items.length;

  // ---- Render ----

  if (isLoading) return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <LoadingSpinner size="lg" label="Loading queue…" />
    </div>
  );
  if (isError) return <ErrorState onRetry={() => refetch()} />;

  if (items.length === 0) {
    return (
      <div className="space-y-6">
        <TabBar activeTab={activeTab} onTabChange={handleTabChange} />
        <EmptyState
          icon={<ListMusic className="w-16 h-16" />}
          title={EMPTY_MESSAGES[activeTab].title}
          description={EMPTY_MESSAGES[activeTab].description}
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <TabBar activeTab={activeTab} onTabChange={handleTabChange} />
        {activeTab === 'stalled' && items.length > 0 && (
          <Button
            variant="danger"
            size="sm"
            onClick={() => {
              if (window.confirm(`Delete all ${items.length} stalled album(s)? This cannot be undone.`)) {
                clearStalledMutation.mutate();
              }
            }}
            loading={clearStalledMutation.isPending}
            leftIcon={<Trash2 className="w-4 h-4" />}
          >
            Clear Stalled
          </Button>
        )}
      </div>

      {/* Bulk Action Bar */}
      {selected.size > 0 && (
        <div className="sticky top-0 z-10 bg-primary text-on-primary rounded-lg px-4 py-3 flex items-center justify-between shadow-lg">
          <span className="text-sm font-medium">
            {selected.size} selected
          </span>
          <div className="flex gap-2">
            <Button
              variant="ghost"
              size="sm"
              className="text-on-primary hover:bg-white/10"
              onClick={() => bulkApproveMutation.mutate([...selected])}
              loading={bulkApproveMutation.isPending}
              leftIcon={<Check className="w-4 h-4" />}
            >
              Approve
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="text-on-primary hover:bg-white/10"
              onClick={() => bulkRejectMutation.mutate([...selected])}
              loading={bulkRejectMutation.isPending}
              leftIcon={<X className="w-4 h-4" />}
            >
              Reject
            </Button>
          </div>
        </div>
      )}

      {isMobile ? (
        <MobileCardList
          items={items}
          approvingId={approvingId}
          rejectingId={rejectingId}
          retryingId={retryingId}
          onApprove={(id) => approveMutation.mutate(id)}
          onReject={(id) => rejectMutation.mutate(id)}
          onRetry={(id) => retryMutation.mutate(id)}
        />
      ) : (
        <DesktopTable
          items={items}
          selected={selected}
          allSelected={allSelected}
          approvingId={approvingId}
          rejectingId={rejectingId}
          retryingId={retryingId}
          onToggleSelect={toggleSelect}
          onToggleSelectAll={toggleSelectAll}
          onApprove={(id) => approveMutation.mutate(id)}
          onReject={(id) => rejectMutation.mutate(id)}
          onRetry={(id) => retryMutation.mutate(id)}
          totalItems={total}
        />
      )}

      {/* Infinite scroll sentinel */}
      {hasMore && (
        <div ref={loaderRef} className="py-4 flex justify-center">
          {isLoadingMore ? <LoadingSpinner size="sm" /> : null}
        </div>
      )}
    </div>
  );
}

// ============================================
// Sub-components
// ============================================

function TabBar({
  activeTab,
  onTabChange,
}: {
  activeTab: QueueTab;
  onTabChange: (tab: QueueTab) => void;
}) {
  return (
    <div className="flex gap-2 overflow-x-auto pb-2">
      {TABS.map((tab) => (
        <button
          key={tab.key}
          type="button"
          onClick={() => onTabChange(tab.key)}
          className={`px-4 py-2 rounded-xl text-sm font-medium transition-colors duration-150 whitespace-nowrap cursor-pointer ${
            activeTab === tab.key
              ? 'bg-primary text-on-primary'
              : 'bg-transparent text-body-muted hover:bg-gray-100 border border-hairline'
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

// ---- Mobile ----

function MobileCardList({
  items,
  approvingId,
  rejectingId,
  retryingId,
  onApprove,
  onReject,
  onRetry,
}: {
  items: Album[];
  approvingId: string | null;
  rejectingId: string | null;
  retryingId: string | null;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onRetry: (id: string) => void;
}) {
  return (
    <div className="space-y-3">
      {items.map((album) => (
        <Card key={album.id} padding="md">
          <div className="flex flex-col gap-2">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <p className="text-xs text-muted truncate">{album.artist_name}</p>
                <p className="font-display text-base text-ink truncate">{album.title}</p>
              </div>
              <Badge status={album.status} />
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <ReasonTag reason={album.reason} />
              {album.play_count > 0 && (
                <span className="text-xs text-body-muted">{album.play_count} plays</span>
              )}
              <span className="text-xs text-body-muted">{formatDate(album.created_at)}</span>
            </div>
            <div className="flex gap-2 mt-1">
              {album.status === 'queued' && (
                <>
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => onApprove(album.id)}
                    loading={approvingId === album.id}
                    leftIcon={<Check className="w-4 h-4" />}
                  >
                    Approve
                  </Button>
                  <Button
                    variant="danger"
                    size="sm"
                    onClick={() => onReject(album.id)}
                    loading={rejectingId === album.id}
                    leftIcon={<X className="w-4 h-4" />}
                  >
                    Reject
                  </Button>
                </>
              )}
              {album.status === 'stalled' && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onRetry(album.id)}
                  loading={retryingId === album.id}
                  leftIcon={<RotateCw className="w-4 h-4" />}
                >
                  Retry
                </Button>
              )}
            </div>
          </div>
        </Card>
      ))}
    </div>
  );
}

// ---- Desktop ----

function DesktopTable({
  items,
  selected,
  allSelected,
  approvingId,
  rejectingId,
  retryingId,
  onToggleSelect,
  onToggleSelectAll,
  onApprove,
  onReject,
  onRetry,
  totalItems,
}: {
  items: Album[];
  selected: Set<string>;
  allSelected: boolean;
  approvingId: string | null;
  rejectingId: string | null;
  retryingId: string | null;
  onToggleSelect: (id: string) => void;
  onToggleSelectAll: () => void;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onRetry: (id: string) => void;
  totalItems: number;
}) {
  return (
    <Card padding="none" className="overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-card-border bg-soft-stone/50">
              <th className="px-4 py-3 text-left w-10">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={onToggleSelectAll}
                  className="rounded border-hairline cursor-pointer"
                />
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-muted uppercase tracking-wider">
                Album
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-muted uppercase tracking-wider">
                Reason
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-muted uppercase tracking-wider">
                Status
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-muted uppercase tracking-wider">
                Date
              </th>
              <th className="px-4 py-3 text-right text-xs font-medium text-muted uppercase tracking-wider">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-card-border">
            {items.map((album) => (
              <tr
                key={album.id}
                className="hover:bg-soft-stone/30 transition-colors"
              >
                <td className="px-4 py-3">
                  <input
                    type="checkbox"
                    checked={selected.has(album.id)}
                    onChange={() => onToggleSelect(album.id)}
                    className="rounded border-hairline cursor-pointer"
                  />
                </td>
                <td className="px-4 py-3">
                  <p className="text-xs text-muted">{album.artist_name}</p>
                  <p className="font-display text-ink font-medium">{album.title}</p>
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <ReasonTag reason={album.reason} />
                    {album.play_count > 0 && (
                      <span className="text-xs text-body-muted">{album.play_count} plays</span>
                    )}
                  </div>
                </td>
                <td className="px-4 py-3">
                  <Badge status={album.status} />
                </td>
                <td className="px-4 py-3 text-body-muted text-xs whitespace-nowrap">
                  {formatDate(album.created_at)}
                </td>
                <td className="px-4 py-3 text-right">
                  <div className="flex items-center justify-end gap-1">
                    {album.status === 'queued' && (
                      <>
                        <button
                          type="button"
                          onClick={() => onApprove(album.id)}
                          disabled={approvingId === album.id}
                          className="p-1.5 rounded-md text-deep-green hover:bg-pale-green transition-colors cursor-pointer disabled:opacity-50"
                          title="Approve"
                        >
                          {approvingId === album.id ? (
                            <span className="inline-block w-4 h-4 border-2 border-deep-green border-t-transparent rounded-full animate-spin" />
                          ) : (
                            <Check className="w-4 h-4" />
                          )}
                        </button>
                        <button
                          type="button"
                          onClick={() => onReject(album.id)}
                          disabled={rejectingId === album.id}
                          className="p-1.5 rounded-md text-coral hover:bg-red-50 transition-colors cursor-pointer disabled:opacity-50"
                          title="Reject"
                        >
                          {rejectingId === album.id ? (
                            <span className="inline-block w-4 h-4 border-2 border-coral border-t-transparent rounded-full animate-spin" />
                          ) : (
                            <X className="w-4 h-4" />
                          )}
                        </button>
                      </>
                    )}
                    {album.status === 'stalled' && (
                      <button
                        type="button"
                        onClick={() => onRetry(album.id)}
                        disabled={retryingId === album.id}
                        className="p-1.5 rounded-md text-ink hover:bg-gray-100 transition-colors cursor-pointer disabled:opacity-50"
                        title="Retry"
                      >
                        {retryingId === album.id ? (
                          <span className="inline-block w-4 h-4 border-2 border-ink border-t-transparent rounded-full animate-spin" />
                        ) : (
                          <RotateCw className="w-4 h-4" />
                        )}
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Footer with item count */}
      <div className="flex items-center justify-between px-4 py-3 border-t border-card-border">
        <span className="text-xs text-body-muted">
          {items.length} of {totalItems} items
        </span>
      </div>
    </Card>
  );
}
