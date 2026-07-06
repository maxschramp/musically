// ============================================
// Musically — Library Page
// Searchable album art grid with API integration
// ============================================

import { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Disc3,
  Search,
  CheckCircle,
  XCircle,
  Music,
  Trash2,
  CheckSquare,
  Square,
  LayoutGrid,
  List,
  ArrowUpDown,
  AlertCircle,
} from 'lucide-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Card } from '@/components/shared/Card';
import { Button } from '@/components/shared/Button';
import { EmptyState } from '@/components/shared/EmptyState';
import { ErrorState } from '@/components/shared/ErrorState';
import { LoadingSpinner } from '@/components/shared/LoadingSpinner';
import { SkeletonAlbumGrid } from '@/components/shared/Skeleton';
import { Modal } from '@/components/shared/Modal';
import { useApiQuery } from '@/hooks/useApi';
import { useInfiniteScroll } from '@/hooks/useInfiniteScroll';
import { apiClient } from '@/api/client';
import { formatDate, truncate } from '@/utils/format';
import type {
  Album,
  AlbumTracksResponse,
  MusicBrainzAlbumResponse,
  TrackComparisonRow,
} from '@/types';

// ============================================
// Album Card
// ============================================

interface AlbumCardProps {
  album: Album;
  index: number;
  onClick: () => void;
  selectMode?: boolean;
  isSelected?: boolean;
  onToggleSelect?: (id: string) => void;
}

function AlbumCard({ album, index: _index, onClick, selectMode = false, isSelected = false, onToggleSelect }: AlbumCardProps) {
  const [imgError, setImgError] = useState(false);

  const handleClick = () => {
    if (selectMode && onToggleSelect) {
      onToggleSelect(album.id);
    } else {
      onClick();
    }
  };

  return (
    <Card padding="sm" onClick={handleClick}>
      <div className="aspect-square rounded-sm bg-soft-stone flex items-center justify-center mb-3 overflow-hidden relative">
        <img
          src={`/api/albums/${album.id}/artwork`}
          alt={`${album.artist_name} - ${album.title}`}
          className="absolute inset-0 w-full h-full object-cover rounded-sm"
          onError={() => setImgError(true)}
          loading="lazy"
        />
        {imgError && (
          <Disc3 className="w-10 h-10 text-muted" />
        )}
        {/* Select checkbox overlay */}
        {selectMode && (
          <div className="absolute top-2 left-2 z-10">
            {isSelected ? (
              <CheckSquare className="w-5 h-5 text-coral drop-shadow-sm" />
            ) : (
              <Square className="w-5 h-5 text-white/70 drop-shadow-sm" />
            )}
          </div>
        )}
        {selectMode && isSelected && (
          <div className="absolute inset-0 bg-coral/10 rounded-sm" />
        )}
      </div>
      <p className="text-sm font-medium text-ink truncate" title={album.title}>
        {truncate(album.title, 30)}
      </p>
      <p className="text-xs text-muted truncate mt-0.5" title={album.artist_name}>
        {album.artist_name}
      </p>
      <div className="flex items-center justify-between gap-1 mt-0.5">
        <span className="text-xs text-muted">
          {album.track_count > 0 ? `${album.track_count} track${album.track_count !== 1 ? 's' : ''}` : ''}
        </span>
        {/* Missing tracks indicator — always clickable to open detail for MB comparison */}
        <span
          className="text-amber-500 hover:text-amber-600 cursor-pointer shrink-0"
          title="Check MusicBrainz for missing tracks"
          onClick={(e) => {
            e.stopPropagation();
            onClick();
          }}
        >
          <AlertCircle className="w-3.5 h-3.5" />
        </span>
      </div>
      {album.downloaded_at && (
        <p className="text-xs text-body-muted mt-0.5">
          {formatDate(album.downloaded_at)}
        </p>
      )}
    </Card>
  );
}

// ============================================
// Track Comparison Helpers
// ============================================

/**
 * Normalize a filename for fuzzy matching against MusicBrainz track titles.
 * Strips extension, leading track numbers, and replaces underscores/hyphens.
 */
