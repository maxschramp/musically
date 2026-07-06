// ============================================
// Musically — Swipe Page
// Mobile-first card stack for reviewing the manual queue
// ============================================

import {
  useState,
  useCallback,
  useEffect,
  useRef,
  type PointerEvent as ReactPointerEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Check, X, Disc3, Heart, ToggleLeft, ToggleRight } from 'lucide-react';
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
const EXIT_ANIMATION_MS = 350;

// ============================================
// Types
// ============================================

interface ExitingState {
  direction: 'left' | 'right';
  album: Album;
}

// ============================================
// Swipe Page
// ============================================

export function Swipe() {
  const [swipedIds, setSwipedIds] = useState<Set<string>>(new Set());
  const [exiting, setExiting] = useState<ExitingState | null>(null);
  const [flippedCardId, setFlippedCardId] = useState<string | null>(null);
  const [page, setPage] = useState(1);

  // --- Queue mode toggle: Manual only or Auto + Manual ---
  const [queueMode, setQueueMode] = useState<'manual' | 'all'>('manual');

  // --- Today's stats ---
  const [todayApproved, setTodayApproved] = useState(0);
  const [todayRejected, setTodayRejected] = useState(0);

  const queryClient = useQueryClient();
  const isMobile = useIsMobile();

  const SWIPE_PAGE_SIZE = 200; // backend max — load as many as possible at once

  const queryParams = queueMode === 'all'
    ? { status: 'queued', type: 'auto', limit: SWIPE_PAGE_SIZE, sort: '-created_at', page }
    : { status: 'queued', type: 'manual', limit: SWIPE_PAGE_SIZE, sort: '-created_at', page };

  const { data, isLoading, isError, refetch } = useApiQuery<PaginatedResponse<Album>>(
    ['queue', 'swipe', queueMode, page],
    '/queue',
    queryParams,
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

  // ---- Derived state ----

  const items: Album[] = data?.items ?? [];
  const total = data?.total ?? 0;
  const hasMoreOnServer = total > page * SWIPE_PAGE_SIZE;

  // Filter out swiped IDs (ID-based, immune to TOCTOU race)
  const nonSwiped = items.filter((a) => !swipedIds.has(a.id));

  // Build visible card stack: exiting card first, then remaining non-swiped
  let visibleItems: Album[];

  if (exiting) {
    // Keep the exiting card rendered for the exit animation.
    // Dedupe in case the API refetch hasn't removed it yet.
    const rest = nonSwiped.filter((a) => a.id !== exiting.album.id);
    visibleItems = [exiting.album, ...rest].slice(0, MAX_VISIBLE_CARDS);
  } else {
    visibleItems = nonSwiped.slice(0, MAX_VISIBLE_CARDS);
  }

  const currentAlbum = visibleItems[0] ?? null;
  const allReviewed = nonSwiped.length === 0 && !exiting;
  const hasSwipedAny = swipedIds.size > 0;

  // ---- Preload next card's artwork ----

  useEffect(() => {
    // Preload the (MAX_VISIBLE_CARDS + 1)th non-swiped item's artwork
    // so its image is cached before it becomes visible.
    const preloadCandidate = nonSwiped[MAX_VISIBLE_CARDS];
    if (preloadCandidate) {
      const img = new Image();
      img.src = `/api/albums/${preloadCandidate.id}/artwork`;
    }
    // Image() constructor triggers a fetch; no cleanup needed.
  }, [nonSwiped.length > MAX_VISIBLE_CARDS ? nonSwiped[MAX_VISIBLE_CARDS]?.id : null]);

  // ---- Swipe handler ----

  const handleSwipe = useCallback(
    (direction: 'left' | 'right') => {
      if (!currentAlbum || exiting) return;

      const album = currentAlbum;

      // Mark as swiped IMMEDIATELY (optimistic update) so the card is
      // filtered from visibleItems before the API refetch returns.
      // This prevents a race where the API removes the card but swipedIds
      // hasn't been updated yet, causing the next-card ordering to shift.
      setSwipedIds((prev) => {
        const next = new Set(prev);
        next.add(album.id);
        return next;
      });

      // Fire mutation — triggers API refetch via invalidateQueue
      if (direction === 'right') {
        approveMutation.mutate(album.id);
        setTodayApproved((n) => n + 1);
      } else {
        rejectMutation.mutate(album.id);
        setTodayRejected((n) => n + 1);
      }

      setExiting({ direction, album });
      setFlippedCardId(null);

      setTimeout(() => {
        setExiting(null);
      }, EXIT_ANIMATION_MS);
    },
    [currentAlbum, exiting, approveMutation, rejectMutation],
  );

  // Skip: just remove from stack without any API call
  const handleSkip = useCallback(() => {
    if (!currentAlbum || exiting) return;

    const album = currentAlbum;

    setSwipedIds((prev) => {
      const next = new Set(prev);
      next.add(album.id);
      return next;
    });

    setExiting({ direction: 'left', album });
    setFlippedCardId(null);

    setTimeout(() => {
      setExiting(null);
    }, EXIT_ANIMATION_MS);
  }, [currentAlbum, exiting]);

  const handleFlip = useCallback(
    (id: string) => {
      setFlippedCardId((prev) => (prev === id ? null : id));
    },
    [],
  );

  // Keyboard support — full shortcuts
  const handleKeyDown = useCallback(
    (e: ReactKeyboardEvent) => {
      // Ignore if user is typing in an input
      if ((e.target as HTMLElement).tagName === 'INPUT' || (e.target as HTMLElement).tagName === 'TEXTAREA') return;

      if (e.key === 'ArrowLeft' || e.key === 'a' || e.key === 'A') {
        e.preventDefault();
        handleSwipe('left');
      } else if (e.key === 'ArrowRight' || e.key === 'd' || e.key === 'D') {
        e.preventDefault();
        handleSwipe('right');
      } else if (e.key === 'ArrowUp' || e.key === 'w' || e.key === 'W') {
        e.preventDefault();
        handleSkip();
      } else if (e.key === 'f' || e.key === 'F') {
        e.preventDefault();
        if (currentAlbum) {
          setFlippedCardId((prev) => (prev === currentAlbum.id ? null : currentAlbum.id));
        }
      }
    },
    [handleSwipe, handleSkip, currentAlbum],
  );

  // Focus management: ensure keyboard events are captured
  const containerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    containerRef.current?.focus();
  }, [currentAlbum?.id]);

  // ---- Render ----

  if (isLoading) return <PageLoading />;
  if (isError) return <ErrorState onRetry={() => refetch()} />;

  if (allReviewed) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-6">
        <EmptyState
          icon={<Heart className="w-16 h-16" />}
          title={hasSwipedAny ? 'All caught up!' : 'No albums pending review'}
          description={
            hasSwipedAny
              ? hasMoreOnServer
                ? 'You have reviewed all loaded albums. There may be more in the queue.'
                : 'You have reviewed all queued albums. Check back later or add more from the artist pages.'
              : 'Albums queued by the rule engine or from Spotify playlists will appear here for your approval.'
          }
          actionLabel={
            hasSwipedAny && hasMoreOnServer
              ? 'Load More'
              : hasSwipedAny
                ? 'View Queue'
                : undefined
          }
          onAction={
            hasSwipedAny && hasMoreOnServer
              ? () => {
                  setPage((p) => p + 1);
                  setSwipedIds(new Set());
                }
              : hasSwipedAny
                ? () => (window.location.href = '/queue')
                : undefined
          }
        />
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="flex flex-col items-center gap-4 py-4 outline-none"
      onKeyDown={handleKeyDown}
      tabIndex={0}
      role="region"
      aria-label="Swipe review"
    >
      {/* Queue Mode Toggle */}
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted">Review mode:</span>
        <button
          type="button"
          onClick={() => {
            setQueueMode('manual');
            setSwipedIds(new Set());
            setPage(1);
          }}
          className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-pill text-xs font-semibold transition-colors cursor-pointer ${
            queueMode === 'manual'
              ? 'bg-brand-coral text-white'
              : 'bg-soft-stone text-muted hover:bg-hairline'
          }`}
        >
          {queueMode === 'manual' ? <ToggleRight className="w-3.5 h-3.5" /> : <ToggleLeft className="w-3.5 h-3.5" />}
          Manual Review
        </button>
        <button
          type="button"
          onClick={() => {
            setQueueMode('all');
            setSwipedIds(new Set());
            setPage(1);
          }}
          className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-pill text-xs font-semibold transition-colors cursor-pointer ${
            queueMode === 'all'
              ? 'bg-brand-coral text-white'
              : 'bg-soft-stone text-muted hover:bg-hairline'
          }`}
        >
          {queueMode === 'all' ? <ToggleRight className="w-3.5 h-3.5" /> : <ToggleLeft className="w-3.5 h-3.5" />}
          Auto-Queued
        </button>
      </div>

      {/* Stats Bar */}
      <div className="flex items-center gap-4 text-xs text-muted">
        <span>{items.length + swipedIds.size} remaining</span>
        {todayApproved > 0 && <span>· {todayApproved} approved today</span>}
        {todayRejected > 0 && <span>· {todayRejected} rejected</span>}
      </div>

      {/* Card Stack */}
      <div
        className="relative w-full max-w-md mx-auto"
        style={{ height: isMobile ? '480px' : '560px' }}
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
              exiting={isTop && exiting ? { direction: exiting.direction } : null}
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
          &larr; Reject &middot; Approve &rarr;
        </p>
      )}

      {/* Keyboard shortcuts hint */}
      <p className="text-xs text-body-muted text-center">
        ⌨ ← reject · → approve · ↑ skip · f details
      </p>

      {/* Desktop action buttons */}
      {currentAlbum && (
        <div className="flex gap-4 mt-1">
          <button
            type="button"
            onClick={handleSkip}
            disabled={!!exiting}
            className="w-12 h-12 rounded-full bg-soft-stone text-muted flex items-center justify-center overflow-hidden relative hover:bg-hairline transition-colors cursor-pointer disabled:opacity-50 shadow-md"
            aria-label="Skip"
            title="Skip (w / ↑)"
          >
            <span className="text-lg font-bold">↑</span>
          </button>
          <button
            type="button"
            onClick={() => handleSwipe('left')}
            disabled={!!exiting}
            className="w-16 h-16 rounded-full bg-red-50 text-red-500 flex items-center justify-center overflow-hidden relative hover:bg-red-100 transition-colors cursor-pointer disabled:opacity-50 shadow-md"
            aria-label="Reject"
            title="Reject (a / ←)"
          >
            <X className="w-8 h-8" />
          </button>
          <button
            type="button"
            onClick={() => handleSwipe('right')}
            disabled={!!exiting}
            className="w-16 h-16 rounded-full bg-pale-green text-deep-green flex items-center justify-center overflow-hidden relative hover:bg-green-100 transition-colors cursor-pointer disabled:opacity-50 shadow-md"
            aria-label="Approve"
            title="Approve (d / →)"
          >
            <Check className="w-8 h-8" />
          </button>
          <button
            type="button"
            onClick={() => currentAlbum && handleFlip(currentAlbum.id)}
            disabled={!!exiting}
            className="w-12 h-12 rounded-full bg-soft-stone text-muted flex items-center justify-center overflow-hidden relative hover:bg-hairline transition-colors cursor-pointer disabled:opacity-50 shadow-md"
            aria-label="Flip card"
            title="Details (f)"
          >
            <span className="text-sm font-bold">f</span>
          </button>
        </div>
      )}

      {/* Progress indicator */}
      <p className="text-xs text-body-muted">
        {swipedIds.size} of {items.length + swipedIds.size} reviewed
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
  exiting: { direction: 'left' | 'right' } | null;
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

  if (exiting?.direction === 'left') {
    transform = `translateX(-150%) translateY(${offset.y * 0.5}px) rotate(-20deg)`;
  } else if (exiting?.direction === 'right') {
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
        // Bug 1 fix: only disable transition during active dragging.
        // Exit animation now transitions smoothly to off-screen.
        transition: dragging ? 'none' : 'transform 0.35s cubic-bezier(0.4, 0, 0.2, 1)',
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
        className={`relative h-full w-full overflow-hidden shadow-lg flex flex-col ${isTop ? 'cursor-grab active:cursor-grabbing' : ''}`}
      >
        <div
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerUp}
          className="h-full w-full touch-none select-none flex flex-col"
        >
          {/* Album art — large square, fills top portion of card */}
          <div className="aspect-square bg-soft-stone flex items-center justify-center relative overflow-hidden">
            {imgError ? (
              <Disc3 className="w-20 h-20 text-hairline" />
            ) : (
              <img
                src={`/api/albums/${album.id}/artwork`}
                alt={`${album.artist_name} - ${album.title}`}
                className="w-full h-full object-cover"
                onError={() => setImgError(true)}
                loading="eager"
                decoding="async"
              />
            )}

            {/* Track count pill */}
            {album.track_count > 0 && (
              <span className="absolute top-2 right-2 z-10 px-2.5 py-0.5 rounded-full text-xs font-medium bg-primary/70 text-white">
                {album.track_count} tracks
              </span>
            )}
          </div>

          {/* Card body — scrollable if content overflows */}
          <div
            className="p-5 flex flex-col gap-3 flex-1 overflow-y-auto"
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
