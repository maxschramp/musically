// ============================================
// Musically — Album Detail Page
// Hero + metadata + track listing + MusicBrainz comparison + actions
// Route: /library/:id
// ============================================

import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Disc3,
  Calendar,
  Disc,
  Music,
  HardDrive,
  ExternalLink,
  Trash2,
  User,
  Download,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Info,
} from 'lucide-react';
import { Card } from '@/components/shared/Card';
import { Button } from '@/components/shared/Button';
import { Badge } from '@/components/shared/Badge';
import { EmptyState } from '@/components/shared/EmptyState';
import { ErrorState } from '@/components/shared/ErrorState';
import { PageLoading } from '@/components/shared/LoadingSpinner';
import { useApiQuery } from '@/hooks/useApi';
import { useIsMobile } from '@/hooks/useMediaQuery';
import { apiClient } from '@/api/client';
import { formatDate, formatNumber } from '@/utils/format';
import type {
  Album,
  AlbumTracksResponse,
  MusicBrainzAlbumResponse,
  TrackComparisonRow,
} from '@/types';

// ============================================
// Track Comparison Helpers (shared logic with Library.tsx)
// ============================================

function normalizeFilename(filename: string): string {
  let name = filename.replace(/\.[^.]+$/, '');
  name = name.replace(/[_-]+/g, ' ');
  name = name.replace(/^\d{1,3}[\s.\-)]*\s*/, '');
  name = name.replace(/\s+/g, ' ');
  return name.trim();
}

function compareTracks(
  diskTracks: { filename: string; size: number; format: string; path: string }[],
  mbTracks: { position: number; title: string; length_ms: number; mbid: string }[],
): TrackComparisonRow[] {
  const rows: TrackComparisonRow[] = [];
  const usedDiskIndices = new Set<number>();
  const normalizedDisks = diskTracks.map((dt) => normalizeFilename(dt.filename).toLowerCase());

  for (const mbTrack of mbTracks) {
    const mbTitleLower = mbTrack.title.toLowerCase();
    const matchIdx = normalizedDisks.findIndex(
      (norm, i) => !usedDiskIndices.has(i) && norm.includes(mbTitleLower),
    );

    if (matchIdx >= 0) {
      usedDiskIndices.add(matchIdx);
      rows.push({
        diskTrack: diskTracks[matchIdx] ?? null,
        mbTrack,
        matchType: 'matched',
      });
    } else {
      rows.push({
        diskTrack: null,
        mbTrack,
        matchType: 'mb-only',
      });
    }
  }

  for (let i = 0; i < diskTracks.length; i++) {
    if (!usedDiskIndices.has(i)) {
      rows.push({
        diskTrack: diskTracks[i] ?? null,
        mbTrack: null,
        matchType: 'disk-only',
      });
    }
  }

  return rows;
}

