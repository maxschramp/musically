// ============================================
// Musically — Server-Sent Events Hook
// Connects to /api/events and auto-invalidates
// TanStack Query caches based on event types.
// ============================================

import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';

// ============================================
// Event Types
// ============================================

interface QueueChangedEvent {
  album_id: string;
  action: 'approved' | 'promoted' | 'rejected';
}

interface AlbumStatusEvent {
  album_id: string;
  status: 'downloading' | 'downloaded' | 'stalled' | 'queued';
}

interface TaskCompletedEvent {
  task_name: string;
  status: 'completed' | 'failed';
}

// ============================================
// Query keys to invalidate per event type
// ============================================

const INVALIDATION_MAP: Record<string, readonly unknown[][]> = {
  queue_changed: [['queue'], ['queue', 'pipeline']],
  album_status: [['queue'], ['queue', 'pipeline']],
  task_completed: [['tasks']],
};

const RECONNECT_DELAY_MS = 3000;

// ============================================
// Hook
// ============================================

export function useEvents() {
  const queryClient = useQueryClient();
  const [isConnected, setIsConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    // SSR guard — EventSource only exists in the browser
    if (typeof window === 'undefined' || typeof EventSource === 'undefined') {
      return;
    }

    let destroyed = false;

    function connect() {
      if (destroyed) return;

      // Clean up any existing connection
      esRef.current?.close();

      const es = new EventSource('/api/events');
      esRef.current = es;

      es.onopen = () => {
        if (!destroyed) setIsConnected(true);
      };

      es.onerror = () => {
        if (destroyed) return;
        setIsConnected(false);
        // EventSource auto-reconnects, but we add our own delay
        // by closing and re-opening manually after a pause
        es.close();
        esRef.current = null;
        reconnectTimerRef.current = setTimeout(connect, RECONNECT_DELAY_MS);
      };

      // ============================================
      // Event Handlers
      // ============================================

      es.addEventListener('queue_changed', (e: MessageEvent) => {
        try {
          const data: QueueChangedEvent = JSON.parse(e.data);
          console.debug('[SSE] queue_changed:', data);
        } catch {
          // Ignore parse errors
        }
        invalidateForEvent('queue_changed');
      });

      es.addEventListener('album_status', (e: MessageEvent) => {
        try {
          const data: AlbumStatusEvent = JSON.parse(e.data);
          console.debug('[SSE] album_status:', data);
        } catch {
          // Ignore parse errors
        }
        invalidateForEvent('album_status');
      });

      es.addEventListener('task_completed', (e: MessageEvent) => {
        try {
          const data: TaskCompletedEvent = JSON.parse(e.data);
          console.debug('[SSE] task_completed:', data);
        } catch {
          // Ignore parse errors
        }
        invalidateForEvent('task_completed');
      });
    }

    function invalidateForEvent(eventType: string) {
      const keys = INVALIDATION_MAP[eventType];
      if (!keys) return;
      for (const key of keys) {
        queryClient.invalidateQueries({ queryKey: [...key] });
      }
    }

    connect();

    return () => {
      destroyed = true;
      esRef.current?.close();
      esRef.current = null;
      if (reconnectTimerRef.current !== null) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    };
  }, [queryClient]);

  return { isConnected };
}
