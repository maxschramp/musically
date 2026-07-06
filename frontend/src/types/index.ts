// ============================================
// Musically — Shared TypeScript Types
// Matches SPEC.md data models
// ============================================

export type AlbumStatus = 'queued' | 'downloading' | 'downloaded' | 'stalled' | 'rejected';
export type QueueType = 'auto' | 'manual' | 'watch_folder';

export interface Album {
  id: string;
  title: string;
  artist_name: string;
  album_mbid: string | null;
  qobuz_id: string | null;
  status: AlbumStatus;
  queue_type: QueueType;
  reason: string;
  play_count: number;
  retry_count: number;
  next_retry_at: string | null;
  downloaded_at: string | null;
  created_at: string;
  track_count: number;
}

export interface Artist {
  id: string;
  name: string;
  artist_mbid: string | null;
  subscribed: boolean;
  subscription_source: string | null;
  albums_in_library: number;
  total_play_count: number;
}

export interface TrackPlay {
  id: string;
  track_name: string;
  artist_name: string;
  album_name: string;
  album_mbid: string | null;
  artist_mbid: string | null;
  played_at: string;
}

export interface Playlist {
  id: string;
  spotify_id: string;
  name: string;
  playlist_type: 'seasonal' | 'discover' | 'other';
  is_active: boolean;
  track_count: number | null;
  last_synced_at: string | null;
}

export interface Setting {
  key: string;
  value: string;
  description: string;
  category: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  limit: number;
}

export interface Stats {
  total_albums: number;
  total_tracks: number;
  total_artists: number;
  queued_count: number;
  downloading_count: number;
  downloaded_count: number;
  stalled_count: number;
  rejected_count: number;
  subscribed_artists: number;
  watch_folder_pending: number;
}

// ============================================
// API Types
// ============================================

export interface ApiError {
  status: number;
  message: string;
  detail?: string;
}

export interface SettingsByCategory {
  [category: string]: Setting[];
}

// ============================================
// Album Detail Types
// ============================================

export interface AlbumTrackItem {
  filename: string;
  size: number;
  format: string;
  path: string;
}

export interface AlbumTracksResponse {
  album_id: string;
  artist: string;
  title: string;
  folder_path: string;
  tracks: AlbumTrackItem[];
  track_count: number;
}

export interface MusicBrainzTrackItem {
  position: number;
  title: string;
  length_ms: number;
  mbid: string;
}

export interface MusicBrainzAlbumResponse {
  found: boolean;
  mbid: string | null;
  title: string;
  artist: string;
  tracks: MusicBrainzTrackItem[];
  track_count: number;
}

export type TrackMatchType = 'matched' | 'mb-only' | 'disk-only';

export interface TrackComparisonRow {
  diskTrack: AlbumTrackItem | null;
  mbTrack: MusicBrainzTrackItem | null;
  matchType: TrackMatchType;
}

// ============================================
// Task Types
// ============================================

export type TaskStatus = 'completed' | 'running' | 'failed' | 'never_run';

export interface Task {
  task_name: string;
  status: TaskStatus;
  last_run_at: string | null;
  last_result: string | null;
  next_scheduled_at: string | null;
}

export interface TaskTriggerResponse {
  task_name: string;
  triggered: boolean;
  message: string;
}

// ============================================
// Database Types
// ============================================

export interface DatabaseTable {
  table_name: string;
  row_count: number;
}

export interface DatabaseTablesResponse {
  tables: DatabaseTable[];
}

export interface DatabaseTableRows {
  table_name: string;
  columns: string[];
  rows: Record<string, unknown>[];
  total: number;
  page: number;
  limit: number;
}

// ============================================
// Discover / Search Types
// ============================================

export type SearchSource = 'musicbrainz' | 'spotify' | 'qobuz';
export type SearchType = 'album' | 'artist';

export interface SearchResult {
  source: SearchSource;
  type: SearchType;
  artist_name: string | null;
  title?: string | null;
  /** Artist name (when type=artist) — from backend `name` field */
  name?: string | null;
  /** Unified MBID (used for both album and artist results from backend) */
  mbid?: string | null;
  /** @deprecated Use `mbid` — kept for backward compat */
  album_mbid?: string | null;
  /** @deprecated Use `mbid` — kept for backward compat */
  artist_mbid?: string | null;
  spotify_id?: string | null;
  qobuz_id?: string | null;
  year?: number | null;
  in_library: boolean;
  in_queue: boolean;
}

export interface SearchResponse {
  query: string;
  results: SearchResult[];
  warnings?: string[];
  /** @deprecated Not returned by backend — kept for backward compat */
  type?: SearchType;
  /** @deprecated Not returned by backend — kept for backward compat */
  sources?: SearchSource[];
}

// ============================================
// Artist Discography Types
// ============================================

export type ReleaseTypeFilter = 'all' | 'album' | 'ep' | 'single' | 'compilation' | 'live' | 'other';
export type DiscographySortOption = 'year' | 'title' | 'type';

export interface MbTrackInfo {
  position: number;
  title: string;
  length_ms: number;
  id: string;
}

export interface MbReleaseLookup {
  id: string;
  title: string;
  date?: string;
  country?: string;
  status?: string;
  'release-group'?: {
    'primary-type'?: string;
    'secondary-types'?: string[];
  };
  'label-info'?: Array<{
    label?: { name?: string };
  }>;
  media?: Array<{
    tracks?: Array<{
      position: number;
      title: string;
      length?: number;
      recording?: { id: string; title: string; length?: number };
    }>;
  }>;
}

// ============================================
// Artist Lookup Types (for FollowButton)
// ============================================

export interface ArtistLookupResponse {
  found: boolean;
  artist_id: string | null;
  artist_name: string;
  subscribed: boolean;
}
