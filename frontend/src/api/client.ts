// ============================================
// Musically — API Client
// Fetch wrapper with base URL /api, error handling
// ============================================

import type { ApiError } from '@/types';

class ApiClientError extends Error {
  status: number;
  detail: string | undefined;

  constructor(status: number, message: string, detail?: string) {
    super(message);
    this.name = 'ApiClientError';
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  params?: Record<string, string | number | boolean | undefined>,
): Promise<T> {
  const url = new URL(`/api${path}`, window.location.origin);

  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null) {
        url.searchParams.set(key, String(value));
      }
    }
  }

  const headers: Record<string, string> = {
    'Accept': 'application/json',
  };

  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
  }

  const response = await fetch(url.toString(), {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    let errorMessage = `Request failed with status ${response.status}`;
    let errorDetail: string | undefined;

    try {
      const errorBody: ApiError = await response.json();
      errorMessage = errorBody.message || errorMessage;
      errorDetail = errorBody.detail;
    } catch {
      // If parsing fails, use the status text
      errorMessage = response.statusText || errorMessage;
    }

    throw new ApiClientError(response.status, errorMessage, errorDetail);
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return undefined as T;
  }

  const data: T = await response.json();
  return data;
}

export const apiClient = {
  get<T>(path: string, params?: Record<string, string | number | boolean | undefined>): Promise<T> {
    return request<T>('GET', path, undefined, params);
  },

  post<T>(path: string, body?: unknown): Promise<T> {
    return request<T>('POST', path, body);
  },

  put<T>(path: string, body?: unknown): Promise<T> {
    return request<T>('PUT', path, body);
  },

  delete<T>(path: string): Promise<T> {
    return request<T>('DELETE', path);
  },
};

export { ApiClientError };
