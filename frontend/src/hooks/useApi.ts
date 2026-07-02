// ============================================
// Musically — Generic API Hooks
// Thin wrappers around TanStack Query for typed API calls
// ============================================

import { useQuery, useMutation, useQueryClient, type UseQueryOptions } from '@tanstack/react-query';
import { apiClient, ApiClientError } from '@/api/client';

// ============================================
// Generic Query Hook
// ============================================

export function useApiQuery<T>(
  queryKey: readonly unknown[],
  path: string,
  params?: Record<string, string | number | boolean | undefined>,
  options?: Omit<UseQueryOptions<T, ApiClientError>, 'queryKey' | 'queryFn'>,
) {
  return useQuery<T, ApiClientError>({
    queryKey: [...queryKey],
    queryFn: () => apiClient.get<T>(path, params),
    staleTime: 30_000,
    retry: 1,
    ...options,
  });
}

// ============================================
// Generic Mutation Hooks
// ============================================

export function useApiMutation<TData, TBody = unknown>(
  method: 'POST' | 'PUT' | 'DELETE',
  path: string,
  invalidateKeys?: readonly unknown[][],
) {
  const queryClient = useQueryClient();

  return useMutation<TData, ApiClientError, TBody | void>({
    mutationFn: (body: TBody | void) => {
      if (method === 'DELETE') {
        return apiClient.delete<TData>(path);
      }
      if (method === 'PUT') {
        return apiClient.put<TData>(path, body);
      }
      return apiClient.post<TData>(path, body);
    },
    onSuccess: () => {
      if (invalidateKeys) {
        for (const key of invalidateKeys) {
          queryClient.invalidateQueries({ queryKey: [...key] });
        }
      }
    },
  });
}
