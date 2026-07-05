// ============================================
// Musically — Tasks Page
// Background task status table with manual triggers
// Sonarr/Radarr-style task monitoring
// ============================================

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { RefreshCw, Play, CheckCircle2, XCircle, Clock, MinusCircle, Loader2, Timer } from 'lucide-react';
import { Card } from '@/components/shared/Card';
import { EmptyState } from '@/components/shared/EmptyState';
import { ErrorState } from '@/components/shared/ErrorState';
import { Button } from '@/components/shared/Button';
import { useApiQuery } from '@/hooks/useApi';
import { apiClient } from '@/api/client';
import { formatRelativeTime, formatTimeUntil } from '@/utils/format';
import type { Task, TaskTriggerResponse, TaskStatus } from '@/types';

// ============================================
// Task Name Mapping
// ============================================

const TASK_NAME_MAP: Record<string, string> = {
  lastfm_sync: 'LastFM Sync',
  download_dispatcher: 'Download Dispatcher',
  spotify_playlist_sync: 'Spotify Playlist Sync',
  stalled_retry: 'Stalled Album Retry',
  watch_folder: 'Watch Folder',
  artwork_cache: 'Artwork Cache',
  mb_enrichment: 'MusicBrainz Enrichment',
  library_import: 'Library Import',
  cleanup: 'Cleanup',
};

function displayTaskName(taskName: string): string {
  return TASK_NAME_MAP[taskName] ?? taskName.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

// ============================================
// Status Indicator
// ============================================

const statusConfig: Record<TaskStatus, { dot: string; label: string; icon: React.ReactNode }> = {
  completed: {
    dot: 'bg-green-500',
    label: 'Completed',
    icon: <CheckCircle2 className="w-4 h-4 text-green-500" />,
  },
  running: {
    dot: 'bg-yellow-500',
    label: 'Running',
    icon: <Loader2 className="w-4 h-4 text-yellow-500 animate-spin" />,
  },
  failed: {
    dot: 'bg-red-500',
    label: 'Failed',
    icon: <XCircle className="w-4 h-4 text-red-500" />,
  },
  never_run: {
    dot: 'bg-gray-300',
    label: 'Never Run',
    icon: <MinusCircle className="w-4 h-4 text-gray-300" />,
  },
};

// ============================================
// Task Row
// ============================================

interface TaskRowProps {
  task: Task;
}

function TaskRow({ task }: TaskRowProps) {
  const queryClient = useQueryClient();
  const config = statusConfig[task.status];

  const triggerMutation = useMutation<TaskTriggerResponse, Error, void>({
    mutationFn: () => apiClient.post(`/tasks/${task.task_name}/trigger`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
    },
  });

  return (
    <div className="flex items-center gap-4 py-3 px-4 rounded-sm hover:bg-soft-stone/30 transition-colors">
      {/* Status indicator */}
      <div className="shrink-0">
        {config.icon}
      </div>

      {/* Task info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <p className="text-sm font-medium text-ink">
            {displayTaskName(task.task_name)}
          </p>
          <span className={`inline-block w-2 h-2 rounded-full ${config.dot}`} />
        </div>
        <div className="flex items-center gap-3 mt-0.5">
          <span className="text-xs text-body-muted">
            {task.last_run_at ? formatRelativeTime(task.last_run_at) : 'Never'}
          </span>
          {task.next_scheduled_at && (
            <span className="text-xs text-muted flex items-center gap-1">
              <Timer className="w-3 h-3" />
              Next: {formatTimeUntil(task.next_scheduled_at)}
            </span>
          )}{task.last_result && (
            <span className="text-xs text-muted truncate max-w-[300px]">
              {task.last_result}
            </span>
          )}
        </div>
      </div>

      {/* Trigger button */}
      <Button
        variant="ghost"
        size="sm"
        leftIcon={<Play className="w-3.5 h-3.5" />}
        onClick={() => triggerMutation.mutate()}
        loading={triggerMutation.isPending}
        disabled={triggerMutation.isPending}
        className="shrink-0"
      >
        Trigger
      </Button>
    </div>
  );
}

// ============================================
// Tasks Page
// ============================================

export function Tasks() {
  const {
    data: tasks,
    isLoading,
    isError,
    error,
    refetch,
  } = useApiQuery<Task[]>(
    ['tasks'],
    '/tasks',
    undefined,
    {
      refetchInterval: 10_000, // Auto-refresh every 10 seconds
    },
  );

  const errorMessage = error?.message ?? 'Failed to load tasks.';

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-display text-xl text-ink tracking-tight">
            Tasks
          </h2>
          <p className="text-sm text-body-muted mt-1">
            Monitor and trigger background tasks.
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          leftIcon={<RefreshCw className="w-4 h-4" />}
          onClick={() => refetch()}
          loading={isLoading}
        >
          Refresh
        </Button>
      </div>

      {/* Loading State */}
      {isLoading && (
        <Card padding="none">
          <div className="divide-y divide-card-border">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="flex items-center gap-4 py-3 px-4 animate-pulse">
                <div className="w-4 h-4 rounded-full bg-hairline" />
                <div className="flex-1 space-y-2">
                  <div className="h-4 bg-hairline rounded w-1/3" />
                  <div className="h-3 bg-hairline rounded w-1/4" />
                </div>
                <div className="h-8 w-20 bg-hairline rounded" />
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Error State */}
      {isError && !isLoading && (
        <Card padding="lg">
          <ErrorState
            title="Failed to Load Tasks"
            message={errorMessage}
            onRetry={() => refetch()}
          />
        </Card>
      )}

      {/* Empty State */}
      {!isLoading && !isError && tasks && tasks.length === 0 && (
        <Card padding="lg">
          <EmptyState
            icon={<Clock className="w-16 h-16" />}
            title="No Tasks Found"
            description="No background tasks are registered yet. Tasks will appear here once the backend is fully configured."
          />
        </Card>
      )}

      {/* Task List */}
      {!isLoading && !isError && tasks && tasks.length > 0 && (
        <Card padding="none">
          <div className="divide-y divide-card-border">
            {tasks.map((task) => (
              <TaskRow key={task.task_name} task={task} />
            ))}
          </div>
        </Card>
      )}

      {/* Legend */}
      {!isLoading && !isError && tasks && tasks.length > 0 && (
        <div className="flex items-center gap-4 text-xs text-muted">
          <span className="flex items-center gap-1.5">
            <CheckCircle2 className="w-3.5 h-3.5 text-green-500" /> Completed
          </span>
          <span className="flex items-center gap-1.5">
            <Loader2 className="w-3.5 h-3.5 text-yellow-500" /> Running
          </span>
          <span className="flex items-center gap-1.5">
            <XCircle className="w-3.5 h-3.5 text-red-500" /> Failed
          </span>
          <span className="flex items-center gap-1.5">
            <MinusCircle className="w-3.5 h-3.5 text-gray-300" /> Never Run
          </span>
        </div>
      )}
    </div>
  );
}