function formatMs(ms: number): string {
  const totalSec = Math.round(ms / 1000);
  const mins = Math.floor(totalSec / 60);
  const secs = totalSec % 60;
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

// ============================================
// Delete Confirm Dialog (inline)
// ============================================

function DeleteConfirmDialog({
  open,
  albumTitle,
  loading,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  albumTitle: string;
  loading: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="fixed inset-0 bg-black/50 backdrop-blur-sm" onClick={onCancel} />
      <div className="relative bg-canvas border border-card-border rounded-md shadow-xl p-6 max-w-sm w-full">
        <div className="flex items-start gap-3 mb-4">
          <div className="icon-chip icon-chip-coral shrink-0 mt-0.5">
            <AlertTriangle className="w-5 h-5" />
          </div>
          <div>
            <h3 className="font-display text-lg text-ink">Delete Album</h3>
            <p className="text-sm text-body-muted mt-1">
              Are you sure you want to delete <strong>{albumTitle}</strong>? This will remove all
              files from disk. This action cannot be undone.
            </p>
          </div>
        </div>
        <div className="flex justify-end gap-3">
          <Button variant="ghost" size="sm" onClick={onCancel} disabled={loading}>
            Cancel
          </Button>
          <Button
            variant="danger"
            size="sm"
            onClick={onConfirm}
            loading={loading}
            leftIcon={<Trash2 className="w-4 h-4" />}
          >
            Delete
          </Button>
        </div>
      </div>
    </div>
  );
}

// ============================================
// Album Detail Page
// ============================================

export function AlbumDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const isMobile = useIsMobile();
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [imgError, setImgError] = useState(false);
  const [queueFlash, setQueueFlash] = useState<string | null>(null);

  // --- Fetch album details ---
  const {
    data: album,
    isLoading: albumLoading,
    isError: albumError,
    error: albumErr,
  } = useApiQuery<Album & { genre?: string; label?: string; total_size?: number; format?: string; year?: number; bitrate?: string }>(
    ['album', id],
    `/albums/${id}`,
    undefined,
    { enabled: !!id },
  );

  // --- Fetch tracks ---
  const {
    data: tracksData,
    isLoading: tracksLoading,
    isError: tracksError,
    refetch: refetchTracks,
  } = useApiQuery<AlbumTracksResponse>(
    ['album-tracks', id],
    `/albums/${id}/tracks`,
    undefined,
    { enabled: !!id },
  );

  // --- Fetch MusicBrainz comparison ---
  const {
    data: mbData,
    isLoading: mbLoading,
    isError: mbError,
    refetch: refetchMb,
  } = useApiQuery<MusicBrainzAlbumResponse>(
    ['album-musicbrainz', id],
    `/albums/${id}/musicbrainz`,
    undefined,
    { enabled: !!id },
  );

  // --- Look up artist ID from name (needed for "View Artist" navigation) ---
  const { data: artistLookup } = useApiQuery<{ found: boolean; artist_id: string | null; artist_name: string; subscribed: boolean }>(
    ['artist-lookup', album?.artist_name],
    '/artists/lookup',
    { artist_name: album?.artist_name ?? '' },
    { enabled: !!album?.artist_name },
  );
  const artistId = artistLookup?.artist_id;

  // --- Delete mutation ---
  const deleteMutation = useMutation({
    mutationFn: () => apiClient.delete(`/albums/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['albums'] });
      queryClient.invalidateQueries({ queryKey: ['album', id] });
      navigate('/library', { replace: true });
    },
  });

  // --- Queue for re-download (missing tracks) ---
  const queueMutation = useMutation({
    mutationFn: () =>
      apiClient.post('/queue', {
        artist_name: album?.artist_name ?? '',
        title: album?.title ?? '',
        queue_type: 'manual',
        reason: 'Missing tracks',
      }),
    onSuccess: () => {
      setQueueFlash('Album queued for re-download!');
      setTimeout(() => setQueueFlash(null), 3000);
    },
    onError: (err: { message?: string }) => {
      setQueueFlash(`Failed to queue: ${err.message || 'Unknown error'}`);
      setTimeout(() => setQueueFlash(null), 4000);
    },
  });

  // --- Derived state ---
  const isLoading = albumLoading;
  const isError = albumError;
  const errorMsg = (albumErr as { message?: string })?.message ?? 'Failed to load album.';
  const notFound = !isLoading && !isError && !album;

  const detailLoading = tracksLoading || mbLoading;
  const detailError = tracksError || mbError;

  const comparisonRows: TrackComparisonRow[] =
    tracksData && mbData
      ? compareTracks(tracksData.tracks, mbData.tracks)
      : [];

  const missingTracks = comparisonRows.filter((r) => r.matchType === 'mb-only');
  const hasMBData = mbData?.found && mbData.tracks.length > 0;
  const diskTracks = tracksData?.tracks ?? [];
  const totalDiskSize = diskTracks.reduce((sum, t) => sum + (t.size ?? 0), 0);

  // --- Render ---

  // Loading
  if (isLoading) return <PageLoading />;

  // Error
  if (isError) {
    return (
      <div className="space-y-6">
        <Card padding="lg">
          <ErrorState
            title="Failed to Load Album"
            message={errorMsg}
            onRetry={() => {
              queryClient.invalidateQueries({ queryKey: ['album', id] });
            }}
          />
        </Card>
      </div>
    );
  }

  // Not found
  if (notFound || !album) {
    return (
      <div className="space-y-6">
        <Card padding="lg">
          <EmptyState
            icon={<Disc3 className="w-16 h-16" />}
            title="Album Not Found"
            description="This album may have been deleted or the ID is invalid."
            actionLabel="Back to Library"
            onAction={() => navigate('/library')}
          />
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* ============================================
          Hero Section
          ============================================ */}
      <div className={`flex gap-6 ${isMobile ? 'flex-col items-center text-center' : 'items-start'}`}>
        {/* Album Artwork */}
        <div className="shrink-0">
          <div className="w-48 h-48 sm:w-64 sm:h-64 rounded-sm bg-soft-stone overflow-hidden shadow-md">
            <img
              src={`/api/albums/${id}/artwork`}
              alt={`${album.artist_name} - ${album.title}`}
              className="w-full h-full object-cover"
              onError={() => setImgError(true)}
            />
            {imgError && (
              <div className="w-full h-full flex items-center justify-center">
                <Disc3 className="w-16 h-16 text-muted" />
              </div>
            )}
          </div>
        </div>

        {/* Hero Info */}
        <div className={`flex-1 min-w-0 ${isMobile ? 'flex flex-col items-center' : ''}`}>
          <p className="text-sm text-body-muted mb-1">{album.artist_name}</p>
          <h1 className="font-display text-2xl sm:text-3xl text-ink tracking-tight font-semibold mb-3">
            {album.title}
          </h1>

          {/* Badges row */}
          <div className="flex flex-wrap items-center gap-2 mb-4">
            <Badge status={album.status} />
            {album.year != null && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-soft-stone text-ink">
                <Calendar className="w-3 h-3" />
                {String(album.year)}
              </span>
            )}
            {album.track_count > 0 && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-soft-stone text-ink">
                <Music className="w-3 h-3" />
                {album.track_count} track{album.track_count !== 1 ? 's' : ''}
              </span>
            )}
          </div>

          {/* Action Bar */}
          <div className="flex flex-wrap gap-2">
            <Button
              variant="ghost"
              size="sm"
              leftIcon={<User className="w-4 h-4" />}
              onClick={() => {
                if (artistId) {
                  navigate(`/artists/${artistId}`);
                }
              }}
              disabled={!artistId}
              title={artistId ? `View ${album.artist_name}` : 'Artist not found in database'}
            >
              View Artist
            </Button>
            {album.album_mbid && (
              <Button
                variant="ghost"
                size="sm"
                leftIcon={<ExternalLink className="w-4 h-4" />}
                onClick={() => window.open(`https://musicbrainz.org/release/${album.album_mbid}`, '_blank')}
              >
                MusicBrainz
              </Button>
            )}
            <Button
              variant="ghost"
              size="sm"
              leftIcon={<Trash2 className="w-4 h-4" />}
              onClick={() => setDeleteOpen(true)}
              className="text-red-600 hover:text-red-700 hover:bg-red-50"
            >
              Delete
            </Button>
          </div>
        </div>
      </div>

      {/* ============================================
          Metadata Panel
          ============================================ */}
      <Card padding="lg">
        <h2 className="font-display text-lg text-ink tracking-tight mb-4">Album Info</h2>
        <div className={`grid gap-4 ${isMobile ? 'grid-cols-2' : 'grid-cols-2 sm:grid-cols-3 md:grid-cols-4'}`}>
          {album.artist_name && (
            <MetaItem icon={<User className="w-4 h-4" />} label="Artist" value={album.artist_name} />
          )}
          {album.genre != null && (
            <MetaItem icon={<Disc className="w-4 h-4" />} label="Genre" value={String(album.genre)} />
          )}
          {album.label != null && (
            <MetaItem icon={<Info className="w-4 h-4" />} label="Label" value={String(album.label)} />
          )}
          {album.track_count > 0 && (
            <MetaItem icon={<Music className="w-4 h-4" />} label="Tracks" value={String(album.track_count)} />
          )}
          {totalDiskSize > 0 && (
            <MetaItem icon={<HardDrive className="w-4 h-4" />} label="Total Size" value={formatFileSize(totalDiskSize)} />
          )}
          {album.format != null && (
            <MetaItem icon={<Disc className="w-4 h-4" />} label="Format" value={String(album.format)} />
          )}
          {album.bitrate != null && (
            <MetaItem icon={<Music className="w-4 h-4" />} label="Bitrate" value={String(album.bitrate)} />
          )}
          {album.downloaded_at && (
            <MetaItem icon={<Calendar className="w-4 h-4" />} label="Downloaded" value={formatDate(album.downloaded_at)} />
          )}
          {album.play_count > 0 && (
            <MetaItem icon={<Music className="w-4 h-4" />} label="Plays" value={formatNumber(album.play_count)} />
          )}
        </div>
      </Card>

      {/* ============================================
          Track Listing
          ============================================ */}
      <Card padding="lg">
        <h2 className="font-display text-lg text-ink tracking-tight mb-4">
          Track Listing
          {diskTracks.length > 0 && (
            <span className="text-sm text-body-muted ml-2 font-normal">
              ({diskTracks.length} file{diskTracks.length !== 1 ? 's' : ''})
            </span>
          )}
        </h2>

        {/* Tracks loading */}
        {tracksLoading && (
          <div className="py-8">
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="flex items-center gap-4 py-2 animate-pulse">
                  <div className="w-6 h-4 bg-soft-stone rounded" />
                  <div className="flex-1 h-4 bg-soft-stone rounded" />
                  <div className="w-20 h-4 bg-soft-stone rounded" />
                  <div className="w-16 h-4 bg-soft-stone rounded" />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Tracks error */}
        {tracksError && !tracksLoading && (
          <p className="text-sm text-coral py-4">
            Failed to load tracks.{' '}
            <button
              type="button"
              className="underline hover:text-red-800"
              onClick={() => refetchTracks()}
            >
              Retry
            </button>
          </p>
        )}

        {/* Empty tracks */}
        {!tracksLoading && !tracksError && diskTracks.length === 0 && (
          <div className="py-8 text-center">
            <Music className="w-10 h-10 text-muted mx-auto mb-3" />
            <p className="text-sm text-body-muted">No track files found on disk.</p>
          </div>
        )}

        {/* Tracks table */}
        {!tracksLoading && !tracksError && diskTracks.length > 0 && (
          <div className="overflow-x-auto -mx-2">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-card-border">
                  <th className="px-3 py-2 text-left text-xs font-medium text-muted uppercase tracking-wider w-10">#</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-muted uppercase tracking-wider">Filename</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-muted uppercase tracking-wider hidden sm:table-cell">Format</th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-muted uppercase tracking-wider">Size</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-card-border">
                {diskTracks.map((track, i) => (
                  <tr key={track.path} className="hover:bg-soft-stone/30 transition-colors">
                    <td className="px-3 py-2 text-muted">{i + 1}</td>
                    <td className="px-3 py-2 text-ink font-medium truncate max-w-50 sm:max-w-xs" title={track.filename}>
                      {track.filename}
                    </td>
                    <td className="px-3 py-2 text-muted hidden sm:table-cell">{track.format || '—'}</td>
                    <td className="px-3 py-2 text-muted text-right">{formatFileSize(track.size)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* ============================================
          MusicBrainz Comparison
          ============================================ */}
      <Card padding="lg">
        <h2 className="font-display text-lg text-ink tracking-tight mb-4">
          MusicBrainz Comparison
          {hasMBData && (
            <span className="text-sm text-body-muted ml-2 font-normal">
              ({comparisonRows.length} track{comparisonRows.length !== 1 ? 's' : ''})
            </span>
          )}
        </h2>

        {/* MB loading */}
        {mbLoading && (
          <div className="py-8">
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="flex items-center gap-4 py-2 animate-pulse">
                  <div className="w-6 h-4 bg-soft-stone rounded" />
                  <div className="flex-1 h-4 bg-soft-stone rounded" />
                  <div className="w-16 h-4 bg-soft-stone rounded" />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* MB error */}
        {mbError && !mbLoading && (
          <p className="text-sm text-coral py-4">
            Failed to load MusicBrainz data.{' '}
            <button
              type="button"
              className="underline hover:text-red-800"
              onClick={() => refetchMb()}
            >
              Retry
            </button>
          </p>
        )}

        {/* MB not found */}
        {!mbLoading && !mbError && !hasMBData && (
          <div className="py-8 text-center">
            <Info className="w-10 h-10 text-muted mx-auto mb-3" />
            <p className="text-sm text-body-muted">
              {mbData && !mbData.found
                ? 'No MusicBrainz release found for this album.'
                : 'MusicBrainz comparison data is not available.'}
            </p>
          </div>
        )}

        {/* MB comparison table */}
        {!mbLoading && !mbError && hasMBData && comparisonRows.length > 0 && (
          <div className="overflow-x-auto -mx-2">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-card-border">
                  <th className="px-3 py-2 text-left text-xs font-medium text-muted uppercase tracking-wider w-16">Status</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-muted uppercase tracking-wider w-10">#</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-muted uppercase tracking-wider">MusicBrainz Title</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-muted uppercase tracking-wider hidden sm:table-cell">File on Disk</th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-muted uppercase tracking-wider">Duration</th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-muted uppercase tracking-wider">{/* action */}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-card-border">
                {comparisonRows.map((row, i) => (
                  <MBRow
                    key={i}
                    row={row}
                    index={i}
                    albumId={id ?? ''}
                    onDownloadMissing={queueMutation.mutate}
                    isDownloading={queueMutation.isPending}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Missing tracks summary */}
        {!detailLoading && !detailError && hasMBData && missingTracks.length > 0 && (
          <div className="mt-4 p-4 rounded-sm bg-coral/5 border border-coral/20">
            <div className="flex items-start gap-3">
              <AlertTriangle className="w-5 h-5 text-coral shrink-0 mt-0.5" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-ink">
                  {missingTracks.length} missing track{missingTracks.length !== 1 ? 's' : ''}
                </p>
                <p className="text-xs text-body-muted mt-1">
                  These tracks are listed on MusicBrainz but are not in your library.
                  Queue the album for re-download to fill the gaps.
                </p>
                <div className="mt-3">
                  <Button
                    variant="primary"
                    size="sm"
                    leftIcon={<Download className="w-4 h-4" />}
                    loading={queueMutation.isPending}
                    onClick={() => queueMutation.mutate()}
                  >
                    Re-download Album
                  </Button>
                </div>
              </div>
            </div>
          </div>
        )}
      </Card>

      {/* ============================================
          Queue Flash Message
          ============================================ */}
      {queueFlash && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 px-5 py-3 rounded-pill shadow-lg text-sm font-medium bg-brand-dark text-white animate-[fadeIn_0.3s_ease-out]">
          {queueFlash}
        </div>
      )}

      {/* ============================================
          Delete Confirmation Dialog
          ============================================ */}
      <DeleteConfirmDialog
        open={deleteOpen}
        albumTitle={album.title}
        loading={deleteMutation.isPending}
        onConfirm={() => deleteMutation.mutate()}
        onCancel={() => setDeleteOpen(false)}
      />
    </div>
  );
}

// ============================================
// Sub-components
// ============================================

function MetaItem({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-start gap-2">
      <span className="text-muted mt-0.5 shrink-0">{icon}</span>
      <div className="min-w-0">
        <p className="text-xs text-muted uppercase tracking-wider">{label}</p>
        <p className="text-sm text-ink font-medium truncate" title={value}>
          {value}
        </p>
      </div>
    </div>
  );
}

function MBRow({
  row,
  index: _index,
  albumId: _albumId,
  onDownloadMissing,
  isDownloading,
}: {
  row: TrackComparisonRow;
  index: number;
  albumId: string;
  onDownloadMissing?: () => void;
  isDownloading?: boolean;
}) {
  const isMatched = row.matchType === 'matched';
  const isMbOnly = row.matchType === 'mb-only';
  const isDiskOnly = row.matchType === 'disk-only';

  return (
    <tr
      className={`transition-colors ${
        isMbOnly
          ? 'bg-coral/5 hover:bg-coral/10'
          : isDiskOnly
            ? 'bg-yellow-50/50 hover:bg-yellow-100/50'
            : 'hover:bg-soft-stone/30'
      }`}
    >
      {/* Status icon */}
      <td className="px-3 py-2">
        {isMatched && <CheckCircle className="w-4 h-4 text-deep-green" aria-label="Matched" />}
        {isMbOnly && <XCircle className="w-4 h-4 text-coral" aria-label="Missing from disk" />}
        {isDiskOnly && <Info className="w-4 h-4 text-yellow-500" aria-label="Extra file on disk" />}
      </td>

      {/* Track number */}
      <td className="px-3 py-2 text-muted">
        {row.mbTrack?.position ?? '—'}
      </td>

      {/* MusicBrainz title */}
      <td className="px-3 py-2 text-ink font-medium truncate max-w-50" title={row.mbTrack?.title ?? row.diskTrack?.filename ?? ''}>
        {row.mbTrack?.title ?? '—'}
      </td>

      {/* Disk filename */}
      <td className="px-3 py-2 text-muted truncate max-w-50 hidden sm:table-cell" title={row.diskTrack?.filename ?? ''}>
        {row.diskTrack?.filename ?? (isMbOnly ? (
          <span className="text-coral italic text-xs">Missing</span>
        ) : '—')}
      </td>

      {/* Duration */}
      <td className="px-3 py-2 text-muted text-right">
        {row.mbTrack?.length_ms ? formatMs(row.mbTrack.length_ms) : '—'}
      </td>

      {/* Action */}
      <td className="px-3 py-2 text-right">
        {isMbOnly && (
          <Button
            variant="primary"
            size="sm"
            leftIcon={<Download className="w-3.5 h-3.5" />}
            loading={isDownloading}
            onClick={onDownloadMissing}
            title="Queue album for re-download"
          >
            <span className="hidden sm:inline">Download</span>
          </Button>
        )}
      </td>
    </tr>
  );
}
