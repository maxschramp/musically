// ============================================
// Musically — Artists Page
// Artist list with subscribe toggles and search
// ============================================

import { useState, useEffect, useCallback } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Users, Search, ListMusic, Scan } from 'lucide-react';
import { Card } from '@/components/shared/Card';
import { EmptyState } from '@/components/shared/EmptyState';
import { ErrorState } from '@/components/shared/ErrorState';
import { LoadingSpinner } from '@/components/shared/LoadingSpinner';
import { Button } from '@/components/shared/Button';
import { useInfiniteScroll } from '@/hooks/useInfiniteScroll';
import { apiClient } from '@/api/client';
import { formatNumber } from '@/utils/format';
import type { Artist } from '@/types';

// ============================================
// Subscribe Toggle
// ============================================

interface SubscribeToggleProps {
  subscribed: boolean;
  loading: boolean;
  onToggle: () => void;
}

function SubscribeToggle({ subscribed, loading, onToggle }: SubscribeToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={subscribed}
      disabled={loading}
      onClick={onToggle}
      className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full transition-colors duration-200 ${
        loading ? 'opacity-50 cursor-wait' : ''
      } ${subscribed ? 'bg-coral' : 'bg-hairline'}`}
    >
      <span
        className={`inline-block h-5 w-5 transform rounded-full bg-white shadow-sm transition-transform duration-200 mt-0.5 ${
          subscribed ? 'translate-x-5.5' : 'translate-x-0.5'
        }`}
      />
    </button>
  );
}

// ============================================
// Artist Row
// ============================================

interface ArtistRowProps {
  artist: Artist;
  onSubscriptionChanged: () => void;
}

function ArtistRow({ artist, onSubscriptionChanged }: ArtistRowProps) {
  const subscribeMutation = useMutation({
    mutationFn: () => apiClient.post<Artist>(`/artists/${artist.id}/subscribe`),
    onSuccess: onSubscriptionChanged,
  });

  const unsubscribeMutation = useMutation({
    mutationFn: () => apiClient.post<Artist>(`/artists/${artist.id}/unsubscribe`),
    onSuccess: onSubscriptionChanged,
  });

  const isToggling = subscribeMutation.isPending || unsubscribeMutation.isPending;

  const handleToggle = useCallback(() => {
    if (artist.subscribed) {
      unsubscribeMutation.mutate();
    } else {
      subscribeMutation.mutate();
    }
  }, [artist.subscribed, subscribeMutation, unsubscribeMutation]);

  return (
    <div className="flex items-center gap-4 py-3 px-4 rounded-sm hover:bg-soft-stone/50 transition-colors">
      {/* Avatar placeholder */}
      <div className="w-10 h-10 rounded-full bg-soft-stone flex items-center justify-center shrink-0">
        <Users className="w-5 h-5 text-muted" />
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-ink truncate">
          {artist.name}
        </p>
        <p className="text-xs text-body-muted mt-0.5">
          {formatNumber(artist.total_play_count)} plays
          {' · '}
          {artist.albums_in_library} {artist.albums_in_library === 1 ? 'album' : 'albums'}{' '}
          in library
        </p>
      </div>

      {/* Toggle */}
      <SubscribeToggle
        subscribed={artist.subscribed}
        loading={isToggling}
        onToggle={handleToggle}
      />
    </div>
  );
}

// ============================================
// Auto-Follow from Library Button
// ============================================

interface AutoFollowProps {
  onComplete: () => void;
}

function AutoFollowFromLibrary({ onComplete }: AutoFollowProps) {
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const autoFollowMutation = useMutation({
    mutationFn: () => apiClient.post<{ subscribed_count: number; message: string }>('/artists/auto-follow'),
    onSuccess: (data) => {
      setToastMessage(data.message || `Subscribed to ${data.subscribed_count} new artists from your library`);
      onComplete();
      // Clear toast after 5 seconds
      setTimeout(() => setToastMessage(null), 5000);
    },
  });

  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        leftIcon={<Scan className="w-4 h-4" />}
        onClick={() => autoFollowMutation.mutate()}
        loading={autoFollowMutation.isPending}
        disabled={autoFollowMutation.isPending}
      >
        Auto-Follow from Library
      </Button>

      {/* Toast notification */}
      {toastMessage && (
        <div className="fixed bottom-20 left-1/2 -translate-x-1/2 z-50 px-4 py-3 rounded-sm bg-deep-green text-white text-sm shadow-lg animate-[fadeIn_0.3s_ease-out]">
          {toastMessage}
        </div>
      )}
    </>
  );
}

// ============================================
// Artists Page
// ============================================

export function Artists() {
  const queryClient = useQueryClient();

  const [searchInput, setSearchInput] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [subscribedFilter, setSubscribedFilter] = useState(false);

  // Debounce search input by 300ms
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchInput);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

  const {
    items: artists,
    isLoading,
    isLoadingMore,
    isError,
    error,
    hasMore,
    loaderRef,
    refetch,
    reset,
  } = useInfiniteScroll<Artist>(
    ['artists', debouncedSearch, subscribedFilter],
    '/artists',
    {
      search: debouncedSearch || undefined,
      subscribed: subscribedFilter || undefined,
    },
  );

  // Reset infinite scroll when search or filter changes
  useEffect(() => {
    reset();
  }, [debouncedSearch, subscribedFilter, reset]);

  const errorMessage = (error as { message?: string })?.message ?? 'Failed to load artists.';

  const handleSubscriptionChanged = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['artists'] });
  }, [queryClient]);

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-display text-xl text-ink tracking-tight">
            Artists
          </h2>
          <p className="text-sm text-body-muted mt-1">
            Manage your subscribed artists and browse their releases.
          </p>
        </div>
      </div>

      {/* Auto-Follow Button */}
      <AutoFollowFromLibrary onComplete={handleSubscriptionChanged} />

      {/* Search + Filter Bar */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" />
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search artists…"
            className="w-full pl-10 pr-4 py-2.5 rounded-sm border border-hairline bg-canvas text-sm text-ink placeholder:text-muted focus:outline-none focus:border-form-focus focus:ring-1 focus:ring-form-focus transition-colors"
          />
        </div>

        {/* Subscribed filter toggle */}
        <button
          type="button"
          onClick={() => {
            setSubscribedFilter(!subscribedFilter);
          }}
          className={`inline-flex items-center gap-2 px-4 py-2.5 rounded-pill text-sm font-medium transition-colors duration-150 cursor-pointer ${
            subscribedFilter
              ? 'bg-coral text-white'
              : 'bg-soft-stone text-ink hover:bg-hairline'
          }`}
        >
          <Users className="w-4 h-4" />
          {subscribedFilter ? 'Subscribed' : 'All Artists'}
        </button>
      </div>

      {/* Loading State */}
      {isLoading && (
        <Card padding="lg">
          <LoadingSpinner size="lg" label="Loading artists…" className="py-16" />
        </Card>
      )}

      {/* Error State */}
      {isError && !isLoading && (
        <Card padding="lg">
          <ErrorState
            title="Failed to Load Artists"
            message={errorMessage}
            onRetry={() => refetch()}
          />
        </Card>
      )}

      {/* Empty State */}
      {!isLoading && !isError && artists.length === 0 && (
        <Card padding="lg">
          <EmptyState
            icon={<ListMusic className="w-16 h-16" />}
            title={
              debouncedSearch
                ? 'No artists found'
                : subscribedFilter
                  ? 'No subscribed artists'
                  : 'No artists yet'
            }
            description={
              debouncedSearch
                ? `No artists matching "${debouncedSearch}".`
                : subscribedFilter
                  ? 'No artists are currently subscribed. Artists are auto-subscribed based on your listening history and rule engine thresholds.'
                  : 'Artists will appear here as they are discovered through your listening history and rule engine processing.'
            }
          />
        </Card>
      )}

      {/* Artist List */}
      {!isLoading && !isError && artists.length > 0 && (
        <>
          <Card padding="none">
            <div className="divide-y divide-card-border">
              {artists.map((artist) => (
                <ArtistRow
                  key={artist.id}
                  artist={artist}
                  onSubscriptionChanged={handleSubscriptionChanged}
                />
              ))}
            </div>
          </Card>

          {/* Infinite scroll sentinel */}
          {hasMore && (
            <div ref={loaderRef} className="py-4 flex justify-center">
              {isLoadingMore ? <LoadingSpinner size="sm" /> : null}
            </div>
          )}
        </>
      )}
    </div>
  );
}
