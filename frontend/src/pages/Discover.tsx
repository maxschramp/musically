// ============================================
// Musically — Discover Page
// Search external sources, browse artist discographies,
// queue albums from MusicBrainz / Spotify / Qobuz
// ============================================

import { useState, useCallback, useMemo } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Search,
  Disc3,
  Plus,
  Music,
  RotateCw,
  Check,
  Library,
  User,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  Calendar,
  Disc,
  Globe,
  Tag,
  Filter,
  ArrowUpDown,
  Layers,
  X,
  Music2,
  type LucideIcon,
} from 'lucide-react';
import { Card } from '@/components/shared/Card';
import { EmptyState } from '@/components/shared/EmptyState';
import { ErrorState } from '@/components/shared/ErrorState';
import { Button } from '@/components/shared/Button';
import { useApiQuery } from '@/hooks/useApi';
import { apiClient } from '@/api/client';
import FollowButton from '@/components/shared/FollowButton';
import type {
  SearchResponse,
  SearchSource,
  SearchType,
  SearchResult,
  ReleaseTypeFilter,
  DiscographySortOption,
  MbReleaseLookup,
  MbTrackInfo,
} from '@/types';

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
// Discography Filter & Sort Config
// ============================================

const RELEASE_TYPE_CONFIG: { key: ReleaseTypeFilter; label: string; icon: LucideIcon }[] = [
  { key: 'all', label: 'All', icon: Layers },
  { key: 'album', label: 'Albums', icon: Disc },
  { key: 'ep', label: 'EPs', icon: Disc },
  { key: 'single', label: 'Singles', icon: Music2 },
  { key: 'compilation', label: 'Compilations', icon: Layers },
  { key: 'live', label: 'Live', icon: Music },
  { key: 'other', label: 'Other', icon: Disc3 },
];

const SORT_OPTIONS: { key: DiscographySortOption; label: string }[] = [
  { key: 'year', label: 'Year' },
  { key: 'title', label: 'Title' },
  { key: 'type', label: 'Type' },
];

/** Map release-group primary types + heuristics to our filter categories */
function classifyReleaseType(item: SearchResult): ReleaseTypeFilter {
  // Heuristic: check title for common patterns
  const title = (item.title ?? '').toLowerCase();
  if (title.includes(' - ep') || title.endsWith(' ep')) return 'ep';
  if (title.includes(' - single') || title.endsWith(' single')) return 'single';
  if (title.includes('compilation')) return 'compilation';
  if (title.includes('live')) return 'live';
  // Default: most releases from MB are albums
  return 'album';
}

/** Extract a display year from a SearchResult */
function extractYear(item: SearchResult): number | null {
  return item.year ?? null;
}

const MB_UA = 'Musically/0.1 (https://github.com/maxschramp/musically)';

/** Fetch a MusicBrainz release by MBID directly (CORS-supported by MB) */
async function fetchMbRelease(mbid: string): Promise<MbReleaseLookup> {
  const url = `https://musicbrainz.org/ws/2/release/${encodeURIComponent(mbid)}?inc=recordings+labels+artists&fmt=json`;
  const res = await fetch(url, { headers: { 'User-Agent': MB_UA } });
  if (!res.ok) throw new Error(`MusicBrainz returned ${res.status}`);
  return res.json() as Promise<MbReleaseLookup>;
}

/** Extract tracks from a raw MB release lookup response */
function extractTracks(release: MbReleaseLookup): MbTrackInfo[] {
  const tracks: MbTrackInfo[] = [];
  for (const medium of release.media ?? []) {
    for (const track of medium.tracks ?? []) {
      const recording = track.recording;
      tracks.push({
        position: track.position,
        title: track.title || recording?.title || '',
        length_ms: track.length ?? recording?.length ?? 0,
        id: recording?.id ?? '',
      });
    }
  }
  return tracks;
}

// ============================================
// Queue Album Button (shared)
// ============================================

