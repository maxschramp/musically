// ============================================
// Musically — Discover Page
// Search external sources and add albums/artists
// ============================================

import { useState, useCallback } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Search, Disc3, Plus, Music, RotateCw, Check, Library } from 'lucide-react';
import { Card } from '@/components/shared/Card';
import { EmptyState } from '@/components/shared/EmptyState';
import { ErrorState } from '@/components/shared/ErrorState';
import { Button } from '@/components/shared/Button';
import { useApiQuery } from '@/hooks/useApi';
import { apiClient } from '@/api/client';
import FollowButton from '@/components/shared/FollowButton';
import type { SearchResponse, SearchSource, SearchType } from '@/types';

// ============================================
// Source & Type Config
// ============================================

const SOURCES: { key: SearchSource; label: string; badgeClass: string }[] = [
  { key: 'musicbrainz', label: 'MusicBrainz', badgeClass: 'bg-blue-100 text-blue-700' },
  { key: 'spotify', label: 'Spotify', badgeClass: 'bg-green-100 text-green-700' },
  { key: 'qobuz', label: 'Qobuz', badgeClass: 'bg-yellow-100 text-yellow-700' },
];

const TYPES: { key: SearchType; label: string }[] = [
  { key: 'album', label: 'Albums' },
  { key: 'artist', label: 'Artists' },
];

// ============================================
// Queue Album Button
// ============================================

function QueueAlbumButton({
  artistName,
  albumTitle,
  inQueue = false,
  inLibrary = false,
}: {
  artistName: string;
  albumTitle?: string;
  inQueue?: boolean;
  inLibrary?: boolean;
}) {
  const queryClient = useQueryClient();
  const [justQueued, setJustQueued] = useState(false);

  const queueMutation = useMutation({
    mutationFn: () =>
      apiClient.post('/queue', {
        artist_name: artistName,
        title: albumTitle,
        queue_type: 'manual',
        reason: 'Manual add',
      }),
    onSuccess: () => {
      // Flash the "Queued" state before invalidation refreshes
      setJustQueued(true);
      // Invalidate queue and ALL search queries so results reflect the new state
      queryClient.invalidateQueries({ queryKey: ['queue'] });
      queryClient.invalidateQueries({ queryKey: ['search'] });
      // Reset the flash after a brief delay
      setTimeout(() => setJustQueued(false), 1500);
    },
  });

  // Determine button state
  const isInLibrary = inLibrary;
  const isInQueue = inQueue || justQueued;
  const isPending = queueMutation.isPending;

  if (isInLibrary) {
    return (
      <Button
        variant="ghost"
        size="sm"
        leftIcon={<Library className="w-3.5 h-3.5" />}
        disabled
      >
        In Library
      </Button>
    );
  }

  if (isInQueue) {
    return (
      <Button
        variant="ghost"
        size="sm"
        leftIcon={<Check className="w-3.5 h-3.5" />}
        disabled
        className={justQueued ? 'text-deep-green border border-deep-green/30' : ''}
      >
        Queued
      </Button>
    );
  }

  return (
    <Button
      variant="primary"
      size="sm"
      leftIcon={<Plus className="w-3.5 h-3.5" />}
      onClick={(e) => {
        e.stopPropagation();
        queueMutation.mutate();
      }}
      loading={isPending}
      disabled={isPending}
    >
      Queue
    </Button>
  );
}

// ============================================
// Source Badge
// ============================================

