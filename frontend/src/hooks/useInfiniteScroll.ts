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

  // Refs to avoid stale closures in the IntersectionObserver callback
  const hasMoreRef = useRef(hasMore);
  const isLoadingRef = useRef(false);
  const observerRef = useRef<IntersectionObserver | null>(null);
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

    // Guard against stale data: if a filter/search reset happened while
    // this query was in-flight, the data.page won't match our current
    // page state.  Discard stale responses.
    if (data.page !== page) return;

    if (page === 1) {
      // New search/filter: replace items entirely
      setItems(data.items);
      setTotal(data.total);
      // If we received items, there might be more — keep going until an
      // empty page signals exhaustion.  This handles post-pagination
      // server-side filtering (e.g. track-count chips) where a page may
      // return fewer than pageSize items.
      setHasMore(data.items.length > 0);
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
      setHasMore(data.items.length > 0);

      return accumulated;
    });
  }, [data, page, pageSize]);

  // Callback ref: fires every time the sentinel <div> mounts or unmounts.
  // This guarantees the IntersectionObserver is always attached to a live
  // DOM node, regardless of whether hasMore changed value or not.
  const loaderRef = useCallback(
    (node: HTMLDivElement | null) => {
      // Clean up any previous observer
      if (observerRef.current) {
        observerRef.current.disconnect();
        observerRef.current = null;
      }

      if (!node || !hasMoreRef.current) return;

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

      observer.observe(node);
      observerRef.current = observer;
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [threshold],
  );

  // When threshold changes, re-attach observer to current node if any.
  // We also clean up on unmount.
  useEffect(() => {
    return () => {
      if (observerRef.current) {
        observerRef.current.disconnect();
        observerRef.current = null;
      }
    };
  }, []);

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
