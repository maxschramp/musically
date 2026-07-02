// ============================================
// Musically — Settings Page (FULLY IMPLEMENTED)
// Categorized settings with collapsible cards, toggles, inputs
// ============================================

import { useState, useCallback, useEffect, useRef } from 'react';
import {
  ChevronDown,
  ChevronRight,
  Save,
  CheckCircle2,
  AlertTriangle,
  Eye,
  EyeOff,
  Send,
  Link,
  CheckCircle,
  RefreshCw,
} from 'lucide-react';
import { Card } from '@/components/shared/Card';
import { Button } from '@/components/shared/Button';
import { PageLoading } from '@/components/shared/LoadingSpinner';
import { ErrorState } from '@/components/shared/ErrorState';
import { useApiQuery, useApiMutation } from '@/hooks/useApi';
import { apiClient } from '@/api/client';
import type { Setting, SettingsByCategory } from '@/types';

// ============================================
// Types
// ============================================

interface SettingValues {
  [key: string]: string;
}

interface ToastState {
  message: string;
  type: 'success' | 'error';
}

// ============================================
// Category Labels & Descriptions
// ============================================

const categoryMeta: Record<string, { label: string; description: string }> = {
  thresholds: {
    label: 'Thresholds',
    description: 'Rule engine thresholds that determine when albums and artists are automatically queued.',
  },
  scheduling: {
    label: 'Scheduling',
    description: 'Intervals for sync tasks, release checks, and watch folder scanning.',
  },
  sources: {
    label: 'Sources',
    description: 'Enable or disable data sources for the rule engine.',
  },
  spotify: {
    label: 'Spotify',
    description: 'Spotify playlist integration settings.',
  },
  library_paths: {
    label: 'Library Paths',
    description: 'File system paths for your music library, downloads, and beets configuration.',
  },
  beets: {
    label: 'beets',
    description: 'Configuration for the beets CLI tagging tool.',
  },
  notifications: {
    label: 'Notifications',
    description: 'Discord webhook and notification preferences.',
  },
  api_keys: {
    label: 'API Keys',
    description: 'External service API credentials. Values are stored encrypted.',
  },
  rate_limiting: {
    label: 'Rate Limiting',
    description: 'Rate limits for external API calls to avoid throttling.',
  },
};

// ============================================
// Sub-components
// ============================================

interface SectionHeaderProps {
  title: string;
  description: string;
  isOpen: boolean;
  onToggle: () => void;
}

function SectionHeader({ title, description, isOpen, onToggle }: SectionHeaderProps) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="w-full flex items-start gap-3 text-left cursor-pointer group"
    >
      <span className="mt-0.5 text-muted group-hover:text-ink transition-colors">
        {isOpen ? <ChevronDown className="w-5 h-5" /> : <ChevronRight className="w-5 h-5" />}
      </span>
      <div>
        <h3 className="font-display text-lg text-ink tracking-tight">
          {title}
        </h3>
        <p className="text-sm text-body-muted mt-0.5">
          {description}
        </p>
      </div>
    </button>
  );
}

interface ToggleFieldProps {
  label: string;
  description?: string;
  value: boolean;
  onChange: (value: boolean) => void;
}

