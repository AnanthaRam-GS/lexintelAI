'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { historyApi } from '../../../lib/api';
import { ErrorMessage, LoadingSpinner } from '../../../components/shared';
import { ProfessionalResultsView } from '../../../components/professional/ProfessionalResultsView';
import type { ProfessionalQueryResponse, QueryHistoryItem } from '../../../lib/types/api';

const ITEMS_PER_PAGE = 3;

export default function ProfessionalHistoryPage() {
  const [historyItems, setHistoryItems] = useState<QueryHistoryItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters & State
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedMode, setSelectedMode] = useState<'all' | 'text' | 'pdf'>('all');
  const [expandedItemId, setExpandedItemId] = useState<number | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [reloadTrigger, setReloadTrigger] = useState(0);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const data = await historyApi.getQueryHistory(50);
        if (!active) return;
        setHistoryItems(data);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : 'Failed to retrieve query history.');
      } finally {
        if (active) setIsLoading(false);
      }
    };
    void load();
    return () => {
      active = false;
    };
  }, [reloadTrigger]);

  // Filtered Items
  const filteredItems = useMemo(() => {
    return historyItems.filter((item) => {
      const matchesSearch =
        !searchTerm.trim() ||
        item.query_text.toLowerCase().includes(searchTerm.toLowerCase()) ||
        (item.generation_backend &&
          item.generation_backend.toLowerCase().includes(searchTerm.toLowerCase()));

      const matchesMode =
        selectedMode === 'all' || item.mode.toLowerCase() === selectedMode.toLowerCase();

      return matchesSearch && matchesMode;
    });
  }, [historyItems, searchTerm, selectedMode]);

  // Client-Side Pagination
  const totalPages = Math.max(1, Math.ceil(filteredItems.length / ITEMS_PER_PAGE));

  const paginatedItems = useMemo(() => {
    const start = (currentPage - 1) * ITEMS_PER_PAGE;
    return filteredItems.slice(start, start + ITEMS_PER_PAGE);
  }, [filteredItems, currentPage]);

  const handlePageChange = (newPage: number) => {
    setCurrentPage(newPage);
    setExpandedItemId(null); // Collapse when paging
  };

  const formatTimestamp = (dateString: string) => {
    try {
      const d = new Date(dateString);
      return d.toLocaleDateString('en-IN', {
        day: 'numeric',
        month: 'short',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return dateString;
    }
  };

  return (
    <div className="space-y-6" data-testid="professional-history-page">
      {/* Heading */}
      <div>
        <span className="text-xs font-bold uppercase tracking-wider text-[var(--color-brass)]">
          Research Audit Trail
        </span>
        <h1 className="font-display text-2xl font-bold tracking-tight text-[var(--color-ink)] sm:text-3xl">
          Query &amp; Document History
        </h1>
        <p className="mt-1 text-sm text-[var(--color-muted)]">
          Historical record of authenticated professional research queries, uploaded brief analyses,
          and preserved AI case briefs.
        </p>
      </div>

      {/* Search & Filter Toolbar */}
      <div className="flex flex-col gap-3 rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-4 shadow-xs sm:flex-row sm:items-center sm:justify-between">
        <div className="flex-1 max-w-md">
          <input
            type="search"
            placeholder="Search past queries or models..."
            value={searchTerm}
            onChange={(e) => {
              setSearchTerm(e.target.value);
              setCurrentPage(1);
            }}
            className="w-full rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-canvas)] px-3.5 py-2 text-xs text-[var(--color-ink)] placeholder-[var(--color-muted)]/60 focus:border-[var(--color-focus)] focus:bg-white focus:outline-none focus:ring-1 focus:ring-[var(--color-focus)]"
          />
        </div>

        <div className="flex items-center gap-2">
          <label htmlFor="mode-filter" className="text-xs font-semibold text-[var(--color-body)]">
            Input Mode:
          </label>
          <select
            id="mode-filter"
            value={selectedMode}
            onChange={(e) => {
              setSelectedMode(e.target.value as 'all' | 'text' | 'pdf');
              setCurrentPage(1);
            }}
            className="rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-canvas)] px-2.5 py-1.5 text-xs text-[var(--color-ink)] focus:outline-none"
          >
            <option value="all">All Modes ({historyItems.length})</option>
            <option value="text">Text Queries</option>
            <option value="pdf">PDF Uploads</option>
          </select>
        </div>
      </div>

      {/* Loading & Error Indicators */}
      {isLoading && (
        <div className="flex h-64 items-center justify-center rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-8">
          <LoadingSpinner size="lg" label="Loading query history audit trail" />
        </div>
      )}

      {error && (
        <ErrorMessage
          variant="inline"
          title="Failed to Load History"
          message={error}
          onRetry={() => {
            setIsLoading(true);
            setReloadTrigger((c) => c + 1);
          }}
        />
      )}

      {/* Empty State */}
      {!isLoading && !error && filteredItems.length === 0 && (
        <div className="rounded-[var(--radius-standard)] border border-dashed border-[var(--color-border)] bg-[var(--color-surface)] p-12 text-center">
          <p className="font-display text-base font-bold text-[var(--color-ink)]">
            No query history entries found
          </p>
          <p className="mt-1 text-xs text-[var(--color-muted)]">
            {searchTerm
              ? 'Try adjusting your search keywords or filters.'
              : 'Submit a text query or upload a brief to create your first analysis.'}
          </p>
        </div>
      )}

      {/* History Items List */}
      {!isLoading && !error && paginatedItems.length > 0 && (
        <div className="space-y-4" data-testid="history-list">
          {paginatedItems.map((item) => {
            const isExpanded = expandedItemId === item.id;
            const isPdf = item.mode.toLowerCase() === 'pdf';

            return (
              <article
                key={item.id}
                className="overflow-hidden rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-xs transition-colors hover:border-[var(--color-brass)]"
                data-testid={`history-item-${item.id}`}
              >
                <div className="p-4 sm:p-5">
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                    <div className="flex items-start gap-3 min-w-0 flex-1">
                      {/* Mode Icon */}
                      <div
                        className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-[var(--radius-compact)] ${
                          isPdf ? 'bg-[#fae9e7] text-[#7c2e28]' : 'bg-[#e8f1fa] text-[#174d85]'
                        }`}
                        title={`Mode: ${item.mode.toUpperCase()}`}
                      >
                        {isPdf ? (
                          <svg
                            className="h-5 w-5"
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                          >
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              strokeWidth={2}
                              d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"
                            />
                          </svg>
                        ) : (
                          <svg
                            className="h-5 w-5"
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                          >
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              strokeWidth={2}
                              d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                            />
                          </svg>
                        )}
                      </div>

                      {/* Query Details */}
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="rounded bg-[var(--color-surface-subtle)] px-2 py-0.5 text-[0.6875rem] font-bold uppercase tracking-wider text-[var(--color-brass)]">
                            {item.mode.toUpperCase()}
                          </span>
                          <span className="text-xs text-[var(--color-muted)]">
                            {formatTimestamp(item.created_at)}
                          </span>
                          {item.generation_backend && (
                            <span className="rounded bg-black/5 px-1.5 py-0.5 font-mono text-[0.625rem] text-[var(--color-muted)]">
                              {item.generation_backend}
                            </span>
                          )}
                        </div>

                        {/* Truncated Query Text */}
                        <p
                          className="mt-2 font-display text-sm font-semibold text-[var(--color-ink)] line-clamp-2"
                          title={item.query_text}
                        >
                          {item.query_text}
                        </p>
                      </div>
                    </div>

                    {/* Expand Action Button */}
                    <div className="sm:self-center">
                      <button
                        type="button"
                        onClick={() => setExpandedItemId(isExpanded ? null : item.id)}
                        aria-expanded={isExpanded}
                        className="cursor-pointer inline-flex items-center gap-1.5 rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-xs font-semibold text-[var(--color-body)] transition-colors hover:border-[var(--color-brass)] hover:text-[var(--color-ink)] focus-visible:outline-2 focus-visible:outline-[var(--color-focus)]"
                      >
                        <span>{isExpanded ? 'Hide Brief' : 'View Stored Brief'}</span>
                        <svg
                          className={`h-3.5 w-3.5 transition-transform duration-[var(--motion-fast)] ${isExpanded ? 'rotate-180' : ''}`}
                          fill="none"
                          stroke="currentColor"
                          viewBox="0 0 24 24"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M19 9l-7 7-7-7"
                          />
                        </svg>
                      </button>
                    </div>
                  </div>
                </div>

                {/* Expandable Stored Result */}
                {isExpanded && (
                  <div className="border-t border-[var(--color-border)] bg-[var(--color-canvas)]/40 p-4 sm:p-6">
                    {item.response_json && 'case_brief' in item.response_json ? (
                      <ProfessionalResultsView
                        result={item.response_json as ProfessionalQueryResponse}
                        queryTitle={item.query_text}
                      />
                    ) : (
                      <div className="rounded-[var(--radius-compact)] bg-white p-4 text-xs text-[var(--color-muted)]">
                        No structured response payload preserved for this entry.
                      </div>
                    )}
                  </div>
                )}
              </article>
            );
          })}

          {/* Client-Side Pagination Controls */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between border-t border-[var(--color-border)] pt-4">
              <span className="text-xs text-[var(--color-muted)]">
                Showing Page <strong className="text-[var(--color-ink)]">{currentPage}</strong> of{' '}
                <strong className="text-[var(--color-ink)]">{totalPages}</strong> (
                {filteredItems.length} total entries)
              </span>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => handlePageChange(currentPage - 1)}
                  disabled={currentPage === 1}
                  className="cursor-pointer rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-xs font-semibold text-[var(--color-body)] transition-colors hover:bg-[var(--color-surface-subtle)] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Previous
                </button>

                <button
                  type="button"
                  onClick={() => handlePageChange(currentPage + 1)}
                  disabled={currentPage === totalPages}
                  className="cursor-pointer rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-xs font-semibold text-[var(--color-body)] transition-colors hover:bg-[var(--color-surface-subtle)] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