function QueueAlbumButton({
  artistName,
  albumTitle,
  inQueue = false,
  inLibrary = false,
  reason = 'Discovered',
}: {
  artistName: string;
  albumTitle?: string;
  inQueue?: boolean;
  inLibrary?: boolean;
  reason?: string;
}) {
  const queryClient = useQueryClient();
  const [justQueued, setJustQueued] = useState(false);

  const queueMutation = useMutation({
    mutationFn: () =>
      apiClient.post('/queue', {
        artist_name: artistName,
        title: albumTitle,
        queue_type: 'manual',
        reason,
      }),
    onSuccess: () => {
      setJustQueued(true);
      queryClient.invalidateQueries({ queryKey: ['queue'] });
      queryClient.invalidateQueries({ queryKey: ['search'] });
      setTimeout(() => setJustQueued(false), 2000);
    },
  });

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
        className={justQueued ? 'text-brand-sage border border-brand-sage/30' : ''}
      >
        {justQueued ? 'Queued ✓' : 'Queued'}
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
// Release Type Badge
// ============================================

function ReleaseTypeBadge({ type }: { type: ReleaseTypeFilter }) {
  if (type === 'all') return null;
  const colorMap: Record<string, string> = {
    album: 'bg-brand-dark/10 text-brand-dark',
    ep: 'bg-brand-purple/10 text-brand-purple',
    single: 'bg-brand-coral/10 text-brand-coral',
    compilation: 'bg-brand-sage/10 text-brand-sage',
    live: 'bg-red-100 text-red-700',
    other: 'bg-soft-stone text-muted',
  };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide ${colorMap[type] ?? colorMap.other}`}>
      {type}
    </span>
  );
}

// ============================================
// Skeleton Components
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

function ArtistCardSkeleton() {
  return (
    <div className="flex items-center gap-4 py-4 px-4 animate-pulse">
      <div className="icon-chip icon-chip-dark shrink-0" />
      <div className="flex-1 space-y-2">
        <div className="h-5 bg-hairline rounded w-1/3" />
        <div className="h-3 bg-hairline rounded w-2/3" />
      </div>
      <div className="h-8 w-20 bg-hairline rounded-pill" />
    </div>
  );
}

function DiscographyRowSkeleton() {
  return (
    <div className="flex items-center gap-3 py-3 px-4 animate-pulse">
      <div className="w-10 h-10 rounded-sm bg-hairline shrink-0" />
      <div className="flex-1 space-y-1.5">
        <div className="h-4 bg-hairline rounded w-2/3" />
        <div className="h-3 bg-hairline rounded w-1/4" />
      </div>
      <div className="w-12 h-4 bg-hairline rounded" />
      <div className="w-16 h-8 bg-hairline rounded-pill" />
    </div>
  );
}

// ============================================
// Track List (expanded album preview)
// ============================================

function TrackList({
  tracks,
  isLoading,
  isError,
  onRetry,
}: {
  tracks: MbTrackInfo[];
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
}) {
  if (isLoading) {
    return (
      <div className="space-y-1.5 py-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="flex items-center gap-3 px-4 py-1.5 animate-pulse">
            <div className="w-5 h-4 bg-hairline rounded" />
            <div className="flex-1 h-3 bg-hairline rounded" />
            <div className="w-10 h-3 bg-hairline rounded" />
          </div>
        ))}
      </div>
    );
  }

  if (isError) {
    return (
      <div className="py-3 px-4 text-center">
        <p className="text-xs text-muted mb-2">Could not load track listing.</p>
        <Button variant="ghost" size="sm" onClick={onRetry}>
          Retry
        </Button>
      </div>
    );
  }

  if (tracks.length === 0) {
    return <p className="py-3 px-4 text-xs text-muted">No track information available.</p>;
  }

  return (
    <div className="divide-y divide-card-border/50">
      {tracks.map((track) => (
        <div
          key={`${track.id}-${track.position}`}
          className="flex items-center gap-3 px-4 py-1.5 hover:bg-soft-stone/30 transition-colors text-xs"
        >
          <span className="w-5 text-right text-muted font-mono tabular-nums shrink-0">
            {track.position}
          </span>
          <span className="flex-1 text-ink truncate">{track.title}</span>
          <span className="text-muted font-mono tabular-nums shrink-0">
            {formatTrackDuration(track.length_ms)}
          </span>
        </div>
      ))}
    </div>
  );
}

function formatTrackDuration(ms: number): string {
  if (!ms || ms <= 0) return '--:--';
  const totalSec = Math.round(ms / 1000);
  const mins = Math.floor(totalSec / 60);
  const secs = totalSec % 60;
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

// ============================================
// Album Row (expandable — discography table)
// ============================================

function AlbumRow({
  item,
  artistName,
}: {
  item: SearchResult;
  artistName: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const [mbData, setMbData] = useState<MbReleaseLookup | null>(null);
  const [mbLoading, setMbLoading] = useState(false);
  const [mbError, setMbError] = useState(false);
  const mbid = item.mbid;

  const loadTracks = useCallback(async () => {
    if (!mbid || mbData || mbLoading) return;
    setMbLoading(true);
    setMbError(false);
    try {
      const release = await fetchMbRelease(mbid);
      setMbData(release);
    } catch {
      setMbError(true);
    } finally {
      setMbLoading(false);
    }
  }, [mbid, mbData, mbLoading]);

  const handleToggle = useCallback(() => {
    const next = !expanded;
    setExpanded(next);
    if (next && mbid) {
      loadTracks();
    }
  }, [expanded, mbid, loadTracks]);

  const tracks = mbData ? extractTracks(mbData) : [];
  const releaseType = classifyReleaseType(item);
  const year = extractYear(item);
  const releaseDate = mbData?.date ?? null;
  const releaseCountry = mbData?.country ?? null;
  const releaseStatus = mbData?.status ?? null;
  const labelName = mbData?.['label-info']?.[0]?.label?.name ?? null;

  return (
    <>
      {/* Main row */}
      <div
        className="flex items-center gap-3 py-3 px-4 hover:bg-soft-stone/20 transition-colors cursor-pointer group"
        onClick={handleToggle}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            handleToggle();
          }
        }}
      >
        {/* Expand chevron */}
        <span className="shrink-0 text-muted group-hover:text-ink transition-colors">
          {expanded ? (
            <ChevronDown className="w-4 h-4" />
          ) : (
            <ChevronRight className="w-4 h-4" />
          )}
        </span>

        {/* Cover art placeholder */}
        <div className="w-10 h-10 rounded-sm bg-soft-stone flex items-center justify-center shrink-0 overflow-hidden">
          <Disc3 className="w-5 h-5 text-muted" />
        </div>

        {/* Title + artist */}
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-ink truncate">
            {item.title ?? 'Unknown Album'}
          </p>
          <p className="text-xs text-body-muted truncate">{item.artist_name ?? artistName}</p>
        </div>

        {/* Year */}
        <span className="text-xs text-muted font-mono tabular-nums w-12 text-right shrink-0 hidden sm:inline">
          {year ?? '—'}
        </span>

        {/* Type badge */}
        <span className="hidden sm:inline shrink-0">
          <ReleaseTypeBadge type={releaseType} />
        </span>

        {/* Source badge */}
        <span className="hidden md:inline shrink-0">
          <SourceBadge source={item.source} />
        </span>

        {/* Action */}
        <div className="shrink-0" onClick={(e) => e.stopPropagation()}>
          <QueueAlbumButton
            artistName={item.artist_name ?? artistName}
            albumTitle={item.title ?? undefined}
            inQueue={item.in_queue}
            inLibrary={item.in_library}
            reason="Discovered"
          />
        </div>
      </div>

      {/* Expanded preview panel */}
      {expanded && (
        <div className="bg-soft-stone/15 border-t border-card-border/50 px-4 py-3">
          <div className="grid grid-cols-1 md:grid-cols-[auto_1fr] gap-4">
            {/* Left: artwork */}
            <div className="hidden md:flex w-40 h-40 rounded-sm bg-soft-stone items-center justify-center shrink-0">
              <Disc3 className="w-12 h-12 text-muted" />
            </div>

            {/* Right: info + tracks */}
            <div className="min-w-0 space-y-3">
              {/* Release info chips */}
              <div className="flex flex-wrap items-center gap-2 text-xs">
                {releaseDate && (
                  <span className="inline-flex items-center gap-1 text-muted">
                    <Calendar className="w-3 h-3" />
                    {releaseDate}
                  </span>
                )}
                {releaseCountry && (
                  <span className="inline-flex items-center gap-1 text-muted">
                    <Globe className="w-3 h-3" />
                    {releaseCountry}
                  </span>
                )}
                {releaseStatus && (
                  <span className="inline-flex items-center gap-1 text-muted capitalize">
                    <Tag className="w-3 h-3" />
                    {releaseStatus}
                  </span>
                )}
                {labelName && (
                  <span className="inline-flex items-center gap-1 text-muted">
                    <Disc className="w-3 h-3" />
                    {labelName}
                  </span>
                )}
                <ReleaseTypeBadge type={releaseType} />
                <SourceBadge source={item.source} />
              </div>

              {/* Track listing */}
              <div>
                <div className="flex items-center gap-2 mb-1.5">
                  <h4 className="text-xs font-semibold text-ink uppercase tracking-wide">
                    Track Listing
                  </h4>
                  {tracks.length > 0 && (
                    <span className="text-[10px] text-muted">({tracks.length} tracks)</span>
                  )}
                </div>
                <div className="bg-canvas border border-card-border rounded-sm overflow-hidden">
                  <TrackList
                    tracks={tracks}
                    isLoading={mbLoading}
                    isError={mbError}
                    onRetry={loadTracks}
                  />
                </div>
              </div>

              {/* External link */}
              {mbid && (
                <a
                  href={`https://musicbrainz.org/release/${mbid}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-xs text-brand-purple hover:underline"
                  onClick={(e) => e.stopPropagation()}
                >
                  <ExternalLink className="w-3 h-3" />
                  View on MusicBrainz
                </a>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

// ============================================
// Discography Panel
// ============================================

function DiscographyPanel({
  artistName,
  onClose,
}: {
  artistName: string;
  onClose: () => void;
}) {
  const [releaseFilter, setReleaseFilter] = useState<ReleaseTypeFilter>('all');
  const [sortBy, setSortBy] = useState<DiscographySortOption>('year');
  const [sortAsc, setSortAsc] = useState(false);
  const [showCount, setShowCount] = useState(10);

  // Fetch artist albums (discography)
  const {
    data,
    isLoading,
    isError,
    error,
    refetch,
  } = useApiQuery<SearchResponse>(
    ['artist-albums', artistName],
    '/search/artist-albums',
    { artist_name: artistName, source: 'musicbrainz,spotify,qobuz' },
    { staleTime: 120_000 },
  );

  const allReleases = useMemo(() => data?.results ?? [], [data?.results]);
  const errorMessage = (error as { message?: string })?.message ?? 'Failed to load discography.';

  // Filter & sort
  const processedReleases = useMemo(() => {
    let filtered = allReleases.filter((r) => r.type === 'album' && r.title);

    // Apply release type filter
    if (releaseFilter !== 'all') {
      filtered = filtered.filter((r) => classifyReleaseType(r) === releaseFilter);
    }

    // Sort
    filtered = [...filtered].sort((a, b) => {
      let cmp = 0;
      switch (sortBy) {
        case 'year':
          cmp = (extractYear(a) ?? 0) - (extractYear(b) ?? 0);
          break;
        case 'title':
          cmp = (a.title ?? '').localeCompare(b.title ?? '');
          break;
        case 'type':
          cmp = classifyReleaseType(a).localeCompare(classifyReleaseType(b));
          break;
      }
      return sortAsc ? cmp : -cmp;
    });

    return filtered;
  }, [allReleases, releaseFilter, sortBy, sortAsc]);

  const visibleReleases = processedReleases.slice(0, showCount);
  const hasMore = showCount < processedReleases.length;

  // Count album types for summary
  const typeCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const r of allReleases.filter((r) => r.type === 'album' && r.title)) {
      const t = classifyReleaseType(r);
      counts[t] = (counts[t] ?? 0) + 1;
    }
    return counts;
  }, [allReleases]);

  const totalAlbums = allReleases.filter((r) => r.type === 'album' && r.title).length;

  return (
    <Card padding="none" className="overflow-hidden border-brand-dark/10">
      {/* Header */}
      <div className="px-5 py-4 border-b border-card-border flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="icon-chip icon-chip-dark shrink-0">
            <User className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="font-display text-lg text-ink font-semibold tracking-tight">
                {artistName}
              </h3>
            </div>
            <p className="text-xs text-body-muted mt-0.5">
              {totalAlbums} release{totalAlbums !== 1 ? 's' : ''}
              {typeCounts.album ? ` · ${typeCounts.album} albums` : ''}
              {typeCounts.ep ? ` · ${typeCounts.ep} EPs` : ''}
              {typeCounts.single ? ` · ${typeCounts.single} singles` : ''}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <FollowButton artistName={artistName} />
          <Button
            variant="ghost"
            size="sm"
            leftIcon={<X className="w-3.5 h-3.5" />}
            onClick={onClose}
          >
            Close
          </Button>
        </div>
      </div>

      {/* Filter & Sort Bar */}
      <div className="px-4 py-2 border-b border-card-border/50 bg-soft-stone/20">
        <div className="flex flex-col sm:flex-row sm:items-center gap-2">
          {/* Release type filter chips */}
          <div className="flex items-center gap-1.5 flex-wrap">
            <Filter className="w-3.5 h-3.5 text-muted shrink-0" />
            {RELEASE_TYPE_CONFIG.map(({ key, label }) => {
              const active = releaseFilter === key;
              const count = key === 'all' ? totalAlbums : (typeCounts[key] ?? 0);
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => { setReleaseFilter(key); setShowCount(10); }}
                  className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-pill text-xs font-medium transition-colors cursor-pointer ${
                    active
                      ? 'bg-brand-dark text-white'
                      : 'bg-white/60 text-muted hover:bg-hairline/50 hover:text-ink'
                  }`}
                >
                  {label}
                  {count > 0 && (
                    <span className={`text-[10px] ${active ? 'text-white/70' : 'text-muted/70'}`}>
                      {count}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {/* Sort */}
          <div className="flex items-center gap-1.5 ml-auto">
            <ArrowUpDown className="w-3.5 h-3.5 text-muted shrink-0" />
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as DiscographySortOption)}
              className="text-xs bg-transparent border-none text-muted cursor-pointer focus:outline-none"
            >
              {SORT_OPTIONS.map(({ key, label }) => (
                <option key={key} value={key}>{label}</option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => setSortAsc(!sortAsc)}
              className="text-xs text-muted hover:text-ink transition-colors cursor-pointer"
              title={sortAsc ? 'Descending' : 'Ascending'}
            >
              {sortAsc ? '↑' : '↓'}
            </button>
          </div>
        </div>
      </div>

      {/* Content */}
      {isLoading && (
        <div className="divide-y divide-card-border">
          {Array.from({ length: 5 }).map((_, i) => (
            <DiscographyRowSkeleton key={i} />
          ))}
        </div>
      )}

      {isError && !isLoading && (
        <div className="py-8">
          <ErrorState
            title="Failed to Load Discography"
            message={errorMessage}
            onRetry={() => refetch()}
          />
        </div>
      )}

      {!isLoading && !isError && processedReleases.length === 0 && (
        <div className="py-8">
          <EmptyState
            icon={<Disc3 className="w-12 h-12" />}
            title="No Releases Found"
            description={
              releaseFilter !== 'all'
                ? `No ${releaseFilter} releases found for "${artistName}". Try a different filter.`
                : `No releases found for "${artistName}".`
            }
          />
        </div>
      )}

      {!isLoading && !isError && processedReleases.length > 0 && (
        <>
          <div className="divide-y divide-card-border/50">
            {visibleReleases.map((item, idx) => (
              <AlbumRow
                key={`${item.source}-${item.mbid ?? item.title}-${idx}`}
                item={item}
                artistName={artistName}
              />
            ))}
          </div>

          {/* Load more / summary */}
          <div className="px-4 py-3 border-t border-card-border/50 flex items-center justify-between">
            <p className="text-xs text-muted">
              Showing {visibleReleases.length} of {processedReleases.length}
            </p>
            {hasMore && (
              <Button
                variant="ghost"
                size="sm"
                leftIcon={<ChevronDown className="w-3.5 h-3.5" />}
                onClick={() => setShowCount((prev) => prev + 10)}
              >
                Load More
              </Button>
            )}
          </div>
        </>
      )}
    </Card>
  );
}

// ============================================
// Artist Result Card (search results)
// ============================================

function ArtistResultCard({
  item,
  onClick,
}: {
  item: SearchResult;
  onClick: () => void;
}) {
  const displayName = item.name ?? item.artist_name ?? 'Unknown Artist';
  const mbid = item.mbid;

  return (
    <div
      className="flex items-center gap-4 py-3 px-4 hover:bg-soft-stone/30 transition-colors cursor-pointer group"
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onClick();
        }
      }}
    >
      {/* Avatar chip */}
      <div className="icon-chip icon-chip-dark shrink-0 group-hover:icon-chip-coral transition-colors duration-200">
        <User className="w-5 h-5" />
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <p className="text-sm font-semibold text-ink truncate group-hover:text-brand-coral transition-colors">
            {displayName}
          </p>
          <SourceBadge source={item.source} />
        </div>
        {mbid && (
          <p className="text-[10px] text-muted font-mono mt-0.5 truncate">
            MBID: {mbid}
          </p>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2 shrink-0" onClick={(e) => e.stopPropagation()}>
        <FollowButton artistName={displayName} />
        <span className="text-xs text-muted hidden sm:inline">
          <ChevronRight className="w-4 h-4" />
        </span>
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
  const [searchType, setSearchType] = useState<SearchType>('artist');

  // Discography panel state
  const [selectedArtist, setSelectedArtist] = useState<string | null>(null);

  // Toggle a source on/off
  const toggleSource = useCallback((source: SearchSource) => {
    setSources((prev) => {
      if (prev.includes(source)) {
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
      setSelectedArtist(null); // Reset discography panel on new search
    },
    [searchInput],
  );

  // Search results query
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
      enabled: !!submittedQuery,
    },
  );

  const results = data?.results ?? [];
  const warnings = data?.warnings ?? [];
  const errorMessage = (error as { message?: string })?.message ?? 'Search failed. Please try again.';

  // Split results by type
  const artistResults = results.filter((r) => r.type === 'artist');
  const albumResults = results.filter((r) => r.type === 'album');

  // Handle artist card click
  const handleArtistClick = useCallback((artistName: string) => {
    setSelectedArtist((prev) => (prev === artistName ? null : artistName));
  }, []);

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div>
        <h2 className="font-display text-xl text-ink tracking-tight font-semibold">
          Discover
        </h2>
        <p className="text-sm text-body-muted mt-1">
          Search for artists to browse their discography, or find albums to queue.
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
              onClick={() => {
                setSearchType(key);
                setSelectedArtist(null);
              }}
              className={`px-4 py-1.5 rounded-pill text-sm font-medium transition-colors duration-150 cursor-pointer ${
                searchType === key
                  ? 'bg-brand-coral text-white'
                  : 'bg-soft-stone text-ink hover:bg-hairline'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </form>

      {/* ============================================
          Idle State (no search yet)
          ============================================ */}
      {!submittedQuery && (
        <Card padding="lg">
          <EmptyState
            icon={<Music className="w-16 h-16" />}
            title="Discover New Music"
            description="Search for an artist to browse their full discography, or search for albums to add to your queue. Results come from MusicBrainz, Spotify, and Qobuz."
          />
        </Card>
      )}

      {/* ============================================
          Loading State
          ============================================ */}
      {submittedQuery && isLoading && (
        <Card padding="none">
          <div className="divide-y divide-card-border">
            {searchType === 'artist'
              ? Array.from({ length: 5 }).map((_, i) => <ArtistCardSkeleton key={i} />)
              : Array.from({ length: 5 }).map((_, i) => <SkeletonCard key={i} />)
            }
          </div>
        </Card>
      )}

      {/* ============================================
          Error State
          ============================================ */}
      {submittedQuery && isError && !isLoading && (
        <Card padding="lg">
          <ErrorState
            title="Search Failed"
            message={errorMessage}
            onRetry={() => refetch()}
          />
        </Card>
      )}

      {/* ============================================
          Empty Results
          ============================================ */}
      {submittedQuery && !isLoading && !isError && results.length === 0 && (
        <Card padding="lg">
          <EmptyState
            icon={<Search className="w-16 h-16" />}
            title="No Results"
            description={`No ${searchType === 'artist' ? 'artists' : 'albums'} found for "${submittedQuery}". Try a different search term or source.`}
          />
        </Card>
      )}

      {/* ============================================
          Warnings
          ============================================ */}
      {warnings.length > 0 && (
        <div className="space-y-1">
          {warnings.map((w, i) => (
            <div
              key={i}
              className="text-xs text-yellow-700 bg-yellow-50 border border-yellow-200 rounded-sm px-3 py-2"
            >
              ⚠ {w}
            </div>
          ))}
        </div>
      )}

      {/* ============================================
          Artist Search Results
          ============================================ */}
      {submittedQuery && !isLoading && !isError && searchType === 'artist' && artistResults.length > 0 && (
        <Card padding="none">
          <div className="px-4 py-3 border-b border-card-border flex items-center justify-between">
            <p className="text-sm text-muted">
              {artistResults.length} artist{artistResults.length !== 1 ? 's' : ''} for &ldquo;{submittedQuery}&rdquo;
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
            {artistResults.map((item, idx) => {
              const displayName = item.name ?? item.artist_name ?? 'Unknown';
              const isSelected = selectedArtist === displayName;
              return (
                <div key={`${item.source}-${displayName}-${idx}`}>
                  <ArtistResultCard
                    item={item}
                    onClick={() => handleArtistClick(displayName)}
                  />
                  {/* Inline discography panel */}
                  {isSelected && (
                    <div className="px-2 pb-4 pt-1">
                      <DiscographyPanel
                        artistName={displayName}
                        onClose={() => setSelectedArtist(null)}
                      />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </Card>
      )}

      {/* ============================================
          Album Search Results (classic list)
          ============================================ */}
      {submittedQuery && !isLoading && !isError && searchType === 'album' && albumResults.length > 0 && (
        <Card padding="none">
          <div className="px-4 py-3 border-b border-card-border flex items-center justify-between">
            <p className="text-sm text-muted">
              {albumResults.length} result{albumResults.length !== 1 ? 's' : ''} for &ldquo;{submittedQuery}&rdquo;
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
            {albumResults.map((result, idx) => (
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
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-brand-sage text-white">
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
                    {result.year ? ` · ${result.year}` : ''}
                  </p>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-2 shrink-0">
                  <FollowButton artistName={result.artist_name ?? ''} />
                  {result.type === 'album' && result.title && (
                    <QueueAlbumButton
                      artistName={result.artist_name ?? ''}
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