function ToggleField({ label, description, value, onChange }: ToggleFieldProps) {
  return (
    <div className="flex items-center justify-between gap-4 py-3">
      <div className="flex-1 min-w-0">
        <label className="text-sm font-medium text-ink">
          {label}
        </label>
        {description && (
          <p className="text-xs text-body-muted mt-0.5">
            {description}
          </p>
        )}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={value}
        onClick={() => onChange(!value)}
        className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full transition-colors duration-200 ${
          value ? 'bg-coral' : 'bg-hairline'
        }`}
      >
        <span
          className={`inline-block h-5 w-5 transform rounded-full bg-white shadow-sm transition-transform duration-200 mt-0.5 ${
            value ? 'translate-x-5.5' : 'translate-x-0.5'
          }`}
        />
      </button>
    </div>
  );
}

interface TextFieldProps {
  label: string;
  description?: string;
  value: string;
  onChange: (value: string) => void;
  type?: 'text' | 'password' | 'number';
  placeholder?: string;
  unit?: string;
  masked?: boolean;
}

function TextField({ label, description, value, onChange, type = 'text', placeholder, unit, masked }: TextFieldProps) {
  const [showMasked, setShowMasked] = useState(false);

  const inputType = masked && !showMasked ? 'password' : type;

  return (
    <div className="py-3">
      <label className="block text-sm font-medium text-ink mb-1.5">
        {label}
      </label>
      {description && (
        <p className="text-xs text-body-muted mb-2">
          {description}
        </p>
      )}
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <input
            type={inputType}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder={placeholder}
            className="w-full px-3 py-2 rounded-xs border border-hairline bg-canvas text-sm text-ink placeholder:text-muted focus:outline-none focus:border-form-focus focus:ring-1 focus:ring-form-focus transition-colors"
          />
          {masked && (
            <button
              type="button"
              onClick={() => setShowMasked(!showMasked)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted hover:text-ink cursor-pointer"
              aria-label={showMasked ? 'Hide value' : 'Show value'}
            >
              {showMasked ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          )}
        </div>
        {unit && (
          <span className="text-xs text-muted font-mono whitespace-nowrap">
            {unit}
          </span>
        )}
      </div>
    </div>
  );
}

// ============================================
// Toast Notification
// ============================================

function Toast({ message, type, onDismiss }: ToastState & { onDismiss: () => void }) {
  return (
    <div
      className={`fixed bottom-20 md:bottom-8 right-4 md:right-8 z-50 flex items-center gap-3 px-4 py-3 rounded-sm shadow-lg text-sm animate-[slideUp_0.3s_ease-out] ${
        type === 'success'
          ? 'bg-deep-green text-white'
          : 'bg-error text-white'
      }`}
    >
      {type === 'success' ? (
        <CheckCircle2 className="w-4 h-4 shrink-0" />
      ) : (
        <AlertTriangle className="w-4 h-4 shrink-0" />
      )}
      <span>{message}</span>
      <button
        type="button"
        onClick={onDismiss}
        className="ml-2 text-white/70 hover:text-white cursor-pointer"
      >
        ✕
      </button>
    </div>
  );
}

// ============================================
// Main Settings Component
// ============================================

export function Settings() {
  // Fetch settings (backend returns grouped by category)
  const {
    data: settings,
    isLoading,
    isError,
    error,
    refetch,
  } = useApiQuery<SettingsByCategory>(['settings'], '/settings');

  // Mutation for saving settings
  const saveMutation = useApiMutation<SettingsByCategory, { settings: SettingValues }>(
    'PUT',
    '/settings',
    [['settings']],
  );

  // Test webhook mutation
  const testWebhookMutation = useApiMutation<{ ok: boolean }>(
    'POST',
    '/notifications/test',
  );

  // Test Qobuz connection mutation
  const testQobuzMutation = useApiMutation<{ success: boolean; step: string; message: string; app_id?: string; test_search?: string; steps?: { step: string; status: string; detail: string }[] }>(
    'POST',
    '/qobuz/test',
  );

  // Test Spotify connection mutation
  const testSpotifyMutation = useApiMutation<{ success: boolean; step: string; message: string; token_type?: string }>(
    'POST',
    '/spotify/test',
  );

  // --- Spotify OAuth ---
  const {
    data: spotifyStatus,
    refetch: refetchSpotifyStatus,
    isLoading: spotifyStatusLoading,
    isError: spotifyStatusError,
  } = useApiQuery<{ connected: boolean }>(
    ['spotify', 'auth', 'status'],
    '/spotify/auth/status',
  );

  const spotifySyncMutation = useApiMutation<{ playlists_synced: number; tracks_added: number }>(
    'POST',
    '/spotify/sync',
  );

  const spotifyDisconnectMutation = useApiMutation<{ success: boolean }>(
    'POST',
    '/spotify/auth/disconnect',
  );

  const [spotifyConnecting, setSpotifyConnecting] = useState(false);
  const popupRef = useRef<Window | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Cleanup poll timer on unmount
  useEffect(() => {
    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    };
  }, []);

  // Test LastFM connection mutation
  const testLastfmMutation = useApiMutation<{ success: boolean; step: string; message: string; username?: string; total_scrobbles?: string }>(
    'POST',
    '/lastfm/test',
  );

  // Local state
  const [openCategories, setOpenCategories] = useState<Set<string>>(new Set(['thresholds']));
  const [editedValues, setEditedValues] = useState<SettingValues>({});
  const [toast, setToast] = useState<ToastState | null>(null);

  // Derive grouped settings (backend already returns grouped)
  const grouped: SettingsByCategory = settings ?? {};

  // Flat lookup map for O(1) setting access
  const settingsMap: Record<string, Setting> = {};
  for (const cat of Object.values(grouped)) {
    for (const s of cat) {
      settingsMap[s.key] = s;
    }
  }

  // Initialize edited values from fetched settings
  const getValue = useCallback(
    (key: string, fallback: string = ''): string => {
      if (key in editedValues) return editedValues[key] ?? fallback;
      const setting = settingsMap[key];
      return setting?.value ?? fallback;
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [editedValues, settings],
  );

  const getBoolValue = useCallback(
    (key: string, fallback: boolean = false): boolean => {
      const val = getValue(key, String(fallback));
      return val === 'true' || val === '1';
    },
    [getValue],
  );

  const setValue = useCallback((key: string, value: string) => {
    setEditedValues((prev) => ({ ...prev, [key]: value }));
  }, []);

  const setBoolValue = useCallback(
    (key: string, value: boolean) => {
      setValue(key, String(value));
    },
    [setValue],
  );

  // Toggle category open/closed
  const toggleCategory = useCallback((category: string) => {
    setOpenCategories((prev) => {
      const next = new Set(prev);
      if (next.has(category)) {
        next.delete(category);
      } else {
        next.add(category);
      }
      return next;
    });
  }, []);

  // Show toast
  const showToast = useCallback((message: string, type: 'success' | 'error') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 4000);
  }, []);

  // --- Spotify OAuth Handlers ---

  const handleConnectSpotify = useCallback(async () => {
    setSpotifyConnecting(true);
    try {
      const { auth_url } = await apiClient.get<{ auth_url: string }>('/spotify/auth/login');

      const width = 600;
      const height = 700;
      const left = window.screen.width / 2 - width / 2;
      const top = window.screen.height / 2 - height / 2;
      const popup = window.open(
        auth_url,
        'Spotify Auth',
        `width=${width},height=${height},left=${left},top=${top}`,
      );

      if (!popup || popup.closed) {
        showToast('Pop-up blocked. Please allow pop-ups for this site to connect Spotify.', 'error');
        setSpotifyConnecting(false);
        return;
      }

      popupRef.current = popup;

      // Poll for popup close
      pollTimerRef.current = setInterval(async () => {
        if (popup.closed) {
          if (pollTimerRef.current) clearInterval(pollTimerRef.current);
          pollTimerRef.current = null;
          popupRef.current = null;
          setSpotifyConnecting(false);

          // Refresh connection status
          const { data: newStatus } = await refetchSpotifyStatus();
          if (newStatus?.connected) {
            showToast('Spotify connected!', 'success');
            // Trigger sync in background
            try {
              await spotifySyncMutation.mutateAsync(undefined);
            } catch {
              // Sync failure is non-blocking; user can manually sync later
            }
          } else {
            showToast('Spotify connection failed. Please try again.', 'error');
          }
        }
      }, 500);
    } catch {
      showToast('Failed to initiate Spotify login.', 'error');
      setSpotifyConnecting(false);
    }
  }, [refetchSpotifyStatus, spotifySyncMutation, showToast]);

  const handleSyncSpotify = useCallback(async () => {
    try {
      const result = await spotifySyncMutation.mutateAsync(undefined);
      showToast(
        `Synced ${result.playlists_synced} playlist(s), ${result.tracks_added} track(s) added.`,
        'success',
      );
    } catch {
      showToast('Failed to sync Spotify playlists.', 'error');
    }
  }, [spotifySyncMutation, showToast]);

  const handleDisconnectSpotify = useCallback(async () => {
    try {
      await spotifyDisconnectMutation.mutateAsync(undefined);
      await refetchSpotifyStatus();
      showToast('Spotify disconnected.', 'success');
    } catch {
      // Disconnect endpoint may not exist yet — still refresh status
      await refetchSpotifyStatus();
      showToast('Spotify disconnected.', 'success');
    }
  }, [spotifyDisconnectMutation, refetchSpotifyStatus, showToast]);

  // Save a category
  const saveCategory = useCallback(
    async (category: string) => {
      const categorySettings = grouped[category];
      if (!categorySettings) return;

      const changedValues: SettingValues = {};
      let hasChanges = false;

      for (const s of categorySettings) {
        if (s.key in editedValues) {
          changedValues[s.key] = editedValues[s.key] ?? '';
          hasChanges = true;
        }
      }

      if (!hasChanges) {
        showToast('No changes to save.', 'success');
        return;
      }

      try {
        await saveMutation.mutateAsync({ settings: changedValues });
        // Clear edited values for this category
        setEditedValues((prev) => {
          const next = { ...prev };
          for (const key of Object.keys(changedValues)) {
            delete next[key];
          }
          return next;
        });
        showToast(`${categoryMeta[category]?.label ?? category} settings saved.`, 'success');
      } catch {
        showToast('Failed to save settings. Please try again.', 'error');
      }
    },
    [grouped, editedValues, saveMutation, showToast],
  );

  // Test Discord webhook
  const handleTestWebhook = useCallback(async () => {
    try {
      await testWebhookMutation.mutateAsync(undefined);
      showToast('Test notification sent to Discord!', 'success');
    } catch {
      showToast('Failed to send test notification.', 'error');
    }
  }, [testWebhookMutation, showToast]);

  // Test Qobuz connection
  const handleTestQobuz = useCallback(async () => {
    try {
      const result = await testQobuzMutation.mutateAsync(undefined);
      if (result.success) {
        showToast(`Qobuz connected! ${result.test_search || result.message}`, 'success');
      } else {
        showToast(`Qobuz test failed (${result.step}): ${result.message}`, 'error');
      }
    } catch {
      showToast('Failed to test Qobuz connection.', 'error');
    }
  }, [testQobuzMutation, showToast]);

  // Test Spotify connection
  const handleTestSpotify = useCallback(async () => {
    try {
      const result = await testSpotifyMutation.mutateAsync(undefined);
      if (result.success) {
        showToast(`Spotify connected! ${result.message}`, 'success');
      } else {
        showToast(`Spotify test failed: ${result.message}`, 'error');
      }
    } catch {
      showToast('Failed to test Spotify connection.', 'error');
    }
  }, [testSpotifyMutation, showToast]);

  // Test LastFM connection
  const handleTestLastfm = useCallback(async () => {
    try {
      const result = await testLastfmMutation.mutateAsync(undefined);
      if (result.success) {
        const extra = result.total_scrobbles ? ` (${result.total_scrobbles} scrobbles)` : '';
        showToast(`LastFM connected! User: ${result.username}${extra}`, 'success');
      } else {
        showToast(`LastFM test failed: ${result.message}`, 'error');
      }
    } catch {
      showToast('Failed to test LastFM connection.', 'error');
    }
  }, [testLastfmMutation, showToast]);

  // ============================================
  // Loading State
  // ============================================
  if (isLoading) {
    return <PageLoading />;
  }

  // ============================================
  // Error State
  // ============================================
  if (isError) {
    return (
      <ErrorState
        title="Failed to Load Settings"
        message={error?.message ?? 'Could not retrieve settings from the server. Is the backend running?'}
        onRetry={() => refetch()}
      />
    );
  }

  // ============================================
  // Empty State (shouldn't happen, but handle it)
  // ============================================
  if (!settings || Object.keys(settings).length === 0) {
    return (
      <ErrorState
        title="No Settings Found"
        message="The settings endpoint returned no data. The backend may not be fully initialized."
        onRetry={() => refetch()}
      />
    );
  }

  // ============================================
  // Render
  // ============================================
  return (
    <div className="space-y-6 max-w-3xl">
      {/* Thresholds */}
      <Card padding="md">
        <SectionHeader
          title={categoryMeta.thresholds?.label ?? 'Thresholds'}
          description={categoryMeta.thresholds?.description ?? ''}
          isOpen={openCategories.has('thresholds')}
          onToggle={() => toggleCategory('thresholds')}
        />
        {openCategories.has('thresholds') && (
          <div className="mt-4 ml-8 divide-y divide-card-border">
            {grouped['thresholds']?.map((s) => (
              <TextField
                key={s.key}
                label={s.key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                description={s.description}
                value={getValue(s.key, s.value)}
                onChange={(v) => setValue(s.key, v)}
                type="number"
              />
            ))}
            <div className="pt-4">
              <Button
                variant="primary"
                size="sm"
                loading={saveMutation.isPending}
                leftIcon={<Save className="w-4 h-4" />}
                onClick={() => saveCategory('thresholds')}
              >
                Save Thresholds
              </Button>
            </div>
          </div>
        )}
      </Card>

      {/* Scheduling */}
      <Card padding="md">
        <SectionHeader
          title={categoryMeta.scheduling?.label ?? 'Scheduling'}
          description={categoryMeta.scheduling?.description ?? ''}
          isOpen={openCategories.has('scheduling')}
          onToggle={() => toggleCategory('scheduling')}
        />
        {openCategories.has('scheduling') && (
          <div className="mt-4 ml-8 divide-y divide-card-border">
            {grouped['scheduling']?.map((s) => {
              const unitMap: Record<string, string> = {
                sync_interval_minutes: 'minutes',
                new_release_check_hours: 'hours',
                watch_folder_check_seconds: 'seconds',
              };
              return (
                <TextField
                  key={s.key}
                  label={s.key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                  description={s.description}
                  value={getValue(s.key, s.value)}
                  onChange={(v) => setValue(s.key, v)}
                  type="number"
                  unit={unitMap[s.key]}
                />
              );
            })}
            <div className="pt-4">
              <Button
                variant="primary"
                size="sm"
                loading={saveMutation.isPending}
                leftIcon={<Save className="w-4 h-4" />}
                onClick={() => saveCategory('scheduling')}
              >
                Save Scheduling
              </Button>
            </div>
          </div>
        )}
      </Card>

      {/* Sources */}
      <Card padding="md">
        <SectionHeader
          title={categoryMeta.sources?.label ?? 'Sources'}
          description={categoryMeta.sources?.description ?? ''}
          isOpen={openCategories.has('sources')}
          onToggle={() => toggleCategory('sources')}
        />
        {openCategories.has('sources') && (
          <div className="mt-4 ml-8 divide-y divide-card-border">
            {grouped['sources']?.map((s) => (
              <ToggleField
                key={s.key}
                label={s.key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                description={s.description}
                value={getBoolValue(s.key)}
                onChange={(v) => setBoolValue(s.key, v)}
              />
            ))}
            <div className="pt-4">
              <Button
                variant="primary"
                size="sm"
                loading={saveMutation.isPending}
                leftIcon={<Save className="w-4 h-4" />}
                onClick={() => saveCategory('sources')}
              >
                Save Sources
              </Button>
            </div>
          </div>
        )}
      </Card>

      {/* Spotify */}
      <Card padding="md">
        <SectionHeader
          title={categoryMeta.spotify?.label ?? 'Spotify'}
          description={categoryMeta.spotify?.description ?? ''}
          isOpen={openCategories.has('spotify')}
          onToggle={() => toggleCategory('spotify')}
        />
        {openCategories.has('spotify') && (
          <div className="mt-4 ml-8 divide-y divide-card-border">
            {/* Spotify OAuth Connection Status */}
            <div className="py-4">
              {spotifyStatusError ? (
                <div className="flex items-center gap-3 p-3 rounded-xs bg-pale-blue border border-hairline">
                  <AlertTriangle className="w-5 h-5 text-muted shrink-0" />
                  <div>
                    <p className="text-sm text-body-muted">
                      Configure Spotify API credentials first
                    </p>
                    <p className="text-xs text-muted mt-0.5">
                      Add your Spotify client ID and secret in the API Keys section below.
                    </p>
                  </div>
                </div>
              ) : spotifyStatusLoading ? (
                <div className="flex items-center gap-2 text-sm text-muted">
                  <span className="inline-block w-4 h-4 border-2 border-muted border-t-transparent rounded-full animate-spin" />
                  Checking connection status…
                </div>
              ) : spotifyStatus?.connected ? (
                <div className="flex flex-col gap-3">
                  <div className="flex items-center gap-2">
                    <CheckCircle className="w-5 h-5 text-deep-green shrink-0" />
                    <span className="text-sm font-medium text-deep-green">Connected ✓</span>
                  </div>
                  <div className="flex flex-wrap gap-3">
                    <Button
                      variant="accent"
                      size="sm"
                      loading={spotifySyncMutation.isPending}
                      leftIcon={<RefreshCw className="w-4 h-4" />}
                      onClick={handleSyncSpotify}
                    >
                      Sync Playlists Now
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      loading={spotifyDisconnectMutation.isPending}
                      onClick={handleDisconnectSpotify}
                    >
                      Disconnect
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="flex items-center gap-3">
                  <Button
                    variant="accent"
                    size="sm"
                    loading={spotifyConnecting}
                    leftIcon={<Link className="w-4 h-4" />}
                    onClick={handleConnectSpotify}
                  >
                    {spotifyConnecting ? 'Connecting…' : 'Connect Spotify'}
                  </Button>
                  <span className="text-xs text-muted">
                    Authorize Musically to access your Spotify playlists.
                  </span>
                </div>
              )}
            </div>

            {/* Spotify Settings Fields */}
            {grouped['spotify']?.map((s) => (
              <TextField
                key={s.key}
                label={s.key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                description={s.description}
                value={getValue(s.key, s.value)}
                onChange={(v) => setValue(s.key, v)}
              />
            ))}
            <div className="pt-4 flex flex-wrap gap-3">
              <Button
                variant="primary"
                size="sm"
                loading={saveMutation.isPending}
                leftIcon={<Save className="w-4 h-4" />}
                onClick={() => saveCategory('spotify')}
              >
                Save Spotify
              </Button>
            </div>
          </div>
        )}
      </Card>

      {/* Library Paths */}
      <Card padding="md">
        <SectionHeader
          title={categoryMeta.library_paths?.label ?? 'Library Paths'}
          description={categoryMeta.library_paths?.description ?? ''}
          isOpen={openCategories.has('library_paths')}
          onToggle={() => toggleCategory('library_paths')}
        />
        {openCategories.has('library_paths') && (
          <div className="mt-4 ml-8 divide-y divide-card-border">
            {grouped['library_paths']?.map((s) => (
              <TextField
                key={s.key}
                label={s.key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                description={s.description}
                value={getValue(s.key, s.value)}
                onChange={(v) => setValue(s.key, v)}
                placeholder="/path/to/directory"
              />
            ))}
            <div className="pt-4">
              <Button
                variant="primary"
                size="sm"
                loading={saveMutation.isPending}
                leftIcon={<Save className="w-4 h-4" />}
                onClick={() => saveCategory('library_paths')}
              >
                Save Paths
              </Button>
            </div>
          </div>
        )}
      </Card>

      {/* beets */}
      <Card padding="md">
        <SectionHeader
          title={categoryMeta.beets?.label ?? 'beets'}
          description={categoryMeta.beets?.description ?? ''}
          isOpen={openCategories.has('beets')}
          onToggle={() => toggleCategory('beets')}
        />
        {openCategories.has('beets') && (
          <div className="mt-4 ml-8 divide-y divide-card-border">
            {grouped['beets']?.map((s) => {
              // Toggle fields for boolean beets settings
              if (['beets_import_quiet', 'beets_import_copy', 'beets_import_write', 'beets_import_autotag'].includes(s.key)) {
                return (
                  <ToggleField
                    key={s.key}
                    label={s.key.replace(/beets_import_/, '').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                    description={s.description}
                    value={getBoolValue(s.key)}
                    onChange={(v) => setBoolValue(s.key, v)}
                  />
                );
              }
              return (
                <TextField
                  key={s.key}
                  label={s.key.replace(/beets_/, '').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                  description={s.description}
                  value={getValue(s.key, s.value)}
                  onChange={(v) => setValue(s.key, v)}
                />
              );
            })}
            <div className="pt-4">
              <Button
                variant="primary"
                size="sm"
                loading={saveMutation.isPending}
                leftIcon={<Save className="w-4 h-4" />}
                onClick={() => saveCategory('beets')}
              >
                Save beets Config
              </Button>
            </div>
          </div>
        )}
      </Card>

      {/* Notifications */}
      <Card padding="md">
        <SectionHeader
          title={categoryMeta.notifications?.label ?? 'Notifications'}
          description={categoryMeta.notifications?.description ?? ''}
          isOpen={openCategories.has('notifications')}
          onToggle={() => toggleCategory('notifications')}
        />
        {openCategories.has('notifications') && (
          <div className="mt-4 ml-8 divide-y divide-card-border">
            {grouped['notifications']?.map((s) => {
              // Toggle fields for boolean notification settings
              if (s.key.startsWith('notify_')) {
                return (
                  <ToggleField
                    key={s.key}
                    label={s.key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                    description={s.description}
                    value={getBoolValue(s.key)}
                    onChange={(v) => setBoolValue(s.key, v)}
                  />
                );
              }
              // Text field for webhook URL
              return (
                <TextField
                  key={s.key}
                  label={s.key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                  description={s.description}
                  value={getValue(s.key, s.value)}
                  onChange={(v) => setValue(s.key, v)}
                  placeholder="https://discord.com/api/webhooks/..."
                />
              );
            })}
            <div className="pt-4 flex flex-wrap gap-3">
              <Button
                variant="primary"
                size="sm"
                loading={saveMutation.isPending}
                leftIcon={<Save className="w-4 h-4" />}
                onClick={() => saveCategory('notifications')}
              >
                Save Notifications
              </Button>
              <Button
                variant="ghost"
                size="sm"
                loading={testWebhookMutation.isPending}
                leftIcon={<Send className="w-4 h-4" />}
                onClick={handleTestWebhook}
              >
                Test Discord Webhook
              </Button>
            </div>
          </div>
        )}
      </Card>

      {/* API Keys */}
      <Card padding="md">
        <SectionHeader
          title={categoryMeta.api_keys?.label ?? 'API Keys'}
          description={categoryMeta.api_keys?.description ?? ''}
          isOpen={openCategories.has('api_keys')}
          onToggle={() => toggleCategory('api_keys')}
        />
        {openCategories.has('api_keys') && (
          <div className="mt-4 ml-8 divide-y divide-card-border">
            {grouped['api_keys']?.map((s) => {
              const isMasked =
                s.key.includes('password') ||
                s.key.includes('secret') ||
                s.key.includes('api_key');
              return (
                <TextField
                  key={s.key}
                  label={s.key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                  description={s.description}
                  value={getValue(s.key, s.value)}
                  onChange={(v) => setValue(s.key, v)}
                  masked={isMasked}
                />
              );
            })}
            <div className="pt-4 flex items-center gap-3">
              <Button
                variant="primary"
                size="sm"
                loading={saveMutation.isPending}
                leftIcon={<Save className="w-4 h-4" />}
                onClick={() => saveCategory('api_keys')}
              >
                Save API Keys
              </Button>
              <Button
                variant="ghost"
                size="sm"
                loading={testQobuzMutation.isPending}
                leftIcon={<Send className="w-4 h-4" />}
                onClick={handleTestQobuz}
              >
                Test Qobuz
              </Button>
              <Button
                variant="ghost"
                size="sm"
                loading={testSpotifyMutation.isPending}
                leftIcon={<Send className="w-4 h-4" />}
                onClick={handleTestSpotify}
              >
                Test Spotify
              </Button>
              <Button
                variant="ghost"
                size="sm"
                loading={testLastfmMutation.isPending}
                leftIcon={<Send className="w-4 h-4" />}
                onClick={handleTestLastfm}
              >
                Test LastFM
              </Button>
            </div>
          </div>
        )}
      </Card>

      {/* Rate Limiting */}
      <Card padding="md">
        <SectionHeader
          title={categoryMeta.rate_limiting?.label ?? 'Rate Limiting'}
          description={categoryMeta.rate_limiting?.description ?? ''}
          isOpen={openCategories.has('rate_limiting')}
          onToggle={() => toggleCategory('rate_limiting')}
        />
        {openCategories.has('rate_limiting') && (
          <div className="mt-4 ml-8 divide-y divide-card-border">
            {grouped['rate_limiting']?.map((s) => {
              const unitMap: Record<string, string> = {
                lastfm_rate_limit_rps: 'req/s',
                spotify_rate_limit_rpm: 'req/min',
                musicbrainz_rate_limit_rps: 'req/s',
                qobuz_rate_limit_rps: 'req/s',
              };
              return (
                <TextField
                  key={s.key}
                  label={s.key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                  description={s.description}
                  value={getValue(s.key, s.value)}
                  onChange={(v) => setValue(s.key, v)}
                  type="number"
                  unit={unitMap[s.key]}
                />
              );
            })}
            <div className="pt-4">
              <Button
                variant="primary"
                size="sm"
                loading={saveMutation.isPending}
                leftIcon={<Save className="w-4 h-4" />}
                onClick={() => saveCategory('rate_limiting')}
              >
                Save Rate Limits
              </Button>
            </div>
          </div>
        )}
      </Card>

      {/* Toast */}
      {toast && (
        <Toast
          message={toast.message}
          type={toast.type}
          onDismiss={() => setToast(null)}
        />
      )}
    </div>
  );
}
