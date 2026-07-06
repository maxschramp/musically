// ============================================
// Musically — Artist Detail Page
// Header + bio + albums grid + similar artists + play history
// Route: /artists/:id
// ============================================

import { useState, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Users,
  Music,
  Disc3,
  BarChart3,
  BookOpen,
} from 'lucide-react';
import { Card } from '@/components/shared/Card';
import { EmptyState } from '@/components/shared/EmptyState';
import { ErrorState } from '@/components/shared/ErrorState';
import { PageLoading, LoadingSpinner } from '@/components/shared/LoadingSpinner';
import { useApiQuery } from '@/hooks/useApi';
import { useInfiniteScroll } from '@/hooks/useInfiniteScroll';
import { useIsMobile } from '@/hooks/useMediaQuery';
import { apiClient } from '@/api/client';
import { formatDate, formatNumber, truncate } from '@/utils/format';
import type { Artist, Album } from '@/types';

// ============================================
// Subscribe Toggle (reused pattern from Artists.tsx)
// ============================================

function SubscribeToggle({
  subscribed,
  loading,
  onToggle,
}: {
  subscribed: boolean;
  loading: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={subscribed}
      disabled={loading}
      onClick={onToggle}
      className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full transition-colors duration-200 ${
        loading ? 'opacity-50 cursor-wait' : ''
      } ${subscribed ? 'bg-brand-coral' : 'bg-hairline'}`}
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
// Album Card (reused pattern from Library.tsx)
// ============================================

function ArtistAlbumCard({
  album,
  onClick,
}: {
  album: Album;
  onClick: () => void;
}) {
  const [imgError, setImgError] = useState(false);

  return (
    <Card padding="sm" onClick={onClick}>
      <div className="aspect-square rounded-sm bg-soft-stone flex items-center justify-center mb-3 overflow-hidden relative">
        <img
          src={`/api/albums/${album.id}/artwork`}
          alt={`${album.artist_name} - ${album.title}`}
          className="absolute inset-0 w-full h-full object-cover rounded-sm"
          onError={() => setImgError(true)}
          loading="lazy"
        />
        {imgError && <Disc3 className="w-10 h-10 text-muted" />}
      </div>
      <p className="text-sm font-medium text-ink truncate" title={album.title}>
        {truncate(album.title, 30)}
      </p>
      <p className="text-xs text-muted truncate mt-0.5" title={album.artist_name}>
        {album.artist_name}
      </p>
      {album.track_count > 0 && (
        <p className="text-xs text-muted mt-0.5">
          {album.track_count} track{album.track_count !== 1 ? 's' : ''}
        </p>
      )}
      {album.downloaded_at && (
        <p className="text-xs text-body-muted mt-0.5">{formatDate(album.downloaded_at)}</p>
      )}
    </Card>
  );
}

// ============================================
// Artist Detail Page
// ============================================

export function ArtistDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const isMobile = useIsMobile();

  // --- Fetch artist details ---
  const {
    data: artist,
    isLoading: artistLoading,
    isError: artistError,
    error: artistErr,
    refetch: refetchArtist,
  } = useApiQuery<Artist & {
    bio?: string;
    image_url?: string;
    genres?: string[];
    similar_artists?: { name: string; id: string }[];
    recent_plays?: { track_name: string; played_at: string }[];
  }>(
    ['artist', id],
    `/artists/${id}`,
    undefined,
    { enabled: !!id },
  );

  // --- Subscribe / Unsubscribe mutations ---
  const subscribeMutation = useMutation({
    mutationFn: () => apiClient.post(`/artists/${id}/subscribe`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['artist', id] });
      queryClient.invalidateQueries({ queryKey: ['artists'] });
    },
  });

  const unsubscribeMutation = useMutation({
    mutationFn: () => apiClient.post(`/artists/${id}/unsubscribe`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['artist', id] });
      queryClient.invalidateQueries({ queryKey: ['artists'] });
    },
  });

  const isToggling = subscribeMutation.isPending || unsubscribeMutation.isPending;

  const handleToggle = useCallback(() => {
    if (artist?.subscribed) {
      unsubscribeMutation.mutate();
    } else {
      subscribeMutation.mutate();
    }
  }, [artist?.subscribed, subscribeMutation, unsubscribeMutation]);

  // --- Fetch artist albums (infinite scroll) ---
  // Use artist.name as the filter; include it in the query key so it re-fetches when the artist loads
  const artistName = artist?.name;

  const {
    items: albums,
    isLoading: albumsLoading,
    isLoadingMore: albumsLoadingMore,
    isError: albumsError,
    hasMore,
    loaderRef,
  } = useInfiniteScroll<Album>(
    ['artist-albums', id, artistName],
    '/albums',
    { artist_name: artistName, sort: '-downloaded_at' },
  );

  // --- Derived state ---
  const isLoading = artistLoading;
  const isError = artistError;
  const errorMsg = (artistErr as { message?: string })?.message ?? 'Failed to load artist.';
  const notFound = !isLoading && !isError && !artist;

  // --- Render ---

  // Loading
  if (isLoading) return <PageLoading />;

  // Error
  if (isError) {
    return (
      <div className="space-y-6">
        <Card padding="lg">
          <ErrorState
            title="Failed to Load Artist"
            message={errorMsg}
            onRetry={() => refetchArtist()}
          />
        </Card>
      </div>
    );
  }

  // Not found
  if (notFound || !artist) {
    return (
      <div className="space-y-6">
        <Card padding="lg">
          <EmptyState
            icon={<Users className="w-16 h-16" />}
            title="Artist Not Found"
            description="This artist may have been removed or the ID is invalid."
            actionLabel="Back to Artists"
            onAction={() => navigate('/artists')}
          />
        </Card>
      </div>
    );
  }

  const similarArtists = artist.similar_artists ?? [];
  const recentPlays = artist.recent_plays ?? [];

  return (
    <div className="space-y-8">
      {/* ============================================
          Artist Header
          ============================================ */}
      <div className={`flex gap-6 ${isMobile ? 'flex-col items-center text-center' : 'items-start'}`}>
        {/* Avatar */}
        <div className="shrink-0">
          <div className="w-32 h-32 sm:w-40 sm:h-40 rounded-full bg-soft-stone flex items-center justify-center shadow-md overflow-hidden">
            {artist.image_url ? (
              <img
                src={artist.image_url}
                alt={artist.name}
                className="w-full h-full object-cover"
              />
            ) : (
              <Users className="w-16 h-16 text-muted" />
            )}
          </div>
        </div>

        {/* Info */}
        <div className={`flex-1 min-w-0 ${isMobile ? 'flex flex-col items-center' : ''}`}>
          <h1 className="font-display text-2xl sm:text-3xl text-ink tracking-tight font-semibold mb-3">
            {artist.name}
          </h1>

          {/* Stats row */}
          <div className="flex flex-wrap items-center gap-4 mb-4">
            {artist.total_play_count > 0 && (
              <div className="flex items-center gap-1.5 text-sm text-body-muted">
                <BarChart3 className="w-4 h-4" />
                <span>{formatNumber(artist.total_play_count)} plays</span>
              </div>
            )}
            <div className="flex items-center gap-1.5 text-sm text-body-muted">
              <Music className="w-4 h-4" />
              <span>
                {artist.albums_in_library}{' '}
                {artist.albums_in_library === 1 ? 'album' : 'albums'} in library
              </span>
            </div>
          </div>

          {/* Subscribe toggle */}
          <div className="flex items-center gap-3">
            <SubscribeToggle
              subscribed={artist.subscribed}
              loading={isToggling}
              onToggle={handleToggle}
            />
            <span className="text-sm text-body-muted">
              {artist.subscribed ? 'Subscribed' : 'Not subscribed'}
            </span>
            {artist.subscription_source && (
              <span className="text-xs text-muted px-2 py-0.5 rounded-full bg-soft-stone">
                via {artist.subscription_source}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* ============================================
          Bio Section
          ============================================ */}
      {artist.bio && (
        <Card padding="lg">
          <h2 className="font-display text-lg text-ink tracking-tight mb-3 flex items-center gap-2">
            <BookOpen className="w-5 h-5 text-muted" />
            About
          </h2>
          <p className="text-sm text-body-muted leading-relaxed whitespace-pre-line">
            {artist.bio}
          </p>
          {artist.genres && artist.genres.length > 0 && (
            <div className="flex flex-wrap gap-2 mt-3">
              {artist.genres.map((genre) => (
                <span
                  key={genre}
                  className="px-2.5 py-0.5 rounded-pill text-xs font-medium bg-brand-purple/10 text-brand-purple"
                >
                  {genre}
                </span>
              ))}
            </div>
          )}
        </Card>
      )}

      {/* ============================================
          Albums in Library
          ============================================ */}
      <div>
        <h2 className="font-display text-lg text-ink tracking-tight mb-4">
          Albums in Library
          {albums.length > 0 && (
            <span className="text-sm text-body-muted ml-2 font-normal">
              ({albums.length} album{albums.length !== 1 ? 's' : ''})
            </span>
          )}
        </h2>

        {/* Albums loading */}
        {albumsLoading && (
          <Card padding="lg">
            <LoadingSpinner size="lg" label="Loading albums…" className="py-16" />
          </Card>
        )}

        {/* Albums error */}
        {albumsError && !albumsLoading && (
          <Card padding="lg">
            <ErrorState
              title="Failed to Load Albums"
              message="Could not load albums for this artist."
              onRetry={() => queryClient.invalidateQueries({ queryKey: ['artist-albums', id] })}
            />
          </Card>
        )}

        {/* Empty albums */}
        {!albumsLoading && !albumsError && albums.length === 0 && (
          <Card padding="lg">
            <EmptyState
              icon={<Disc3 className="w-16 h-16" />}
              title="No albums in library"
              description={`${artist.name} doesn't have any albums in your library yet.`}
            />
          </Card>
        )}

        {/* Albums grid */}
        {!albumsLoading && !albumsError && albums.length > 0 && (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4">
              {albums.map((album) => (
                <ArtistAlbumCard
                  key={album.id}
                  album={album}
                  onClick={() => navigate(`/library/${album.id}`)}
                />
              ))}
            </div>

            {/* Infinite scroll sentinel */}
            {hasMore && (
              <div ref={loaderRef} className="py-4 flex justify-center">
                {albumsLoadingMore ? <LoadingSpinner size="sm" /> : null}
              </div>
            )}
          </>
        )}
      </div>

      {/* ============================================
          Similar Artists
          ============================================ */}
      {similarArtists.length > 0 && (
        <Card padding="lg">
          <h2 className="font-display text-lg text-ink tracking-tight mb-4">
            Similar Artists
          </h2>
          <div className="flex flex-wrap gap-2">
            {similarArtists.map((sa) => (
              <button
                key={sa.id}
                type="button"
                onClick={() => navigate(`/artists/${sa.id}`)}
                className="px-4 py-2 rounded-pill bg-soft-stone hover:bg-hairline text-sm text-ink font-medium transition-colors cursor-pointer"
              >
                {sa.name}
              </button>
            ))}
          </div>
        </Card>
      )}

      {/* ============================================
          Recent Plays
          ============================================ */}
      {recentPlays.length > 0 && (
        <Card padding="lg">
          <h2 className="font-display text-lg text-ink tracking-tight mb-4">
            Recent Plays
          </h2>
          <div className="space-y-2">
            {recentPlays.map((play, i) => (
              <div
                key={i}
                className="flex items-center justify-between py-2 border-b border-card-border last:border-0"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <Music className="w-4 h-4 text-muted shrink-0" />
                  <p className="text-sm text-ink truncate">{play.track_name}</p>
                </div>
                <p className="text-xs text-muted shrink-0 ml-3">{formatDate(play.played_at)}</p>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
