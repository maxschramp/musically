// ============================================
// Musically — useInfiniteScroll Hook
// Reusable infinite scroll with accumulated items
// ============================================

import { useState, useCallback, useRef, useEffect } from 'react';
import { useApiQuery } from './useApi';
import type { PaginatedResponse } from '@/types';

interface UseInfiniteScrollOptions {
  pageSize?: number;
  threshold?: number; // px from bottom to trigger load
}

export function useInfiniteScroll<T>(
  queryKey: readonly unknown[],
  path: string,
  params?: Record<string, string | number | boolean | undefined>,
  options?: UseInfiniteScrollOptions,
) {
  const { pageSize = 50, threshold = 200 } = options ?? {};
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<T[]>([]);
  const [hasMore, setHasMore] = useState(true);
  const [total, setTotal] = useState(0);
  const loaderRef = useRef<HTMLDivElement>(null);

  // Refs to avoid stale closures in the IntersectionObserver callback
  const hasMoreRef = useRef(hasMore);
  const isLoadingRef = useRef(false);
  hasMoreRef.current = hasMore;

  const queryParams = { ...params, page, limit: pageSize };

  const { data, isLoading, isError, error, refetch } = useApiQuery<PaginatedResponse<T>>(
    [...queryKey, page],
    path,
    queryParams,
    { enabled: hasMore },
  );

  // Keep isLoadingRef in sync (runs on every render, always current)
  isLoadingRef.current = isLoading;

  // Accumulate items when data changes
  useEffect(() => {
    if (!data) return;

    if (page === 1) {
      // New search/filter: replace items entirely
      setItems(data.items);
      setTotal(data.total);
      setHasMore(data.items.length === pageSize && data.items.length < data.total);
      return;
    }

    // Subsequent page: append, deduplicate by ID
    setItems((prev) => {
      const existingIds = new Set(prev.map((item: unknown) => (item as { id: string }).id));
      const newUnique = data.items.filter(
        (item: unknown) => !existingIds.has((item as { id: string }).id),
      );
      const accumulated = [...prev, ...newUnique];

      // Update total and hasMore based on accumulated state
      setTotal(data.total);
      setHasMore(
        data.items.length === pageSize && accumulated.length < data.total,
      );

      return accumulated;
    });
  }, [data, page, pageSize]);

  // Intersection Observer for scroll detection.
  // Only depends on hasMore and threshold — NOT isLoading, because:
  // - isLoadingRef is always current (set during render, before effects)
  // - hasMoreRef is always current (set during render, before effects)
  // - Recreating the observer on every load toggle can cause missed intersections
  useEffect(() => {
    const loader = loaderRef.current;
    if (!loader || !hasMore) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (
          entries[0]?.isIntersecting &&
          hasMoreRef.current &&
          !isLoadingRef.current
        ) {
          setPage((p) => p + 1);
        }
      },
      { rootMargin: `0px 0px ${threshold}px 0px` },
    );

    observer.observe(loader);
    return () => observer.disconnect();
  }, [hasMore, threshold]);

  const reset = useCallback(() => {
    setPage(1);
    setItems([]);
    setHasMore(true);
    setTotal(0);
  }, []);

  return {
    items,
    isLoading: isLoading && page === 1,
    isLoadingMore: isLoading && page > 1,
    isError,
    error,
    hasMore,
    loaderRef,
    refetch,
    reset,
    total,
  };
}
