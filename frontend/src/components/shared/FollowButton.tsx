// ============================================
// Musically — FollowButton Component
// Compact heart toggle to follow/unfollow artists
// ============================================

import { useCallback } from 'react';
import { Heart } from 'lucide-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useApiQuery } from '@/hooks/useApi';
import { apiClient } from '@/api/client';
import type { ArtistLookupResponse } from '@/types';

interface FollowButtonProps {
  artistName: string;
  initialSubscribed?: boolean;
  onToggle?: (subscribed: boolean) => void;
}

export default function FollowButton({
  artistName,
  initialSubscribed = false,
  onToggle,
}: FollowButtonProps) {
  const queryClient = useQueryClient();

  // Look up the artist to get ID and actual subscription status
  const { data, isLoading: isLookupLoading } = useApiQuery<ArtistLookupResponse>(
    ['artist-lookup', artistName],
    '/artists/lookup',
    { artist_name: artistName },
    {
      staleTime: 60_000,
      // If we got an initialSubscribed hint, use it as placeholder data
      placeholderData: initialSubscribed
        ? {
            found: true,
            artist_id: null,
            artist_name: artistName,
            subscribed: true,
          }
        : undefined,
    },
  );

  const artistId = data?.artist_id;
  const isSubscribed = data?.subscribed ?? initialSubscribed;

  // Subscribe mutation
  const subscribeMutation = useMutation({
    mutationFn: () => apiClient.post(`/artists/${artistId}/subscribe`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['artist-lookup', artistName] });
      queryClient.invalidateQueries({ queryKey: ['artists'] });
      onToggle?.(true);
    },
  });

  // Unsubscribe mutation
  const unsubscribeMutation = useMutation({
    mutationFn: () => apiClient.post(`/artists/${artistId}/unsubscribe`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['artist-lookup', artistName] });
      queryClient.invalidateQueries({ queryKey: ['artists'] });
      onToggle?.(false);
    },
  });

  const isMutating = subscribeMutation.isPending || unsubscribeMutation.isPending;
  const isLoading = isLookupLoading || isMutating;

  const handleClick = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      e.stopPropagation();
      if (!artistId || isLoading) return;

      if (isSubscribed) {
        unsubscribeMutation.mutate();
      } else {
        subscribeMutation.mutate();
      }
    },
    [artistId, isSubscribed, isLoading, subscribeMutation, unsubscribeMutation],
  );

  // Don't render if lookup found no artist (and no initial state)
  if (data && !data.found && !initialSubscribed) {
    return null;
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={isLoading}
      className={`inline-flex items-center justify-center shrink-0 transition-all duration-200 ${
        isLoading ? 'opacity-50 cursor-wait animate-pulse' : 'cursor-pointer hover:scale-110'
      }`}
      aria-label={isSubscribed ? `Unfollow ${artistName}` : `Follow ${artistName}`}
      title={isSubscribed ? `Unfollow ${artistName}` : `Follow ${artistName}`}
    >
      <Heart
        className={`w-5 h-5 transition-colors duration-200 ${
          isSubscribed
            ? 'fill-coral text-coral'
            : 'fill-none text-muted hover:text-coral'
        }`}
      />
    </button>
  );
}
