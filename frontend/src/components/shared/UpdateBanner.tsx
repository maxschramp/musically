// ============================================
// Musically — Update Banner
// Dismissible banner when a new GitHub release is available
// ============================================

import { useState, useEffect, useRef, useCallback } from 'react';
import { ArrowUpRight } from 'lucide-react';
import { apiClient } from '@/api/client';

interface ReleaseInfo {
  tag_name: string;
  html_url: string;
}

const DISMISS_KEY = 'musically-dismissed-version';

function getDismissedVersion(): string | null {
  try {
    return localStorage.getItem(DISMISS_KEY);
  } catch {
    return null;
  }
}

function setDismissedVersion(version: string): void {
  try {
    localStorage.setItem(DISMISS_KEY, version);
  } catch {
    // localStorage unavailable — silently ignore
  }
}

export function UpdateBanner() {
  const [latestVersion, setLatestVersion] = useState<string | null>(null);
  const [currentVersion, setCurrentVersion] = useState<string | null>(null);
  const [releaseUrl, setReleaseUrl] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const hasChecked = useRef(false);

  const checkForUpdate = useCallback(async () => {
    if (hasChecked.current) return;
    hasChecked.current = true;

    try {
      // Fetch both in parallel
      const [releaseRes, healthRes] = await Promise.allSettled([
        fetch('https://api.github.com/repos/musically-app/musically/releases/latest', {
          headers: { Accept: 'application/vnd.github+json' },
        }),
        apiClient.get<{ version: string }>('/health/version'),
      ]);

      // Parse GitHub release
      if (releaseRes.status === 'fulfilled' && releaseRes.value.ok) {
        const release: ReleaseInfo = await releaseRes.value.json();
        const latest = release.tag_name.replace(/^v/, '');
        const dismissedVersion = getDismissedVersion();

        // Only show if newer than dismissed version, or no dismissed version
        if (!dismissedVersion || compareVersions(latest, dismissedVersion) > 0) {
          setLatestVersion(latest);
          setReleaseUrl(release.html_url);
        }
      }

      // Parse current version
      if (healthRes.status === 'fulfilled') {
        setCurrentVersion(healthRes.value.version);
      }
    } catch {
      // Silently fail — the banner is non-critical
    }
  }, []);

  useEffect(() => {
    // Delay check slightly so the page renders first
    const timer = setTimeout(checkForUpdate, 2000);
    return () => clearTimeout(timer);
  }, [checkForUpdate]);

  const handleDismiss = () => {
    if (latestVersion) {
      setDismissedVersion(latestVersion);
    }
    setDismissed(true);
  };

  // Only show when we have a newer version, it hasn't been dismissed,
  // and we also know the current version (so we can compare properly).
  if (
    dismissed ||
    !latestVersion ||
    !currentVersion ||
    compareVersions(latestVersion, currentVersion) <= 0
  ) {
    return null;
  }

  return (
    <div className="bg-brand-coral text-white">
      <div className="max-w-7xl mx-auto px-4 py-2.5 flex items-center justify-between gap-4">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-sm font-semibold shrink-0">
            ⬆ Musically v{latestVersion} is available!
          </span>
          <span className="text-sm text-white/80 hidden sm:inline truncate">
            You're on v{currentVersion}.
          </span>
          {releaseUrl && (
            <a
              href={releaseUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-sm font-semibold text-white underline hover:text-white/90 shrink-0"
            >
              View release
              <ArrowUpRight className="w-3.5 h-3.5" />
            </a>
          )}
        </div>
        <button
          type="button"
          onClick={handleDismiss}
          className="shrink-0 px-3 py-1 rounded-pill text-sm font-semibold text-white border border-white/40 hover:bg-white/10 transition-colors cursor-pointer"
          aria-label="Dismiss update notification"
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}

// ============================================
// Simple semver comparison
// Returns positive if a > b, negative if a < b, 0 if equal
// ============================================

function compareVersions(a: string, b: string): number {
  const aParts = a.split('.').map(Number);
  const bParts = b.split('.').map(Number);

  for (let i = 0; i < Math.max(aParts.length, bParts.length); i++) {
    const aNum = aParts[i] ?? 0;
    const bNum = bParts[i] ?? 0;
    if (aNum > bNum) return 1;
    if (aNum < bNum) return -1;
  }

  return 0;
}
