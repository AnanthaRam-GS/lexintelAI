'use client';

import React, { useState } from 'react';
import type { ProfessionalPrecedent } from '../lib/types/api';

export interface CitationCardProps {
  precedent: ProfessionalPrecedent;
  className?: string;
}

export function CitationCard({ precedent, className = '' }: CitationCardProps) {
  const [isExcerptExpanded, setIsExcerptExpanded] = useState(false);

  const relevancePct =
    precedent.relevance_score == null ? null : Math.round(precedent.relevance_score * 100);

  const hasPinpoints =
    precedent.page_start != null ||
    precedent.page_end != null ||
    precedent.paragraph_start != null ||
    precedent.paragraph_end != null;

  return (
    <article
      className={`group rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-4 shadow-sm transition-all duration-[var(--motion-fast)] hover:border-[var(--color-brass)] hover:shadow-[var(--shadow-component)] sm:p-5 ${className}`}
      data-testid="citation-card"
      aria-label={`Precedent: ${precedent.case_name}`}
    >
      {/* Top Header: Case Title and Relevance Score */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 flex-1">
          <h3 className="font-display text-[1.0625rem] font-bold leading-snug text-[var(--color-ink)] transition-colors group-hover:text-[var(--color-brass-hover)]">
            {precedent.case_name}
          </h3>

          <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-[var(--color-muted)]">
            {precedent.court && (
              <span className="font-medium text-[var(--color-body)]">{precedent.court}</span>
            )}
            {precedent.court && precedent.year && <span aria-hidden="true">·</span>}
            {precedent.year && <span className="font-semibold">{precedent.year}</span>}
            {precedent.document_id && (
              <>
                <span aria-hidden="true">·</span>
                <span className="rounded bg-[var(--color-surface-subtle)] px-1.5 py-0.5 font-mono text-[0.6875rem] text-[var(--color-muted)]">
                  {precedent.document_id}
                </span>
              </>
            )}
          </div>
        </div>

        {/* Relevance: the reranker's score for this precedent, or "not available" */}
        {relevancePct == null ? (
          <div
            className="flex shrink-0 items-center self-start rounded-full border border-[var(--color-border)] bg-[var(--color-canvas)] px-2.5 py-1 text-xs text-[var(--color-muted)]"
            title="The reranker did not score this precedent."
          >
            Relevance not available
          </div>
        ) : (
          <div
            className="flex shrink-0 items-center gap-2 self-start rounded-full border border-[var(--color-border)] bg-[var(--color-canvas)] px-2.5 py-1 text-xs"
            title="Reranker relevance score (0-100)"
          >
            <div className="h-1.5 w-10 overflow-hidden rounded-full bg-black/10">
              <div
                className="h-full bg-[var(--color-brass)] transition-all duration-300"
                style={{ width: `${relevancePct}%` }}
              />
            </div>
            <span className="font-semibold text-[var(--color-ink)]">{relevancePct}%</span>
            <span className="text-[0.6875rem] text-[var(--color-muted)] uppercase tracking-wider">
              Relevance
            </span>
          </div>
        )}
      </div>

      {/* Excerpt Section */}
      {precedent.excerpt && (
        <div className="mt-3.5 rounded-[var(--radius-compact)] border-l-2 border-[var(--color-brass)] bg-[var(--color-canvas)]/60 px-3.5 py-2.5">
          <p
            className={`text-[0.875rem] leading-relaxed text-[var(--color-body)] italic ${
              !isExcerptExpanded ? 'line-clamp-3' : ''
            }`}
          >
            &ldquo;{precedent.excerpt}&rdquo;
          </p>
          {precedent.chunk_id && (
            <p className="mt-1 text-[0.6875rem] text-[var(--color-muted)]">
              Excerpt from{' '}
              <span className="font-mono" data-testid="excerpt-chunk-id">
                {precedent.chunk_id}
              </span>
            </p>
          )}
          {precedent.excerpt.length > 180 && (
            <button
              type="button"
              onClick={() => setIsExcerptExpanded((prev) => !prev)}
              className="mt-1 inline-flex text-xs font-semibold text-[var(--color-brass)] hover:underline focus-visible:outline-2 focus-visible:outline-[var(--color-focus)]"
            >
              {isExcerptExpanded ? 'Show less' : 'Read full excerpt'}
            </button>
          )}
        </div>
      )}

      {/* Footer: Pinpoints and Source Link */}
      <footer className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-[var(--color-border)] pt-3 text-xs">
        {hasPinpoints ? (
          <div className="flex flex-wrap items-center gap-2 text-[var(--color-muted)]">
            <span className="font-medium text-[var(--color-body)]">Pinpoint:</span>
            {precedent.page_start != null && (
              <span className="rounded bg-[var(--color-surface-subtle)] px-1.5 py-0.5">
                {precedent.page_end != null && precedent.page_end !== precedent.page_start
                  ? `pp. ${precedent.page_start}–${precedent.page_end}`
                  : `p. ${precedent.page_start}`}
              </span>
            )}
            {precedent.paragraph_start != null && (
              <span className="rounded bg-[var(--color-surface-subtle)] px-1.5 py-0.5">
                ¶ {precedent.paragraph_start}
                {precedent.paragraph_end != null &&
                precedent.paragraph_end !== precedent.paragraph_start
                  ? `–${precedent.paragraph_end}`
                  : ''}
              </span>
            )}
          </div>
        ) : (
          <span />
        )}

        {precedent.source_url && (
          <a
            href={precedent.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 font-semibold text-[var(--color-info-foreground)] transition-colors hover:text-[var(--color-ink)] hover:underline focus-visible:outline-2 focus-visible:outline-[var(--color-focus)]"
          >
            <span>View Judgment</span>
            <svg
              className="h-3.5 w-3.5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"
              />
            </svg>
          </a>
        )}
      </footer>
    </article>
  );
}
