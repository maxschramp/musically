// ============================================
// Musically — Swipe Page
// Mobile-first card stack for reviewing the manual queue
// ============================================

import {
  useState,
  useCallback,
  useRef,
  type PointerEvent as ReactPointerEvent,
  type KeyboardEvent,
} from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Check, X, Disc3, Heart } from 'lucide-react';
import { apiClient } from '@/api/client';
import { useApiQuery } from '@/hooks/useApi';
import { useIsMobile } from '@/hooks/useMediaQuery';
import { Badge } from '@/components/shared/Badge';
import { Card } from '@/components/shared/Card';
import { EmptyState } from '@/components/shared/EmptyState';
import { ErrorState } from '@/components/shared/ErrorState';
import { PageLoading } from '@/components/shared/LoadingSpinner';
import { formatDate } from '@/utils/format';
import type { Album, PaginatedResponse } from '@/types';

// ============================================
// Constants
// ============================================

const SWIPE_THRESHOLD = 100;
const MAX_VISIBLE_CARDS = 3;

// ============================================
// Swipe Page
// ============================================

export function Swipe() {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [exiting, setExiting] = useState<'left' | 'right' | null>(null);
  const [flippedCardId, setFlippedCardId] = useState<string | null>(null);

  const queryClient = useQueryClient();
  const isMobile = useIsMobile();

  const { data, isLoading, isError, refetch } = useApiQuery<PaginatedResponse<Album>>(
    ['queue', 'manual-swipe'],
    '/queue',
    { status: 'queued', type: 'manual', limit: 50, sort: '-created_at' },
  );

  const invalidateQueue = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['queue'] });
  }, [queryClient]);

  const approveMutation = useMutation({
    mutationFn: (id: string) => apiClient.post<Album>(`/queue/${id}/approve`),
    onSuccess: invalidateQueue,
  });

  const rejectMutation = useMutation({
    mutationFn: (id: string) => apiClient.post<Album>(`/queue/${id}/reject`),
    onSuccess: invalidateQueue,
  });

  // ---- Derived ----

  const items: Album[] = data?.items ?? [];
  const allReviewed = currentIndex >= items.length;
  const visibleItems = items.slice(currentIndex, currentIndex + MAX_VISIBLE_CARDS);
  const currentAlbum = visibleItems[0] ?? null;

  // ---- Swipe handler ----

  const handleSwipe = useCallback(
    (direction: 'left' | 'right') => {
      if (!currentAlbum || exiting) return;

      setExiting(direction);
      setFlippedCardId(null);

      const id = currentAlbum.id;

      setTimeout(() => {
        if (direction === 'right') {
          approveMutation.mutate(id);
        } else {
          rejectMutation.mutate(id);
        }
        setCurrentIndex((prev) => prev + 1);
        setExiting(null);
      }, 350);
    },
    [currentAlbum, exiting, approveMutation, rejectMutation],
  );

  const handleFlip = useCallback(
    (id: string) => {
      setFlippedCardId((prev) => (prev === id ? null : id));
    },
    [],
  );

  // Keyboard support
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'ArrowLeft') handleSwipe('left');
      else if (e.key === 'ArrowRight') handleSwipe('right');
    },
    [handleSwipe],
  );

  // ---- Render ----

  if (isLoading) return <PageLoading />;
  if (isError) return <ErrorState onRetry={() => refetch()} />;

  if (items.length === 0 || allReviewed) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh]">
        <EmptyState
          icon={<Heart className="w-16 h-16" />}
          title={allReviewed ? 'All caught up!' : 'No albums pending review'}
          description={
            allReviewed
              ? 'You have reviewed all queued albums. Check back later or add more from the artist pages.'
              : 'Albums queued by the rule engine or from Spotify playlists will appear here for your approval.'
          }
          actionLabel={allReviewed ? 'View Queue' : undefined}
          onAction={allReviewed ? () => window.location.href = '/queue' : undefined}
        />
      </div>
    );
  }

  return (
    <div
      className="flex flex-col items-center gap-6 py-4 outline-none"
      onKeyDown={handleKeyDown}
      tabIndex={0}
    >
      {/* Card Stack */}
      <div
        className="relative w-full max-w-md mx-auto"
        style={{ height: isMobile ? '420px' : '480px' }}
      >
        {visibleItems.map((album, i) => {
          const isTop = i === 0;
          const isFlipped = flippedCardId === album.id;

          return (
            <SwipeCard
              key={album.id}
              album={album}
              isTop={isTop}
              isFlipped={isFlipped}
              stackIndex={i}
              exiting={isTop ? exiting : null}
              onSwipeLeft={() => handleSwipe('left')}
              onSwipeRight={() => handleSwipe('right')}
              onFlip={() => handleFlip(album.id)}
            />
          );
        })}
      </div>

      {/* Swipe hint */}
      {currentAlbum && !exiting && (
        <p className="text-xs text-muted text-center">
          &larr; Skip &middot; Approve &rarr;
        </p>
      )}

      {/* Desktop action buttons */}
      {currentAlbum && (
        <div className="flex gap-6 mt-2">
          <button
            type="button"
            onClick={() => handleSwipe('left')}
            disabled={!!exiting}
            className="w-16 h-16 rounded-full bg-red-50 text-red-500 flex items-center justify-center overflow-hidden relative hover:bg-red-100 transition-colors cursor-pointer disabled:opacity-50 shadow-md"
            aria-label="Skip"
          >
            <X className="w-8 h-8" />
          </button>
          <button
            type="button"
            onClick={() => handleSwipe('right')}
            disabled={!!exiting}
            className="w-16 h-16 rounded-full bg-pale-green text-deep-green flex items-center justify-center overflow-hidden relative hover:bg-green-100 transition-colors cursor-pointer disabled:opacity-50 shadow-md"
            aria-label="Approve"
          >
            <Check className="w-8 h-8" />
          </button>
        </div>
      )}

      {/* Progress indicator */}
      <p className="text-xs text-body-muted">
        {currentIndex + 1} of {items.length}
      </p>
    </div>
  );
}

