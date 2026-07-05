// ============================================
// Musically — Formatters
// Date, duration, title case, truncation utilities
// ============================================

/**
 * Format an ISO date string to a human-readable date.
 * e.g. "2026-07-01T12:00:00Z" → "Jul 1, 2026"
 */
export function formatDate(isoString: string | null | undefined): string {
  if (!isoString) return '—';
  const date = new Date(isoString);
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

/**
 * Format an ISO date string to a relative time string.
 * e.g. "2 hours ago", "3 days ago"
 */
export function formatRelativeTime(isoString: string | null | undefined): string {
  if (!isoString) return '—';

  const now = Date.now();
  const then = new Date(isoString).getTime();
  const diffMs = now - then;

  if (diffMs < 0) return 'just now';

  const seconds = Math.floor(diffMs / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);
  const weeks = Math.floor(days / 7);
  const months = Math.floor(days / 30);

  if (seconds < 60) return 'Just now';
  if (minutes < 60) return `${minutes}m ago`;
  if (hours < 24) return `${hours}h ago`;
  if (days < 7) return `${days}d ago`;
  if (weeks < 5) return `${weeks}w ago`;
  if (months < 12) return `${months}mo ago`;

  return formatDate(isoString);
}

/**
 * Format a duration in seconds to "mm:ss" or "hh:mm:ss".
 */
export function formatDuration(totalSeconds: number): string {
  if (totalSeconds < 0) return '0:00';

  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = Math.floor(totalSeconds % 60);

  const pad = (n: number) => n.toString().padStart(2, '0');

  if (hours > 0) {
    return `${hours}:${pad(minutes)}:${pad(seconds)}`;
  }
  return `${minutes}:${pad(seconds)}`;
}

/**
 * Format a number with commas.
 * e.g. 1234567 → "1,234,567"
 */
export function formatNumber(n: number): string {
  return n.toLocaleString('en-US');
}

/**
 * Truncate a string to maxLength, appending "…" if truncated.
 */
export function truncate(str: string, maxLength: number): string {
  if (str.length <= maxLength) return str;
  return str.slice(0, maxLength).trimEnd() + '…';
}

/**
 * Convert a string to Title Case.
 */
export function titleCase(str: string): string {
  return str
    .toLowerCase()
    .split(' ')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}


/**
 * Format an ISO date string to a relative future time string.
 * e.g. future date -> "in 5m", "in 2h", "in 3d"
 */
export function formatTimeUntil(isoString: string | null | undefined): string {
  if (!isoString) return '\u2014';
  const now = Date.now();
  const then = new Date(isoString).getTime();
  const diffMs = then - now;
  if (diffMs <= 0) return 'now';
  const s = Math.floor(diffMs / 1000);
  const m = Math.floor(s / 60);
  const h = Math.floor(m / 60);
  const d = Math.floor(h / 24);
  const w = Math.floor(d / 7);
  if (s < 60) return 'in ' + s + 's';
  if (m < 60) return 'in ' + m + 'm';
  if (h < 24) return 'in ' + h + 'h';
  if (d < 7) return 'in ' + d + 'd';
  if (w < 5) return 'in ' + w + 'w';
  return formatDate(isoString);
}
