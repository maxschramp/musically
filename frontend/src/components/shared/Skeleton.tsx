// ============================================
// Musically — Skeleton Loading Placeholders
// Pulse-animated placeholders for infinite scroll
// ============================================

interface SkeletonProps {
  className?: string;
}

function Bar({ className = '' }: SkeletonProps) {
  return (
    <div
      className={`animate-pulse rounded-sm bg-soft-stone ${className}`}
      aria-hidden="true"
    />
  );
}

// ============================================
// Album Grid Skeleton (Library page)
// ============================================

export function SkeletonAlbumGrid({ count = 10 }: { count?: number }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="space-y-3">
          {/* Artwork placeholder */}
          <Bar className="aspect-square w-full" />
          {/* Title line */}
          <Bar className="h-3 w-3/4" />
          {/* Artist line */}
          <Bar className="h-3 w-1/2" />
        </div>
      ))}
    </div>
  );
}

// ============================================
// Table Row Skeleton (Queue page)
// ============================================

export function SkeletonQueueRows({ count = 5 }: { count?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: count }, (_, i) => (
        <div
          key={i}
          className="flex items-center gap-4 px-4 py-3 rounded-sm bg-canvas border border-hairline"
        >
          {/* Checkbox / artwork area */}
          <Bar className="w-10 h-10 rounded-sm shrink-0" />
          {/* Title + artist */}
          <div className="flex-1 min-w-0 space-y-2">
            <Bar className="h-4 w-2/3" />
            <Bar className="h-3 w-1/2" />
          </div>
          {/* Reason tag */}
          <Bar className="h-6 w-16 rounded-full shrink-0 hidden sm:block" />
          {/* Date */}
          <Bar className="h-3 w-20 shrink-0 hidden md:block" />
          {/* Action buttons */}
          <Bar className="h-8 w-8 rounded-sm shrink-0" />
          <Bar className="h-8 w-8 rounded-sm shrink-0" />
        </div>
      ))}
    </div>
  );
}

// ============================================
// Artist Row Skeletons
// ============================================

export function SkeletonArtistRows({ count = 5 }: { count?: number }) {
  return (
    <div className="divide-y divide-card-border">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="flex items-center gap-4 py-3 px-4 animate-pulse">
          {/* Avatar */}
          <Bar className="w-10 h-10 rounded-full shrink-0" />
          {/* Name + stats */}
          <div className="flex-1 min-w-0 space-y-2">
            <Bar className="h-4 w-1/3" />
            <Bar className="h-3 w-1/2" />
          </div>
          {/* Toggle */}
          <Bar className="h-6 w-11 rounded-full shrink-0" />
        </div>
      ))}
    </div>
  );
}

// ============================================
// Table Row Skeleton (Desktop table — Queue page)
// ============================================

export function SkeletonQueueTableRows({ count = 5 }: { count?: number }) {
  return (
    <>
      {Array.from({ length: count }, (_, i) => (
        <tr key={i} className="border-b border-card-border animate-pulse">
          {/* Checkbox */}
          <td className="py-3 pl-4 pr-2">
            <Bar className="w-4 h-4 rounded-xs" />
          </td>
          {/* Artwork */}
          <td className="py-3 px-2">
            <Bar className="w-10 h-10 rounded-sm" />
          </td>
          {/* Title */}
          <td className="py-3 px-2">
            <Bar className="h-4 w-40" />
          </td>
          {/* Artist */}
          <td className="py-3 px-2">
            <Bar className="h-4 w-32" />
          </td>
          {/* Reason */}
          <td className="py-3 px-2">
            <Bar className="h-5 w-16 rounded-full" />
          </td>
          {/* Type */}
          <td className="py-3 px-2">
            <Bar className="h-4 w-12" />
          </td>
          {/* Date */}
          <td className="py-3 px-2">
            <Bar className="h-4 w-24" />
          </td>
          {/* Actions */}
          <td className="py-3 pr-4">
            <div className="flex gap-2 justify-end">
              <Bar className="w-8 h-8 rounded-sm" />
              <Bar className="w-8 h-8 rounded-sm" />
            </div>
          </td>
        </tr>
      ))}
    </>
  );
}