function SourceBadge({ source }: { source: SearchSource }) {
  const config = SOURCES.find((s) => s.key === source);
  if (!config) return null;

  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${config.badgeClass}`}>
      {config.label}
    </span>
  );
}

// ============================================
// Skeleton Card
// ============================================

function SkeletonCard() {
  return (
    <div className="flex items-center gap-4 py-3 px-4 animate-pulse">
      <div className="w-12 h-12 rounded-sm bg-hairline shrink-0" />
      <div className="flex-1 space-y-2">
        <div className="h-4 bg-hairline rounded w-2/3" />
        <div className="h-3 bg-hairline rounded w-1/3" />
      </div>
      <div className="flex items-center gap-2">
        <div className="h-5 w-5 bg-hairline rounded" />
        <div className="h-8 w-16 bg-hairline rounded" />
      </div>
    </div>
  );
}

// ============================================
// Discover Page
// ============================================

export function Discover() {
  const [searchInput, setSearchInput] = useState('');
  const [submittedQuery, setSubmittedQuery] = useState('');
  const [sources, setSources] = useState<SearchSource[]>(['musicbrainz', 'spotify', 'qobuz']);
  const [searchType, setSearchType] = useState<SearchType>('album');

  // Toggle a source on/off
  const toggleSource = useCallback((source: SearchSource) => {
    setSources((prev) => {
      if (prev.includes(source)) {
        // Don't allow deselecting the last source
        if (prev.length <= 1) return prev;
        return prev.filter((s) => s !== source);
      }
      return [...prev, source];
    });
  }, []);

  // Execute search
  const handleSearch = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (!searchInput.trim()) return;
      setSubmittedQuery(searchInput.trim());
    },
    [searchInput],
  );

  // API query (only when submittedQuery is set)
  const {
    data,
    isLoading,
    isError,
    error,
    refetch,
  } = useApiQuery<SearchResponse>(
    ['search', submittedQuery, searchType, sources.join(',')],
    '/search',
    {
      q: submittedQuery || undefined,
      type: searchType || undefined,
      source: sources.join(','),
    },
    {
      enabled: !!submittedQuery, // Only fetch when query is submitted
    },
  );

  const results = data?.results ?? [];
  const errorMessage = error?.message ?? 'Search failed. Please try again.';

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div>
        <h2 className="font-display text-xl text-ink tracking-tight">
          Discover
        </h2>
        <p className="text-sm text-body-muted mt-1">
          Search external sources for new music to add to your library.
        </p>
      </div>

      {/* Search Form */}
      <form onSubmit={handleSearch} className="space-y-4">
        {/* Search input */}
        <div className="relative">
          <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-muted" />
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search for artists or albums…"
            className="w-full pl-12 pr-24 py-3 rounded-sm border border-hairline bg-canvas text-base text-ink placeholder:text-muted focus:outline-none focus:border-form-focus focus:ring-1 focus:ring-form-focus transition-colors"
          />
          <Button
            type="submit"
            variant="accent"
            size="md"
            disabled={!searchInput.trim() || isLoading}
            loading={isLoading}
            className="absolute right-2 top-1/2 -translate-y-1/2"
          >
            Search
          </Button>
        </div>

        {/* Source Toggle Chips */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted mr-1">Sources:</span>
          {SOURCES.map(({ key, label }) => {
            const active = sources.includes(key);
            return (
              <button
                key={key}
                type="button"
                onClick={() => toggleSource(key)}
                className={`px-3 py-1.5 rounded-pill text-xs font-medium transition-colors duration-150 cursor-pointer ${
                  active
                    ? 'bg-ink text-white'
                    : 'bg-soft-stone text-muted hover:bg-hairline'
                }`}
              >
                {label}
              </button>
            );
          })}
        </div>

        {/* Type Toggle */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted mr-1">Type:</span>
          {TYPES.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              onClick={() => setSearchType(key)}
              className={`px-4 py-1.5 rounded-pill text-sm font-medium transition-colors duration-150 cursor-pointer ${
                searchType === key
                  ? 'bg-coral text-white'
                  : 'bg-soft-stone text-ink hover:bg-hairline'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </form>

      {/* Results */}
      {!submittedQuery && (
        <Card padding="lg">
          <EmptyState
            icon={<Music className="w-16 h-16" />}
            title="Search for Music"
            description="Search for artists or albums to discover new music. Results come from MusicBrainz, Spotify, and Qobuz."
          />
        </Card>
      )}

      {/* Loading State */}
      {submittedQuery && isLoading && (
        <Card padding="none">
          <div className="divide-y divide-card-border">
            {Array.from({ length: 5 }).map((_, i) => (
              <SkeletonCard key={i} />
            ))}
          </div>
        </Card>
      )}

      {/* Error State */}
      {submittedQuery && isError && !isLoading && (
        <Card padding="lg">
          <ErrorState
            title="Search Failed"
            message={errorMessage}
            onRetry={() => refetch()}
          />
        </Card>
      )}

      {/* Empty Results */}
      {submittedQuery && !isLoading && !isError && results.length === 0 && (
        <Card padding="lg">
          <EmptyState
            icon={<Search className="w-16 h-16" />}
            title="No Results"
            description={`No ${searchType === 'artist' ? 'artists' : 'albums'} found for "${submittedQuery}". Try a different search term or source.`}
          />
        </Card>
      )}

      {/* Results List */}
      {submittedQuery && !isLoading && !isError && results.length > 0 && (
        <Card padding="none">
          <div className="px-4 py-3 border-b border-card-border flex items-center justify-between">
            <p className="text-sm text-muted">
              {results.length} result{results.length !== 1 ? 's' : ''} for &ldquo;{submittedQuery}&rdquo;
            </p>
            <Button
              variant="ghost"
              size="sm"
              leftIcon={<RotateCw className="w-3.5 h-3.5" />}
              onClick={() => refetch()}
            >
              Refresh
            </Button>
          </div>
          <div className="divide-y divide-card-border">
            {results.map((result, idx) => (
              <div
                key={`${result.source}-${result.artist_name}-${result.title ?? ''}-${idx}`}
                className="flex items-center gap-4 py-3 px-4 hover:bg-soft-stone/30 transition-colors"
              >
                {/* Art placeholder */}
                <div className="w-12 h-12 rounded-sm bg-soft-stone flex items-center justify-center shrink-0">
                  <Disc3 className="w-6 h-6 text-muted" />
                </div>

                {/* Info */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-medium text-ink truncate">
                      {result.artist_name}
                      {result.title && (
                        <span className="text-muted font-normal"> — {result.title}</span>
                      )}
                    </p>
                    <SourceBadge source={result.source} />
                    {result.in_library && (
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-deep-green text-white">
                        in library
                      </span>
                    )}
                    {result.in_queue && !result.in_library && (
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-action-blue text-white">
                        in queue
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-body-muted mt-0.5 capitalize">
                    {result.type}
                  </p>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-2 shrink-0">
                  <FollowButton artistName={result.artist_name} />
                  {result.type === 'album' && result.title && (
                    <QueueAlbumButton
                      artistName={result.artist_name}
                      albumTitle={result.title}
                      inQueue={result.in_queue}
                      inLibrary={result.in_library}
                    />
                  )}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
