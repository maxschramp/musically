// ============================================
// Musically — useMediaQuery Hook
// ============================================

import { useState, useEffect } from 'react';

/**
 * React hook that tracks a CSS media query string.
 * Returns true when the media query matches.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState<boolean>(() => {
    if (typeof window !== 'undefined') {
      return window.matchMedia(query).matches;
    }
    return false;
  });

  useEffect(() => {
    const mediaQuery = window.matchMedia(query);

    const handleChange = (event: MediaQueryListEvent) => {
      setMatches(event.matches);
    };

    // Set initial value (handles SSR scenarios)
    setMatches(mediaQuery.matches);

    mediaQuery.addEventListener('change', handleChange);
    return () => {
      mediaQuery.removeEventListener('change', handleChange);
    };
  }, [query]);

  return matches;
}

/**
 * Convenience hook: returns true if viewport is <= 767px (mobile).
 */
export function useIsMobile(): boolean {
  return useMediaQuery('(max-width: 767px)');
}

/**
 * Convenience hook: returns true if viewport is >= 1280px (desktop).
 */
export function useIsDesktop(): boolean {
  return useMediaQuery('(min-width: 1280px)');
}