function normalizeFilename(filename: string): string {
  // Remove file extension
  let name = filename.replace(/\.[^.]+$/, '');
  // Replace underscores and hyphens with spaces
  name = name.replace(/[_-]+/g, ' ');
  // Remove leading track numbers like "01", "1.", "01 -", "1-", "01)", etc.
  name = name.replace(/^\d{1,3}[\s.\-)]*\s*/, '');
  // Collapse multiple spaces
  name = name.replace(/\s+/g, ' ');
  return name.trim();
}

/**
 * Compare disk files with MusicBrainz tracks.
 * Returns unified rows: matched pairs, MB-only (missing on disk), and disk-only (extra).
 */
function compareTracks(
  diskTracks: { filename: string; size: number; format: string; path: string }[],
  mbTracks: { position: number; title: string; length_ms: number; mbid: string }[],
): TrackComparisonRow[] {
  const rows: TrackComparisonRow[] = [];
  const usedDiskIndices = new Set<number>();

  // Pre-normalize disk filenames once
  const normalizedDisks = diskTracks.map((dt) => normalizeFilename(dt.filename).toLowerCase());

  // For each MusicBrainz track, find a matching disk file
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

  // Add any disk tracks that weren't matched to any MB track
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

/** Format milliseconds to mm:ss */
function formatMs(ms: number): string {
  const totalSec = Math.round(ms / 1000);
  const mins = Math.floor(totalSec / 60);
  const secs = totalSec % 60;
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

// ============================================
// Library Page
// ============================================

export function Library() {
  const navigate = useNavigate();
  const [searchInput, setSearchInput] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [selectedAlbum, setSelectedAlbum] = useState<Album | null>(null);

  // Filter and select mode state
  const [trackFilter, setTrackFilter] = useState<'all' | 'singles' | 'eps' | 'albums'>('all');
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);

  // --- Sorting ---
  const [sortBy, setSortBy] = useState<string>('-created_at');

  // --- View toggle (Grid / Table), persisted in localStorage ---
  const [view, setView] = useState<'grid' | 'table'>(() => {
    try {
      const stored = localStorage.getItem('musically-library-view');
      if (stored === 'grid' || stored === 'table') return stored;
    } catch {
      // localStorage unavailable
    }
    return 'grid';
  });

  const setViewPersisted = (v: 'grid' | 'table') => {
    setView(v);
    try {
      localStorage.setItem('musically-library-view', v);
    } catch {
      // localStorage unavailable
    }
  };

  // Sort options list
  const sortOptions = [
    { label: 'Date Added (newest)', value: '-created_at' },
    { label: 'Date Added (oldest)', value: 'created_at' },
    { label: 'Alphabetical (A–Z)', value: 'title' },
    { label: 'Alphabetical (Z–A)', value: '-title' },
    { label: 'Artist (A–Z)', value: 'artist_name' },
    { label: 'Artist (Z–A)', value: '-artist_name' },
    { label: 'Release Date (newest)', value: '-release_date' },
    { label: 'Release Date (oldest)', value: 'release_date' },
    { label: 'Track Count (most)', value: '-track_count' },
    { label: 'Track Count (least)', value: 'track_count' },
  ];

  const trackFilterParams = useMemo(() => {
    switch (trackFilter) {
      case 'singles': return { min_tracks: 1, max_tracks: 3 };
      case 'eps': return { min_tracks: 4, max_tracks: 7 };
      case 'albums': return { min_tracks: 8 };
      default: return {};
    }
  }, [trackFilter]);

  const queryParams = useMemo(() => ({
    search: debouncedSearch || undefined,
    sort: sortBy,
    ...trackFilterParams,
  }), [debouncedSearch, sortBy, trackFilterParams]);

  const {
    items: albums,
    isLoading,
    isLoadingMore,
    isError,
    error,
    hasMore,
    loaderRef,
    refetch,
    reset,
    total,
  } = useInfiniteScroll<Album>(
    ['albums', debouncedSearch, trackFilter, sortBy],
    '/albums',
    queryParams,
  );

  // Debounce search input by 300ms
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchInput);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

  // Reset infinite scroll when search, filter, or sort changes
  useEffect(() => {
    reset();
  }, [debouncedSearch, trackFilter, sortBy, reset]);

  // --- Detail Queries (enabled only when an album is selected) ---
  const queryClient = useQueryClient();

  const bulkDeleteMutation = useMutation({
    mutationFn: (ids: string[]) =>
      apiClient.post<{ deleted: number; errors: string[] }>('/library/bulk-delete', {
        album_ids: ids,
        delete_files: true,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['albums'] });
      setSelectedIds(new Set());
      setSelectMode(false);
      setDeleteConfirmOpen(false);
    },
  });

  // --- Album Detail Queries (enabled only when an album is selected) ---
  const {
    data: tracksData,
    isLoading: tracksLoading,
    isError: tracksError,
    error: tracksErr,
    refetch: refetchTracks,
  } = useApiQuery<AlbumTracksResponse>(
    ['album-tracks', selectedAlbum?.id],
    `/albums/${selectedAlbum?.id}/tracks`,
    undefined,
    { enabled: !!selectedAlbum },
  );

  const {
    data: mbData,
    isLoading: mbLoading,
    isError: mbError,
    error: mbErr,
    refetch: refetchMb,
  } = useApiQuery<MusicBrainzAlbumResponse>(
    ['album-musicbrainz', selectedAlbum?.id],
    `/albums/${selectedAlbum?.id}/musicbrainz`,
    undefined,
    { enabled: !!selectedAlbum },
  );

  const errorMessage = (error as { message?: string })?.message ?? 'Failed to load library.';

  // Build comparison rows when both queries are loaded
  const detailLoading = tracksLoading || mbLoading;
  const detailError = tracksError || mbError;
  const detailErrMsg =
    tracksErr?.message ?? mbErr?.message ?? 'Failed to load album details.';
  const handleDetailRetry = () => {
    if (tracksError) refetchTracks();
    if (mbError) refetchMb();
  };

  const comparisonRows: TrackComparisonRow[] =
    tracksData && mbData
      ? compareTracks(tracksData.tracks, mbData.tracks)
      : [];

  const closeModal = () => setSelectedAlbum(null);

  return (
    <div className="space-y-6">
      {/* Search Bar */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" />
        <input
          type="text"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder="Search by artist or album title…"
          className="w-full pl-10 pr-4 py-2.5 rounded-sm border border-hairline bg-canvas text-sm text-ink placeholder:text-muted focus:outline-none focus:border-form-focus focus:ring-1 focus:ring-form-focus transition-colors"
        />
      </div>

      {/* Filter Chips */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted mr-1">Tracks:</span>
        {([
          { key: 'all', label: 'All' },
          { key: 'singles', label: 'Singles (1–3)' },
          { key: 'eps', label: 'EPs (4–7)' },
          { key: 'albums', label: 'Albums (8+)' },
        ] as const).map(({ key, label }) => (
          <button
            key={key}
            type="button"
            onClick={() => {
              setTrackFilter(key);
            }}
            className={`px-3 py-1.5 rounded-pill text-xs font-medium transition-colors duration-150 cursor-pointer ${
              trackFilter === key
                ? 'bg-ink text-white'
                : 'bg-soft-stone text-muted hover:bg-hairline'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Sort Dropdown + View Toggle */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        {/* Sort */}
        <div className="relative">
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            className="appearance-none pl-3 pr-9 py-1.5 rounded-pill text-xs font-medium bg-soft-stone text-ink border-0 cursor-pointer hover:bg-hairline transition-colors focus:outline-none focus:ring-2 focus:ring-focus-blue"
            aria-label="Sort albums"
          >
            {sortOptions.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <ArrowUpDown className="absolute right-2.5 top-1/2 -translate-y-1/2 w-3 h-3 text-muted pointer-events-none" />
        </div>

        {/* View Toggle */}
        <div className="flex items-center rounded-pill bg-soft-stone p-0.5">
          <button
            type="button"
            onClick={() => setViewPersisted('grid')}
            className={`px-3 py-1.5 rounded-pill text-xs font-medium transition-colors cursor-pointer flex items-center gap-1.5 ${
              view === 'grid'
                ? 'bg-ink text-white'
                : 'text-muted hover:text-ink'
            }`}
            aria-label="Grid view"
          >
            <LayoutGrid className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Grid</span>
          </button>
          <button
            type="button"
            onClick={() => setViewPersisted('table')}
            className={`px-3 py-1.5 rounded-pill text-xs font-medium transition-colors cursor-pointer flex items-center gap-1.5 ${
              view === 'table'
                ? 'bg-ink text-white'
                : 'text-muted hover:text-ink'
            }`}
            aria-label="Table view"
          >
            <List className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Table</span>
          </button>
        </div>
      </div>

      {/* Header with Select Toggle */}
      {!isLoading && !isError && albums.length > 0 && (
        <div className="flex items-center justify-between">
          <p className="text-sm text-muted">
            {total} album{total !== 1 ? 's' : ''}
          </p>
          <div className="flex items-center gap-2">
            {selectMode && (
              <button
                type="button"
                onClick={() => {
                  if (selectedIds.size === albums.length) {
                    setSelectedIds(new Set());
                  } else {
                    setSelectedIds(new Set(albums.map((a) => a.id)));
                  }
                }}
                className="text-xs text-muted hover:text-ink transition-colors"
              >
                {selectedIds.size === albums.length ? 'Deselect All' : 'Select All'}
              </button>
            )}
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setSelectMode(!selectMode);
                setSelectedIds(new Set());
              }}
            >
              {selectMode ? 'Cancel' : 'Select'}
            </Button>
          </div>
        </div>
      )}

      {/* Loading State */}
      {isLoading && (
        <Card padding="lg">
          <LoadingSpinner size="lg" label="Loading library…" className="py-16" />
        </Card>
      )}

      {/* Error State */}
      {isError && !isLoading && (
        <Card padding="lg">
          <ErrorState
            title="Failed to Load Library"
            message={errorMessage}
            onRetry={() => refetch()}
          />
        </Card>
      )}

      {/* Empty State */}
      {!isLoading && !isError && albums.length === 0 && (
        <Card padding="lg">
          <EmptyState
            icon={<Disc3 className="w-16 h-16" />}
            title={debouncedSearch ? 'No albums found' : 'No albums in library'}
            description={
              debouncedSearch
                ? `No albums matching "${debouncedSearch}". Try a different search term.`
                : 'Your downloaded FLAC library will appear here. Albums are added automatically based on your rule engine configuration.'
            }
          />
        </Card>
      )}

      {/* Grid / Table View */}
      {!isLoading && !isError && albums.length > 0 && (
        <>
          {/* ========== Grid View ========== */}
          {view === 'grid' && (
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4">
              {albums.map((album, i) => (
                <AlbumCard
                  key={album.id}
                  album={album}
                  index={i}
                  onClick={() => navigate(`/library/${album.id}`)}
                  selectMode={selectMode}
                  isSelected={selectedIds.has(album.id)}
                  onToggleSelect={(id) => {
                    setSelectedIds((prev) => {
                      const next = new Set(prev);
                      if (next.has(id)) {
                        next.delete(id);
                      } else {
                        next.add(id);
                      }
                      return next;
                    });
                  }}
                />
              ))}
            </div>
          )}

          {/* ========== Table View ========== */}
          {view === 'table' && (
            <LibraryTable
              albums={albums}
              selectMode={selectMode}
              selectedIds={selectedIds}
              onToggleSelect={(id) => {
                setSelectedIds((prev) => {
                  const next = new Set(prev);
                  if (next.has(id)) {
                    next.delete(id);
                  } else {
                    next.add(id);
                  }
                  return next;
                });
              }}
              onAlbumClick={(album) => navigate(`/library/${album.id}`)}
            />
          )}

          {/* Skeleton placeholders while loading the next page */}
          {isLoadingMore && <SkeletonAlbumGrid count={10} />}

          {/* Infinite scroll sentinel */}
          {hasMore && (
            <div ref={loaderRef} className="py-4 flex justify-center">
              {isLoadingMore ? <LoadingSpinner size="sm" /> : null}
            </div>
          )}
        </>
      )}

      {/* Select Mode Bottom Bar */}
      {selectMode && selectedIds.size > 0 && (
        <div className="fixed bottom-0 left-0 right-0 z-40 bg-primary text-on-primary shadow-lg">
          <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
            <span className="text-sm font-medium">
              {selectedIds.size} album{selectedIds.size !== 1 ? 's' : ''} selected
            </span>
            <div className="flex items-center gap-3">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setSelectMode(false);
                  setSelectedIds(new Set());
                }}
                className="text-on-primary! hover:bg-white/10"
              >
                Cancel
              </Button>
              <Button
                variant="danger"
                size="sm"
                leftIcon={<Trash2 className="w-4 h-4" />}
                loading={bulkDeleteMutation.isPending}
                onClick={() => setDeleteConfirmOpen(true)}
              >
                Delete Selected
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      <Modal open={deleteConfirmOpen} onClose={() => setDeleteConfirmOpen(false)}>
        <div className="p-6">
          <h3 className="text-lg font-medium text-ink mb-2">
            Delete {selectedIds.size} album{selectedIds.size !== 1 ? 's' : ''}?
          </h3>
          <p className="text-sm text-body-muted mb-6">
            This will permanently delete the selected albums and their files from disk.
            This action cannot be undone.
          </p>
          <div className="flex items-center justify-end gap-3">
            <Button variant="ghost" size="sm" onClick={() => setDeleteConfirmOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              size="sm"
              loading={bulkDeleteMutation.isPending}
              onClick={() => bulkDeleteMutation.mutate([...selectedIds])}
            >
              Delete
            </Button>
          </div>
        </div>
      </Modal>

      {/* ============================================ */}
      {/* Album Detail Modal                          */}
      {/* ============================================ */}
      <Modal open={!!selectedAlbum} onClose={closeModal}>
        {/* Loading State */}
        {detailLoading && (
          <div className="p-8">
            <LoadingSpinner size="lg" label="Loading album details…" className="py-16" />
          </div>
        )}

        {/* Error State */}
        {detailError && !detailLoading && (
          <div className="p-8">
            <ErrorState
              title="Failed to Load Album Details"
              message={detailErrMsg}
              onRetry={handleDetailRetry}
            />
          </div>
        )}

        {/* Detail Content */}
        {!detailLoading && !detailError && tracksData && mbData && (
          <div className="flex flex-col">
            {/* Header */}
            <div className="flex items-start gap-5 p-6 pb-4 border-b border-card-border">
              {/* Album Artwork */}
              <div className="w-28 h-28 sm:w-36 sm:h-36 rounded-sm bg-soft-stone flex-shrink-0 flex items-center justify-center overflow-hidden relative">
                {selectedAlbum && (
                  <img
                    src={`/api/albums/${selectedAlbum.id}/artwork`}
                    alt={`${tracksData.artist} - ${tracksData.title}`}
                    className="absolute inset-0 w-full h-full object-cover rounded-sm"
                    onError={(e) => {
                      (e.target as HTMLImageElement).style.display = 'none';
                    }}
                  />
                )}
                <Disc3 className="w-12 h-12 text-muted" />
              </div>

              {/* Album Info */}
              <div className="min-w-0 flex-1 pt-1">
                <h2 className="text-xl font-medium text-ink leading-tight truncate">
                  {tracksData.title}
                </h2>
                <p className="text-sm text-body-muted mt-1">
                  {tracksData.artist}
                </p>
                <div className="flex flex-wrap items-center gap-3 mt-3 text-xs text-muted">
                  <span>
                    {tracksData.track_count} track{tracksData.track_count !== 1 ? 's' : ''} on disk
                  </span>
                  {mbData.found && (
                    <span>
                      {mbData.track_count} track{mbData.track_count !== 1 ? 's' : ''} on MusicBrainz
                    </span>
                  )}
                  {mbData.mbid && (
                    <span className="truncate max-w-[200px]" title={mbData.mbid}>
                      MBID: {mbData.mbid}
                    </span>
                  )}
                </div>
                {!mbData.found && (
                  <p className="text-xs text-coral mt-2">
                    Album not found on MusicBrainz
                  </p>
                )}
              </div>
            </div>

            {/* Track Comparison Table */}
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-card-border text-left text-xs text-muted uppercase tracking-wider">
                    <th className="w-10 py-2.5 pl-6 font-medium">#</th>
                    <th className="py-2.5 font-medium">Track on Disk</th>
                    <th className="py-2.5 pr-6 font-medium">MusicBrainz</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-card-border">
                  {comparisonRows.map((row, i) => (
                    <tr
                      key={i}
                      className={
                        row.matchType === 'mb-only'
                          ? 'bg-coral/[0.04]'
                          : row.matchType === 'disk-only'
                            ? 'bg-soft-stone/50'
                            : ''
                      }
                    >
                      {/* Row number */}
                      <td className="py-2.5 pl-6 text-muted tabular-nums">
                        {row.mbTrack?.position ?? '—'}
                      </td>

                      {/* Disk track */}
                      <td className="py-2.5">
                        {row.diskTrack ? (
                          <span className="text-ink truncate block max-w-[220px]" title={row.diskTrack.filename}>
                            {row.diskTrack.filename}
                          </span>
                        ) : (
                          <span className="text-muted italic">—</span>
                        )}
                      </td>

                      {/* MusicBrainz track + match indicator */}
                      <td className="py-2.5 pr-6">
                        <div className="flex items-center gap-2">
                          {row.mbTrack ? (
                            <>
                              <span className="text-ink truncate max-w-[200px]" title={row.mbTrack.title}>
                                {row.mbTrack.title}
                              </span>
                              <span className="text-xs text-muted tabular-nums shrink-0">
                                {formatMs(row.mbTrack.length_ms)}
                              </span>
                            </>
                          ) : (
                            <span className="text-muted italic">—</span>
                          )}

                          {/* Match icon */}
                          {row.matchType === 'matched' && (
                            <CheckCircle className="w-4 h-4 text-deep-green shrink-0 ml-auto" />
                          )}
                          {row.matchType === 'mb-only' && (
                            <XCircle className="w-4 h-4 text-coral shrink-0 ml-auto" />
                          )}
                          {row.matchType === 'disk-only' && (
                            <Music className="w-4 h-4 text-muted shrink-0 ml-auto" />
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Summary footer */}
            <div className="flex items-center gap-4 px-6 py-3 border-t border-card-border text-xs text-muted">
              <span className="flex items-center gap-1.5">
                <CheckCircle className="w-3.5 h-3.5 text-deep-green" />
                {comparisonRows.filter((r) => r.matchType === 'matched').length} matched
              </span>
              <span className="flex items-center gap-1.5">
                <XCircle className="w-3.5 h-3.5 text-coral" />
                {comparisonRows.filter((r) => r.matchType === 'mb-only').length} missing
              </span>
              <span className="flex items-center gap-1.5">
                <Music className="w-3.5 h-3.5 text-muted" />
                {comparisonRows.filter((r) => r.matchType === 'disk-only').length} extra
              </span>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}

// ============================================
// Library Table Component
// Cohere research-table style: white card, thin rules, hover states
// ============================================


interface LibraryTableProps {
  albums: Album[];
  selectMode: boolean;
  selectedIds: Set<string>;
  onToggleSelect: (id: string) => void;
  onAlbumClick: (album: Album) => void;
}

function LibraryTable({
  albums,
  selectMode,
  selectedIds,
  onToggleSelect,
  onAlbumClick,
}: LibraryTableProps) {
  const [imgErrors, setImgErrors] = useState<Set<string>>(new Set());

  const handleImgError = (id: string) => {
    setImgErrors((prev) => {
      const next = new Set(prev);
      next.add(id);
      return next;
    });
  };

  return (
    <Card padding="none">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-card-border text-left text-xs text-muted uppercase tracking-wider">
              {selectMode && <th className="w-10 py-2.5 pl-4 font-medium"> </th>}
              <th className="w-12 py-2.5 pl-4 font-medium"></th>
              <th className="py-2.5 font-medium">Album</th>
              <th className="py-2.5 font-medium hidden sm:table-cell">Tracks</th>
              <th className="py-2.5 font-medium hidden md:table-cell">Format</th>
              <th className="py-2.5 font-medium hidden lg:table-cell">Size</th>
              <th className="py-2.5 font-medium hidden lg:table-cell">Downloaded</th>
              <th className="py-2.5 pr-4 font-medium text-right"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-card-border">
            {albums.map((album) => {
              const imgFailed = imgErrors.has(album.id);
              return (
                <tr
                  key={album.id}
                  className="hover:bg-soft-stone/30 transition-colors cursor-pointer"
                  onClick={() => {
                    if (selectMode) {
                      onToggleSelect(album.id);
                    } else {
                      onAlbumClick(album);
                    }
                  }}
                >
                  {/* Select checkbox */}
                  {selectMode && (
                    <td className="py-2.5 pl-4" onClick={(e) => e.stopPropagation()}>
                      <button
                        type="button"
                        onClick={() => onToggleSelect(album.id)}
                        className="cursor-pointer"
                        aria-label={selectedIds.has(album.id) ? 'Deselect' : 'Select'}
                      >
                        {selectedIds.has(album.id) ? (
                          <CheckSquare className="w-4 h-4 text-coral" />
                        ) : (
                          <Square className="w-4 h-4 text-muted" />
                        )}
                      </button>
                    </td>
                  )}

                  {/* Artwork thumbnail */}
                  <td className="py-2.5 pl-4">
                    <div className="w-10 h-10 rounded-sm bg-soft-stone overflow-hidden shrink-0 flex items-center justify-center">
                      {imgFailed ? (
                        <Disc3 className="w-5 h-5 text-muted" />
                      ) : (
                        <img
                          src={`/api/albums/${album.id}/artwork`}
                          alt=""
                          className="w-full h-full object-cover"
                          loading="lazy"
                          onError={() => handleImgError(album.id)}
                        />
                      )}
                    </div>
                  </td>

                  {/* Artist — Album title */}
                  <td className="py-2.5 min-w-0">
                    <div className="truncate">
                      <span className="text-ink font-medium truncate" title={album.title}>
                        {truncate(album.title, 50)}
                      </span>
                      <span className="text-muted block sm:hidden text-xs">
                        {truncate(album.artist_name, 30)}
                      </span>
                      <span className="text-muted hidden sm:block text-xs truncate" title={album.artist_name}>
                        {album.artist_name}
                      </span>
                    </div>
                  </td>

                  {/* Track count */}
                  <td className="py-2.5 hidden sm:table-cell text-muted tabular-nums">
                    {album.track_count || '—'}
                  </td>

                  {/* Format */}
                  <td className="py-2.5 hidden md:table-cell text-muted">
                    {'—'}
                  </td>

                  {/* Size */}
                  <td className="py-2.5 hidden lg:table-cell text-muted tabular-nums">
                    {'—'}
                  </td>

                  {/* Downloaded date */}
                  <td className="py-2.5 hidden lg:table-cell text-muted">
                    {album.downloaded_at ? formatDate(album.downloaded_at) : '—'}
                  </td>

                  {/* Actions */}
                  <td className="py-2.5 pr-4 text-right" onClick={(e) => e.stopPropagation()}>
                    <div className="flex items-center justify-end gap-1">
                      {/* Missing tracks indicator */}
                      <span
                        className="text-amber-500 hover:text-amber-600 cursor-pointer p-1"
                        title="Check MusicBrainz for missing tracks"
                        onClick={() => onAlbumClick(album)}
                      >
                        <AlertCircle className="w-3.5 h-3.5" />
                      </span>
                      {/* View detail */}
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => onAlbumClick(album)}
                        className="text-xs"
                      >
                        View
                      </Button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
