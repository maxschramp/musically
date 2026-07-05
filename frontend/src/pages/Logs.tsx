// ============================================
// Musically — Logs Page
// Real-time log viewer with service selector,
// live tailing via SSE, and color-coded output
// ============================================

import { useState, useEffect, useRef, useCallback } from 'react';
import {
  ScrollText,
  Pause,
  Play,
  Trash2,
  Wifi,
  WifiOff,
} from 'lucide-react';
import { Card } from '@/components/shared/Card';
import { EmptyState } from '@/components/shared/EmptyState';
import { ErrorState } from '@/components/shared/ErrorState';
import { LoadingSpinner } from '@/components/shared/LoadingSpinner';
import { Button } from '@/components/shared/Button';
import { useApiQuery } from '@/hooks/useApi';

// ============================================
// Types
// ============================================

type ServiceName = 'all' | 'api' | 'nginx' | 'postgres' | 'redis';

interface LogsResponse {
  service: string;
  lines: string[];
  total_lines: number;
}

interface ServiceTab {
  key: ServiceName;
  label: string;
}

const SERVICES: ServiceTab[] = [
  { key: 'all', label: 'All' },
  { key: 'api', label: 'API' },
  { key: 'nginx', label: 'Nginx' },
  { key: 'postgres', label: 'PostgreSQL' },
  { key: 'redis', label: 'Redis' },
];

const LINE_COUNT_OPTIONS = [100, 200, 500, 1000];

// ============================================
// Log Level Color Mapping
// ============================================

function getLogLineClass(line: string): string {
  const upper = line.toUpperCase();
  if (upper.includes('ERROR') || upper.includes('CRITICAL') || upper.includes('FATAL')) {
    return 'text-red-400';
  }
  if (upper.includes('WARNING') || upper.includes('WARN')) {
    return 'text-amber-400';
  }
  if (upper.includes('INFO')) {
    return 'text-gray-200';
  }
  if (upper.includes('DEBUG') || upper.includes('TRACE')) {
    return 'text-gray-500';
  }
  return 'text-gray-400';
}

// ============================================
// Logs Page
// ============================================

