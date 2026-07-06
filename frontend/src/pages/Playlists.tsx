// ============================================
// Musically — Playlists Page
// Synced Spotify playlists with type filter tabs
// ============================================

import { useState, useMemo, useCallback } from 'react';
import { ListMusic, Loader2, CheckCircle2, AlertTriangle, RefreshCw } from 'lucide-react';
import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { useApiQuery } from '@/hooks/useApi';
import { useIsMobile } from '@/hooks/useMediaQuery';
import { apiClient } from '@/api/client';
import { Card } from '@/components/shared/Card';
import { Button } from '@/components/shared/Button';
import { EmptyState } from '@/components/shared/EmptyState';
import { ErrorState } from '@/components/shared/ErrorState';
import { PageLoading } from '@/components/shared/LoadingSpinner';
import { formatRelativeTime } from '@/utils/format';
import type { Playlist, PaginatedResponse } from '@/types';

// ---- Types ----

type PlaylistTab = 'all' | 'seasonal' | 'discover';

const TABS: { key: PlaylistTab; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'seasonal', label: 'Seasonal' },
  { key: 'discover', label: 'Discover' },
];

const EMPTY_MESSAGES: Record<PlaylistTab, { title: string; description: string }> = {
  all: {
    title: 'No playlists synced yet',
    description:
      'Connect Spotify in Settings to sync your playlists. Seasonal and discover playlists will appear here.',
  },
  seasonal: {
    title: 'No seasonal playlists',
    description:
      'Seasonal playlists (e.g. Winter 2025) will appear here once synced from Spotify.',
  },
  discover: {
    title: 'No discover playlists',
    description:
      'Discover playlists (e.g. Pitchfork Selects) will appear here once synced from Spotify.',
  },
};

// ---- Type badge config ----

const TYPE_BADGE: Record<Playlist['playlist_type'], { label: string; bg: string; text: string }> = {
  seasonal: { label: 'SEASONAL', bg: 'bg-deep-green', text: 'text-white' },
  discover: { label: 'DISCOVER', bg: 'bg-action-blue', text: 'text-white' },
  other: { label: 'OTHER', bg: 'bg-soft-stone', text: 'text-ink' },
};

const TYPE_DOT: Record<Playlist['playlist_type'], string> = {
  seasonal: 'bg-deep-green',
  discover: 'bg-action-blue',
  other: 'bg-muted',
};

// ============================================
// Playlists Page
// ============================================