// ============================================
// SwipeCard Component
// ============================================

function SwipeCard({
  album,
  isTop,
  isFlipped,
  stackIndex,
  exiting,
  onSwipeLeft,
  onSwipeRight,
  onFlip,
}: {
  album: Album;
  isTop: boolean;
  isFlipped: boolean;
  stackIndex: number;
  exiting: 'left' | 'right' | null;
  onSwipeLeft: () => void;
  onSwipeRight: () => void;

  onFlip: () => void;
}) {
  const [imgError, setImgError] = useState(false);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const startPos = useRef<{ x: number; y: number } | null>(null);

  // ---- Pointer event handlers ----

  const handlePointerDown = useCallback(
    (e: ReactPointerEvent) => {
      if (!isTop || exiting) return;
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
      startPos.current = { x: e.clientX, y: e.clientY };
      setDragging(true);
    },
    [isTop, exiting],
  );

  const handlePointerMove = useCallback(
    (e: ReactPointerEvent) => {
      if (!dragging || !startPos.current || !isTop || exiting) return;
      const dx = e.clientX - startPos.current.x;
      const dy = e.clientY - startPos.current.y;
      setOffset({ x: dx, y: dy });
    },
    [dragging, isTop, exiting],
  );

  const handlePointerUp = useCallback(
    (e: ReactPointerEvent) => {
      if (!dragging || !isTop) return;
      (e.target as HTMLElement).releasePointerCapture(e.pointerId);
      setDragging(false);
      startPos.current = null;

      const absX = Math.abs(offset.x);

      if (absX > SWIPE_THRESHOLD) {
        if (offset.x > 0) {
          setOffset({ x: 500, y: offset.y });
          onSwipeRight();
        } else {
          setOffset({ x: -500, y: offset.y });
          onSwipeLeft();
        }
      } else {
        setOffset({ x: 0, y: 0 });
      }
    },
    [dragging, isTop, offset, onSwipeLeft, onSwipeRight],
  );

  // ---- Compute card style ----

  // Stack cards behind are slightly offset and smaller
  const stackScale = isTop ? 1 : 1 - stackIndex * 0.05;
  const stackTranslateY = isTop ? 0 : stackIndex * 16;

  let transform = '';

  if (exiting === 'left') {
    transform = `translateX(-150%) translateY(${offset.y * 0.5}px) rotate(-20deg)`;
  } else if (exiting === 'right') {
    transform = `translateX(150%) translateY(${offset.y * 0.5}px) rotate(20deg)`;
  } else if (isTop && dragging) {
    const rotate = offset.x * 0.05;
    transform = `translateX(${offset.x}px) translateY(${offset.y}px) rotate(${rotate}deg)`;
  } else {
    transform = `scale(${stackScale}) translateY(${stackTranslateY}px)`;
  }

  // Swipe feedback overlay opacity
  const feedbackOpacity = dragging ? Math.min(Math.abs(offset.x) / SWIPE_THRESHOLD, 1) : 0;
  const isRight = offset.x > 0;

  return (
    <div
      className={`absolute inset-0 ${isTop ? 'z-20' : `z-${20 - stackIndex}`} ${!isTop && !exiting ? 'pointer-events-none' : ''}`}
      style={{
        transform,
        transition: dragging || exiting ? 'none' : 'transform 0.35s cubic-bezier(0.4, 0, 0.2, 1)',
      }}
    >
      {/* Feedback overlays */}
      {isTop && dragging && (
        <>
          <div
            className="absolute inset-0 rounded-lg bg-deep-green z-10 pointer-events-none flex items-center justify-start px-6"
            style={{ opacity: isRight ? feedbackOpacity : 0 }}
          >
            <Check className="w-12 h-12 text-white" />
          </div>
          <div
            className="absolute inset-0 rounded-lg bg-red-400 z-10 pointer-events-none flex items-center justify-end px-6"
            style={{ opacity: isRight ? 0 : feedbackOpacity }}
          >
            <X className="w-12 h-12 text-white" />
          </div>
        </>
      )}

      {/* The card itself */}
      <Card
        padding="none"
        className={`relative h-full w-full overflow-hidden shadow-lg ${isTop ? 'cursor-grab active:cursor-grabbing' : ''}`}
      >
        <div
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerUp}
          className="h-full w-full touch-none select-none"
        >
          {/* Album art */}
          <div className="h-48 bg-soft-stone flex items-center justify-center relative">
            {imgError ? (
              <Disc3 className="w-20 h-20 text-hairline" />
            ) : (
              <img src={`/api/albums/${album.id}/artwork`} alt="" className="h-full w-full object-cover" onError={() => setImgError(true)} loading="lazy" />
            )}
          </div>

          {/* Card body */}
          <div
            className="p-5 flex flex-col gap-3"
            onClick={(e) => {
              // Only flip on tap (not after drag)
              if (!dragging && isTop) {
                e.stopPropagation();
                onFlip();
              }
            }}
          >
            <div>
              <p className="text-xs text-muted uppercase tracking-wider">
                {album.artist_name}
              </p>
              <h2 className="font-display text-xl text-ink mt-0.5">
                {album.title}
              </h2>
            </div>

            <div className="flex items-center gap-2 flex-wrap">
              <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-soft-stone text-ink">
                {album.reason}
              </span>
              {album.play_count > 0 && (
                <span className="text-xs text-body-muted">
                  {album.play_count} plays
                </span>
              )}
            </div>

            {/* Flipped details */}
            {isFlipped && (
              <div className="mt-2 pt-3 border-t border-card-border space-y-2 animate-[fadeIn_0.2s_ease-out]">
                <DetailRow label="Status" value={<Badge status={album.status} />} />
                <DetailRow label="Play Count" value={String(album.play_count)} />
                <DetailRow label="Queued" value={formatDate(album.created_at)} />
                {album.downloaded_at && (
                  <DetailRow label="Downloaded" value={formatDate(album.downloaded_at)} />
                )}
              </div>
            )}

            {!isFlipped && (
              <p className="text-xs text-muted mt-auto">
                Tap to see details
              </p>
            )}
          </div>
        </div>
      </Card>
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-body-muted">{label}</span>
      <span className="text-ink font-medium">{value}</span>
    </div>
  );
}