export function Logs() {
  const [service, setService] = useState<ServiceName>('all');
  const [lineCount, setLineCount] = useState(200);
  const [paused, setPaused] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const [liveLines, setLiveLines] = useState<string[]>([]);
  const [sseConnected, setSseConnected] = useState(false);
  const [sseError, setSseError] = useState(false);

  const logContainerRef = useRef<HTMLDivElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  // ==========================================
  // Initial log fetch
  // ==========================================

  const {
    data: logsData,
    isLoading: logsLoading,
    isError: logsError,
    error: logsErr,
    refetch: refetchLogs,
  } = useApiQuery<LogsResponse>(
    ['logs', service, lineCount],
    '/logs',
    { service, lines: lineCount },
    { staleTime: 0 },
  );

  // ==========================================
  // SSE live tail
  // ==========================================

  const connectSSE = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    setSseConnected(false);
    setSseError(false);

    const es = new EventSource(`/api/logs/stream?service=${service}`);
    eventSourceRef.current = es;

    es.onopen = () => {
      setSseConnected(true);
      setSseError(false);
    };

    es.onmessage = (event) => {
      if (paused) return;
      const text = event.data;
      setLiveLines((prev) => [...prev, text]);
    };

    es.onerror = () => {
      setSseConnected(false);
      setSseError(true);
      // EventSource will auto-reconnect; if it fails permanently, close
      // and we let the error state show.
    };
  }, [service, paused]);

  // Connect / reconnect SSE when service or paused state changes
  useEffect(() => {
    if (!paused) {
      connectSSE();
    } else {
      // Close SSE when paused
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
      setSseConnected(false);
    }

    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
    };
  }, [connectSSE, paused]);

  // ==========================================
  // Derived state
  // ==========================================

  // Merge fetched lines + live lines
  const fetchedLines = logsData?.lines ?? [];
  const allLines = [...fetchedLines, ...liveLines];

  // ==========================================
  // Auto-scroll
  // ==========================================

  useEffect(() => {
    if (autoScroll && logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [allLines, autoScroll]);

  // ==========================================
  // Actions
  // ==========================================

  const handleServiceChange = (svc: ServiceName) => {
    setService(svc);
    setLiveLines([]);
    setSseError(false);
  };

  const handleLineCountChange = (count: number) => {
    setLineCount(count);
    setLiveLines([]);
  };

  const handleTogglePause = () => {
    setPaused((prev) => !prev);
  };

  const handleToggleAutoScroll = () => {
    setAutoScroll((prev) => !prev);
  };

  const handleClear = () => {
    setLiveLines([]);
  };

  // ==========================================
  // Render helpers
  // ==========================================

  const showEmpty =
    !logsLoading && !logsError && allLines.length === 0 && !sseConnected;

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="font-display text-xl text-ink tracking-tight">
            Logs
          </h2>
          <p className="text-sm text-body-muted mt-1">
            Real-time log viewer for all Musically services.
          </p>
        </div>

        {/* SSE connection badge */}
        <div className="flex items-center gap-2">
          {sseConnected ? (
            <span className="inline-flex items-center gap-1.5 text-xs font-medium text-deep-green">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-deep-green opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-deep-green" />
              </span>
              Live
            </span>
          ) : sseError ? (
            <span className="inline-flex items-center gap-1.5 text-xs font-medium text-coral">
              <WifiOff className="w-3.5 h-3.5" />
              Disconnected
            </span>
          ) : !paused ? (
            <span className="inline-flex items-center gap-1.5 text-xs font-medium text-muted">
              <Wifi className="w-3.5 h-3.5" />
              Connecting…
            </span>
          ) : null}
        </div>
      </div>

      {/* Service Tabs */}
      <div className="flex gap-1 overflow-x-auto pb-1">
        {SERVICES.map((tab) => (
          <button
            key={tab.key}
            onClick={() => handleServiceChange(tab.key)}
            className={`shrink-0 px-4 py-2 text-sm font-medium rounded-sm transition-colors duration-150 cursor-pointer ${
              service === tab.key
                ? 'bg-primary text-on-primary'
                : 'bg-soft-stone text-ink hover:bg-hairline'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Controls Bar */}
      <Card padding="sm">
        <div className="flex flex-wrap items-center gap-3">
          {/* Line count selector */}
          <div className="flex items-center gap-1">
            <span className="text-xs text-body-muted mr-1">Lines:</span>
            {LINE_COUNT_OPTIONS.map((count) => (
              <button
                key={count}
                onClick={() => handleLineCountChange(count)}
                className={`px-2 py-1 text-xs rounded-sm transition-colors cursor-pointer ${
                  lineCount === count
                    ? 'bg-primary text-on-primary'
                    : 'bg-soft-stone text-ink hover:bg-hairline'
                }`}
              >
                {count}
              </button>
            ))}
          </div>

          {/* Divider */}
          <span className="w-px h-5 bg-border-light hidden sm:block" />

          {/* Pause / Resume */}
          <Button
            variant="ghost"
            size="sm"
            leftIcon={paused ? <Play className="w-4 h-4" /> : <Pause className="w-4 h-4" />}
            onClick={handleTogglePause}
          >
            {paused ? 'Resume' : 'Pause'}
          </Button>

          {/* Auto-scroll toggle */}
          <Button
            variant="ghost"
            size="sm"
            onClick={handleToggleAutoScroll}
          >
            <span className={`inline-block w-2 h-2 rounded-full mr-1.5 ${autoScroll ? 'bg-deep-green' : 'bg-muted'}`} />
            Auto-scroll {autoScroll ? 'On' : 'Off'}
          </Button>

          {/* Clear */}
          <Button
            variant="ghost"
            size="sm"
            leftIcon={<Trash2 className="w-4 h-4" />}
            onClick={handleClear}
          >
            Clear
          </Button>

          {/* Line count indicator */}
          <span className="ml-auto text-xs text-body-muted">
            {allLines.length.toLocaleString()} lines
            {logsData?.total_lines !== undefined && logsData.total_lines > allLines.length && (
              <span> of {logsData.total_lines.toLocaleString()}</span>
            )}
          </span>
        </div>
      </Card>

      {/* Log Display Area */}
      <Card padding="none" className="overflow-hidden">
        {/* Loading state */}
        {logsLoading && (
          <div className="flex items-center justify-center py-24" style={{ backgroundColor: '#1a1a2e' }}>
            <LoadingSpinner size="md" label="Loading logs…" />
          </div>
        )}

        {/* Error state */}
        {logsError && !logsLoading && (
          <ErrorState
            title="Failed to load logs"
            message={logsErr?.message ?? 'Could not fetch log data. The backend may be unavailable.'}
            onRetry={() => {
              setLiveLines([]);
              refetchLogs();
            }}
          />
        )}

        {/* Empty state */}
        {showEmpty && (
          <EmptyState
            icon={<ScrollText className="w-16 h-16" />}
            title="No logs available"
            description={`No log entries found for the ${service === 'all' ? 'selected' : service} service yet. Start the service to see its logs here.`}
          />
        )}

        {/* Log lines */}
        {!logsLoading && allLines.length > 0 && (
          <div
            ref={logContainerRef}
            className="overflow-auto font-mono text-sm leading-relaxed p-4"
            style={{
              backgroundColor: '#1a1a2e',
              maxHeight: 'calc(100vh - 380px)',
              minHeight: '400px',
            }}
          >
            {allLines.map((line, i) => (
              <div
                key={i}
                className={`whitespace-pre-wrap break-all ${getLogLineClass(line)}`}
              >
                {line}
              </div>
            ))}
          </div>
        )}

        {/* SSE error banner (non-blocking) */}
        {sseError && !logsLoading && allLines.length > 0 && (
          <div className="flex items-center justify-between gap-3 px-4 py-2 bg-coral/10 border-t border-coral/20">
            <div className="flex items-center gap-2 text-sm text-coral">
              <WifiOff className="w-4 h-4" />
              <span>Live feed disconnected. Retrying…</span>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setSseError(false);
                connectSSE();
              }}
            >
              Reconnect
            </Button>
          </div>
        )}
      </Card>
    </div>
  );
}