export function Playlists() {
  const [activeTab, setActiveTab] = useState<PlaylistTab>('all');
  const [refreshing, setRefreshing] = useState(false);
  const isMobile = useIsMobile();
  const queryClient = useQueryClient();

  const { data, isLoading, isError, refetch } = useApiQuery<PaginatedResponse<Playlist>>(
    ['playlists'],
    '/playlists',
    { limit: 200 },
  );

  // Spotify connection status
  const { data: spotifyStatus } = useApiQuery<{
    configured: boolean;
    enabled: boolean;
    authorized: boolean;
    token_expired: boolean;
    token_expiry: string | null;
    last_synced_at: string | null;
    total_playlists: number;
    active_playlists: number;
  }>(
    ['spotify-status'],
    '/spotify/status',
    undefined,
    { refetchInterval: 60_000 }, // refresh every minute
  );

  // Manual playlist refresh
  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await apiClient.post('/playlists/refresh');
      queryClient.invalidateQueries({ queryKey: ['playlists'] });
      queryClient.invalidateQueries({ queryKey: ['spotify-status'] });
    } catch {
      // error handled by the status banner
    } finally {
      setRefreshing(false);
    }
  }, [queryClient]);

  // Toggle playlist active state with optimistic update
  const toggleMutation = useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) =>
      apiClient.put(`/playlists/${id}`, { is_active }),
    onMutate: async ({ id, is_active }) => {
      await queryClient.cancelQueries({ queryKey: ['playlists'] });
      const previous = queryClient.getQueryData<PaginatedResponse<Playlist>>(['playlists']);
      if (previous) {
        queryClient.setQueryData<PaginatedResponse<Playlist>>(['playlists'], {
          ...previous,
          items: previous.items.map((p) =>
            p.id === id ? { ...p, is_active } : p,
          ),
        });
      }
      return { previous };
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(['playlists'], context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['playlists'] });
    },
  });

  // Filter client-side by active tab
  const filteredItems = useMemo(() => {
    if (!data?.items) return [];
    if (activeTab === 'all') return data.items;
    return data.items.filter((p) => p.playlist_type === activeTab);
  }, [data, activeTab]);

  // Bulk toggle all visible playlists
  const bulkToggleMutation = useMutation({
    mutationFn: async (activate: boolean) => {
      const ids = filteredItems.map((p) => p.id);
      await Promise.all(ids.map((id) => apiClient.put(`/playlists/${id}`, { is_active: activate })));
    },
    onMutate: async (activate) => {
      await queryClient.cancelQueries({ queryKey: ['playlists'] });
      const previous = queryClient.getQueryData<PaginatedResponse<Playlist>>(['playlists']);
      if (previous) {
        queryClient.setQueryData<PaginatedResponse<Playlist>>(['playlists'], {
          ...previous,
          items: previous.items.map((p) =>
            filteredItems.some((f) => f.id === p.id) ? { ...p, is_active: activate } : p,
          ),
        });
      }
      return { previous };
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(['playlists'], context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['playlists'] });
    },
  });

  const handleTabChange = useCallback((tab: PlaylistTab) => {
    setActiveTab(tab);
  }, []);

  // ---- Render states ----

  if (isLoading) return <PageLoading />;
  if (isError) return <ErrorState onRetry={() => refetch()} />;
  if (!data) return null;

  return (
    <div className="space-y-6">
      <TabBar activeTab={activeTab} onTabChange={handleTabChange} />

      {/* Spotify connection status banner */}
      {spotifyStatus && (
        <div className={`flex items-center gap-3 px-4 py-2.5 rounded-sm text-sm ${
          spotifyStatus.authorized && !spotifyStatus.token_expired
            ? 'bg-brand-sage/10 border border-brand-sage/20'
            : spotifyStatus.configured
              ? 'bg-yellow-50 border border-yellow-200'
              : 'bg-soft-stone border border-hairline'
        }`}>
          {spotifyStatus.authorized && !spotifyStatus.token_expired ? (
            <CheckCircle2 className="w-4 h-4 text-brand-sage shrink-0" />
          ) : spotifyStatus.configured ? (
            <AlertTriangle className="w-4 h-4 text-yellow-600 shrink-0" />
          ) : (
            <AlertTriangle className="w-4 h-4 text-muted shrink-0" />
          )}
          <span className="flex-1 text-ink">
            {!spotifyStatus.configured
              ? 'Spotify not configured. Add your Client ID and Secret in Settings.'
              : !spotifyStatus.authorized
                ? 'Spotify configured but not authorized. Click "Connect Spotify" in Settings.'
                : spotifyStatus.token_expired
                  ? 'Spotify token expired. Re-authorize in Settings to resume sync.'
                  : spotifyStatus.last_synced_at
                    ? `Spotify connected · last synced ${formatRelativeTime(spotifyStatus.last_synced_at)}`
                    : 'Spotify connected · not yet synced'}
          </span>
          {spotifyStatus.authorized && (
            <Button
              variant="ghost"
              size="sm"
              onClick={handleRefresh}
              loading={refreshing}
              leftIcon={<RefreshCw className="w-3.5 h-3.5" />}
            >
              Refresh
            </Button>
          )}
        </div>
      )}

      {/* Bulk toggle controls */}
      {filteredItems.length > 0 && (
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => bulkToggleMutation.mutate(true)}
            disabled={bulkToggleMutation.isPending}
            className="px-3 py-1.5 text-xs font-medium rounded-sm bg-deep-green text-white hover:bg-deep-green/90 transition-colors disabled:opacity-50 cursor-pointer"
          >
            {bulkToggleMutation.isPending ? 'Working...' : 'Enable All'}
          </button>
          <button
            type="button"
            onClick={() => bulkToggleMutation.mutate(false)}
            disabled={bulkToggleMutation.isPending}
            className="px-3 py-1.5 text-xs font-medium rounded-sm bg-hairline text-ink hover:bg-hairline/80 transition-colors disabled:opacity-50 cursor-pointer"
          >
            {bulkToggleMutation.isPending ? 'Working...' : 'Disable All'}
          </button>
          <span className="text-xs text-muted ml-2">
            {filteredItems.filter((p) => p.is_active).length} of {filteredItems.length} active
          </span>
        </div>
      )}

      {filteredItems.length === 0 ? (
        <EmptyState
          icon={<ListMusic className="w-16 h-16" />}
          title={EMPTY_MESSAGES[activeTab].title}
          description={EMPTY_MESSAGES[activeTab].description}
        />
      ) : isMobile ? (
        <MobilePlaylistList items={filteredItems} toggleMutation={toggleMutation} />
      ) : (
        <DesktopPlaylistList items={filteredItems} toggleMutation={toggleMutation} />
      )}

      {/* Summary footer */}
      {filteredItems.length > 0 && (
        <p className="text-xs text-body-muted text-right">
          {filteredItems.length} playlist{filteredItems.length !== 1 ? 's' : ''}
        </p>
      )}
    </div>
  );
}

// ============================================
// TabBar
// ============================================

