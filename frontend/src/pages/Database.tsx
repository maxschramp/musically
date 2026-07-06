// ============================================
// Musically — Database Page
// Read-only database browser with table list and
// paginated row viewer
// ============================================

import { useState } from 'react';
import { Database as DatabaseIcon, Table2, ChevronLeft, ChevronRight } from 'lucide-react';
import { Card } from '@/components/shared/Card';
import { EmptyState } from '@/components/shared/EmptyState';
import { ErrorState } from '@/components/shared/ErrorState';
import { LoadingSpinner } from '@/components/shared/LoadingSpinner';
import { useApiQuery } from '@/hooks/useApi';
import type { DatabaseTable, DatabaseTablesResponse, DatabaseTableRows } from '@/types';

// ============================================
// Helpers
// ============================================

/** Truncate a value for display. UUIDs get 8 chars, long text gets 50. */
function truncateValue(value: unknown): string {
  if (value === null || value === undefined) return 'NULL';
  const str = String(value);

  // UUID detection: 36-char hex with dashes
  if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(str)) {
    return str.slice(0, 8) + '…';
  }

  if (str.length > 50) {
    return str.slice(0, 50) + '…';
  }

  return str;
}

// ============================================
// Database Page
// ============================================

export function Database() {
  const [selectedTable, setSelectedTable] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const limit = 50;

  // Fetch table list
  const {
    data: tablesResponse,
    isLoading: tablesLoading,
    isError: tablesError,
    error: tablesErr,
    refetch: refetchTables,
  } = useApiQuery<DatabaseTablesResponse>(
    ['database-tables'],
    '/database/tables',
  );

  const tables: DatabaseTable[] = tablesResponse?.tables ?? [];

  // Fetch rows for selected table
  const {
    data: tableData,
    isLoading: rowsLoading,
    isError: rowsError,
    error: rowsErr,
    refetch: refetchRows,
  } = useApiQuery<DatabaseTableRows>(
    ['database-rows', selectedTable, page],
    `/database/table/${selectedTable}`,
    { page, limit },
    {
      enabled: !!selectedTable, // Only fetch when a table is selected
    },
  );

  const handleTableSelect = (tableName: string) => {
    setSelectedTable(tableName);
    setPage(1);
  };

  const totalPages = tableData ? Math.ceil(tableData.total / limit) : 0;

  const tablesErrorMsg = tablesErr?.message ?? 'Failed to load tables.';
  const rowsErrorMsg = rowsErr?.message ?? 'Failed to load rows.';

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div>
        <h2 className="font-display text-xl text-ink tracking-tight">
          Database
        </h2>
        <p className="text-sm text-body-muted mt-1">
          Browse database tables and their contents.
        </p>
      </div>

      {/* Mobile: Table Tabs */}
      <div className="lg:hidden overflow-x-auto -mx-4 px-4">
        {tablesLoading && (
          <div className="flex gap-2 pb-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="h-9 w-24 bg-hairline rounded-pill animate-pulse shrink-0" />
            ))}
          </div>
        )}
        {tablesError && !tablesLoading && (
          <ErrorState
            title="Failed to Load Tables"
            message={tablesErrorMsg}
            onRetry={() => refetchTables()}
          />
        )}
        {!tablesLoading && !tablesError && tables && (
          <div className="flex gap-2 pb-2">
            {tables.map((table) => (
              <button
                key={table.table_name}
                type="button"
                onClick={() => handleTableSelect(table.table_name)}
                className={`shrink-0 px-4 py-2 rounded-pill text-sm font-medium transition-colors duration-150 cursor-pointer ${
                  selectedTable === table.table_name
                    ? 'bg-coral text-white'
                    : 'bg-soft-stone text-ink hover:bg-hairline'
                }`}
              >
                {table.table_name}
                <span className="ml-1.5 text-xs opacity-70">
                  ({table.row_count})
                </span>
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="flex gap-6">
        {/* Desktop: Table Sidebar */}
        <div className="hidden lg:block w-56 shrink-0">
          <Card padding="none">
            <div className="px-4 py-3 border-b border-card-border">
              <p className="text-xs font-medium text-muted uppercase tracking-wider">
                Tables
              </p>
            </div>

            {tablesLoading && (
              <div className="p-4 space-y-3">
                {Array.from({ length: 6 }).map((_, i) => (
                  <div key={i} className="h-8 bg-hairline rounded animate-pulse" />
                ))}
              </div>
            )}

            {tablesError && !tablesLoading && (
              <div className="p-4">
                <ErrorState
                  title="Error"
                  message={tablesErrorMsg}
                  onRetry={() => refetchTables()}
                  className="py-8"
                />
              </div>
            )}

            {!tablesLoading && !tablesError && tables && tables.length === 0 && (
              <div className="p-4">
                <EmptyState
                  icon={<DatabaseIcon className="w-10 h-10" />}
                  title="No Tables"
                  description="No database tables found."
                />
              </div>
            )}

            {!tablesLoading && !tablesError && tables && tables.length > 0 && (
              <div className="py-1">
                {tables.map((table) => (
                  <button
                    key={table.table_name}
                    type="button"
                    onClick={() => handleTableSelect(table.table_name)}
                    className={`w-full flex items-center justify-between px-4 py-2.5 text-sm transition-colors duration-150 cursor-pointer text-left ${
                      selectedTable === table.table_name
                        ? 'bg-soft-stone text-coral font-medium border-l-[3px] border-coral pl-3.5'
                        : 'text-ink hover:bg-soft-stone/50 border-l-[3px] border-transparent pl-3.5'
                    }`}
                  >
                    <span className="truncate">{table.table_name}</span>
                    <span className="text-xs text-muted ml-2 shrink-0">
                      {table.row_count}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </Card>
        </div>

        {/* Data Panel */}
        <div className="flex-1 min-w-0">
          {!selectedTable && (
            <Card padding="lg">
              <EmptyState
                icon={<Table2 className="w-16 h-16" />}
                title="Select a Table"
                description="Choose a table from the sidebar or tabs above to view its contents."
              />
            </Card>
          )}

          {selectedTable && rowsLoading && (
            <Card padding="lg">
              <LoadingSpinner size="lg" label={`Loading ${selectedTable}…`} className="py-16" />
            </Card>
          )}

          {selectedTable && rowsError && !rowsLoading && (
            <Card padding="lg">
              <ErrorState
                title="Failed to Load Rows"
                message={rowsErrorMsg}
                onRetry={() => refetchRows()}
              />
            </Card>
          )}

          {selectedTable && !rowsLoading && !rowsError && tableData && (
            <Card padding="none">
              {/* Table header info */}
              <div className="px-4 py-3 border-b border-card-border flex items-center justify-between">
                <p className="text-sm font-medium text-ink">
                  {tableData.table_name}
                  <span className="text-xs text-muted ml-2">
                    ({tableData.total} row{tableData.total !== 1 ? 's' : ''})
                  </span>
                </p>
                {totalPages > 1 && (
                  <span className="text-xs text-muted">
                    Page {tableData.page} of {totalPages}
                  </span>
                )}
              </div>

              {/* Data table */}
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-card-border bg-soft-stone/50">
                      {tableData.columns.map((col) => (
                        <th
                          key={col}
                          className="px-4 py-2.5 text-left text-xs font-medium text-muted uppercase tracking-wider whitespace-nowrap"
                        >
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {tableData.rows.length === 0 ? (
                      <tr>
                        <td
                          colSpan={tableData.columns.length}
                          className="px-4 py-12 text-center text-muted"
                        >
                          No rows in this table.
                        </td>
                      </tr>
                    ) : (
                      tableData.rows.map((row, rowIdx) => (
                        <tr
                          key={rowIdx}
                          className="border-b border-card-border hover:bg-soft-stone/30 transition-colors"
                        >
                          {tableData.columns.map((col) => {
                            const rawValue = row[col];
                            const display = truncateValue(rawValue);
                            const fullValue = rawValue === null || rawValue === undefined
                              ? 'NULL'
                              : String(rawValue);

                            return (
                              <td
                                key={col}
                                className="px-4 py-2 text-ink whitespace-nowrap max-w-[200px] truncate"
                                title={fullValue.length > 50 ? fullValue : undefined}
                              >
                                <span
                                  className={
                                    rawValue === null || rawValue === undefined
                                      ? 'text-muted italic text-xs'
                                      : ''
                                  }
                                >
                                  {display}
                                </span>
                              </td>
                            );
                          })}
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="flex items-center justify-center gap-2 px-4 py-3 border-t border-card-border">
                  <button
                    type="button"
                    disabled={page <= 1}
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    className="inline-flex items-center gap-1 px-2 py-1 text-sm rounded-sm border border-hairline text-ink hover:bg-soft-stone disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                  >
                    <ChevronLeft className="w-4 h-4" />
                    Prev
                  </button>
                  <span className="text-sm text-muted">
                    {tableData.page} / {totalPages}
                  </span>
                  <button
                    type="button"
                    disabled={page >= totalPages}
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                    className="inline-flex items-center gap-1 px-2 py-1 text-sm rounded-sm border border-hairline text-ink hover:bg-soft-stone disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                  >
                    Next
                    <ChevronRight className="w-4 h-4" />
                  </button>
                </div>
              )}
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