function TabBar({
  activeTab,
  onTabChange,
}: {
  activeTab: PlaylistTab;
  onTabChange: (tab: PlaylistTab) => void;
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

// ============================================
// Desktop — Table-style list
// ============================================

type ToggleMutation = UseMutationResult<unknown, Error, { id: string; is_active: boolean }>;

function DesktopPlaylistList({
  items,
  toggleMutation,
}: {
  items: Playlist[];
  toggleMutation: ToggleMutation;
}) {
  return (
    <div className="space-y-2">
      {items.map((playlist) => {
        const isToggling = toggleMutation.isPending && (toggleMutation.variables as { id: string } | undefined)?.id === playlist.id;

        return (
          <Card key={playlist.id} padding="md">
            <div className="flex items-center gap-4">
              {/* Type dot */}
              <span
                className={`flex-shrink-0 w-3 h-3 rounded-full ${TYPE_DOT[playlist.playlist_type]}`}
              />

              {/* Playlist info */}
              <div className="flex-1 min-w-0">
                <p className="font-medium text-ink truncate">{playlist.name}</p>
                <div className="flex items-center gap-2 mt-1 flex-wrap">
                  <PlaylistTypeBadge type={playlist.playlist_type} />
                  {playlist.track_count != null && (
                    <span className="text-xs text-body-muted">
                      {playlist.track_count} track{playlist.track_count !== 1 ? 's' : ''}
                    </span>
                  )}
                  <span className="text-xs text-body-muted">
                    synced {formatRelativeTime(playlist.last_synced_at)}
                  </span>
                </div>
              </div>

              {/* Toggle switch */}
              <div className="flex-shrink-0 flex items-center gap-2">
                {isToggling && (
                  <Loader2 className="w-3.5 h-3.5 animate-spin text-muted" />
                )}
                <button
                  type="button"
                  role="switch"
                  aria-checked={playlist.is_active}
                  aria-label={`${playlist.is_active ? 'Disable' : 'Enable'} playlist ${playlist.name}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    toggleMutation.mutate({ id: playlist.id, is_active: !playlist.is_active });
                  }}
                  disabled={isToggling}
                  className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full transition-colors duration-200 ${
                    playlist.is_active ? 'bg-deep-green' : 'bg-hairline'
                  } ${isToggling ? 'opacity-60 cursor-not-allowed' : ''}`}
                >
                  <span
                    className={`inline-block h-4 w-4 transform rounded-full bg-white shadow-sm transition-transform duration-200 mt-0.5 ${
                      playlist.is_active ? 'translate-x-[18px]' : 'translate-x-0.5'
                    }`}
                  />
                </button>
              </div>
            </div>
          </Card>
        );
      })}
    </div>
  );
}

// ============================================
// Mobile — Card list
// ============================================

function MobilePlaylistList({
  items,
  toggleMutation,
}: {
  items: Playlist[];
  toggleMutation: ToggleMutation;
}) {
  return (
    <div className="space-y-3">
      {items.map((playlist) => {
        const isToggling = toggleMutation.isPending && (toggleMutation.variables as { id: string } | undefined)?.id === playlist.id;

        return (
          <Card key={playlist.id} padding="md">
            <div className="flex flex-col gap-2">
              <div className="flex items-start gap-3">
                {/* Type dot */}
                <span
                  className={`flex-shrink-0 w-3 h-3 rounded-full mt-1.5 ${TYPE_DOT[playlist.playlist_type]}`}
                />

                <div className="flex-1 min-w-0">
                  <p className="font-medium text-ink truncate">{playlist.name}</p>
                  <div className="flex items-center gap-2 mt-1 flex-wrap">
                    <PlaylistTypeBadge type={playlist.playlist_type} />
                    {playlist.track_count != null && (
                      <span className="text-xs text-body-muted">
                        {playlist.track_count} track{playlist.track_count !== 1 ? 's' : ''}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-body-muted mt-1">
                    synced {formatRelativeTime(playlist.last_synced_at)}
                  </p>
                </div>

                {/* Toggle switch */}
                <div className="flex-shrink-0 flex items-center gap-2 mt-0.5">
                  {isToggling && (
                    <Loader2 className="w-3.5 h-3.5 animate-spin text-muted" />
                  )}
                  <button
                    type="button"
                    role="switch"
                    aria-checked={playlist.is_active}
                    aria-label={`${playlist.is_active ? 'Disable' : 'Enable'} playlist ${playlist.name}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleMutation.mutate({ id: playlist.id, is_active: !playlist.is_active });
                    }}
                    disabled={isToggling}
                    className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full transition-colors duration-200 ${
                      playlist.is_active ? 'bg-deep-green' : 'bg-hairline'
                    } ${isToggling ? 'opacity-60 cursor-not-allowed' : ''}`}
                  >
                    <span
                      className={`inline-block h-4 w-4 transform rounded-full bg-white shadow-sm transition-transform duration-200 mt-0.5 ${
                        playlist.is_active ? 'translate-x-[18px]' : 'translate-x-0.5'
                      }`}
                    />
                  </button>
                </div>
              </div>
            </div>
          </Card>
        );
      })}
    </div>
  );
}

// ============================================
// PlaylistTypeBadge
// ============================================

function PlaylistTypeBadge({ type }: { type: Playlist['playlist_type'] }) {
  const config = TYPE_BADGE[type];
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium ${config.bg} ${config.text}`}
    >
      {config.label}
    </span>
  );
}
