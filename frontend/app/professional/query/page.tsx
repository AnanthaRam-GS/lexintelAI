'use client';

import React, { useState } from 'react';
import { queryApi } from '../../../lib/api';
import { ErrorMessage, LoadingSpinner } from '../../../components/shared';
import { ProfessionalResultsView } from '../../../components/professional/ProfessionalResultsView';
import type { ProfessionalQueryResponse } from '../../../lib/types/api';

const EXAMPLE_QUERIES = [
  {
    title: 'Circumstantial Evidence & Murder',
    text: 'Circumstantial evidence murder case bail grounds under Section 302 IPC / Section 103 BNS where weapon recovery lacks independent pancha witnesses.',
  },
  {
    title: 'Bail on Medical & Delay Grounds',
    text: 'Regular bail application under Section 437 CrPC / Section 480 BNSS for non-bailable offence relying on continuous hospitalization and completed investigation.',
  },
  {
    title: 'Quashing Commercial Dispute',
    text: 'Petition under Section 482 CrPC / Section 528 BNSS to quash FIR where commercial dispute regarding breach of contract was dishonestly converted into IPC 420/406 cheating.',
  },
];

export default function ProfessionalQueryPage() {
  const [queryText, setQueryText] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [errorState, setErrorState] = useState<{ title: string; message: string; detail?: string } | null>(null);
  const [result, setResult] = useState<ProfessionalQueryResponse | null>(null);
  const [submittedQuery, setSubmittedQuery] = useState('');

  const handleExecuteQuery = async (textToRun: string) => {
    const trimmed = textToRun.trim();
    if (!trimmed) {
      setErrorState({
        title: 'Empty Query',
        message: 'Please enter a legal query, factual background, or statutory question to begin analysis.',
      });
      return;
    }

    setErrorState(null);
    setIsLoading(true);
    setSubmittedQuery(trimmed);

    try {
      const response = await queryApi.submitText(trimmed);
      setResult(response);
    } catch (err) {
      setErrorState({
        title: 'Query Analysis Failed',
        message: err instanceof Error ? err.message : 'Unable to complete legal analysis.',
        detail: (err as { detail?: string })?.detail,
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    handleExecuteQuery(queryText);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault();
      handleExecuteQuery(queryText);
    }
  };

  const handleReset = () => {
    setResult(null);
    setQueryText('');
    setSubmittedQuery('');
    setErrorState(null);
  };

  return (
    <div className="space-y-6" data-testid="professional-query-page">
      {/* Page Heading */}
      <div>
        <span className="text-xs font-bold uppercase tracking-wider text-[var(--color-brass)]">
          Legal Research Workbench
        </span>
        <h1 className="font-display text-2xl font-bold tracking-tight text-[var(--color-ink)] sm:text-3xl">
          Statutory &amp; Precedent Text Query
        </h1>
        <p className="mt-1 text-sm text-[var(--color-muted)]">
          Submit fact patterns, legal propositions, or questions to extract relevant IPC/BNS provisions, retrieved Supreme Court precedents, and a complete structured case brief.
        </p>
      </div>

      {/* Results View or Query Form */}
      {result ? (
        <ProfessionalResultsView
          result={result}
          queryTitle={submittedQuery}
          onReset={handleReset}
        />
      ) : (
        <div className="space-y-6">
          {/* Query Composer Card */}
          <section
            aria-label="Text query form"
            className="rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-6 shadow-xs sm:p-8"
          >
            {errorState && (
              <div className="mb-6">
                <ErrorMessage
                  variant="inline"
                  title={errorState.title}
                  message={errorState.message}
                  technicalDetail={errorState.detail}
                  onRetry={() => handleExecuteQuery(queryText)}
                />
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <div className="flex items-center justify-between">
                  <label
                    htmlFor="legal-query-input"
                    className="block text-xs font-bold uppercase tracking-wider text-[var(--color-body)]"
                  >
                    Enter Legal Proposition or Fact Pattern
                  </label>
                  <span className="text-xs text-[var(--color-muted)]">
                    Press <kbd className="rounded border border-black/20 bg-black/5 px-1 font-mono text-[0.6875rem]">⌘+Enter</kbd> to submit
                  </span>
                </div>

                <textarea
                  id="legal-query-input"
                  rows={5}
                  value={queryText}
                  onChange={(e) => setQueryText(e.target.value)}
                  onKeyDown={handleKeyDown}
                  disabled={isLoading}
                  placeholder="e.g. Accused charged under Section 302 IPC based purely on circumstantial evidence and recovery of weapon without independent witnesses. Seeks regular bail citing parity and delay in trial..."
                  className="mt-2 w-full rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-canvas)] p-3.5 text-sm text-[var(--color-ink)] placeholder-[var(--color-muted)]/60 transition-colors focus:border-[var(--color-focus)] focus:bg-white focus:outline-none focus:ring-2 focus:ring-[var(--color-focus)]/20 disabled:opacity-60"
                />
              </div>

              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between pt-2">
                <span className="text-xs text-[var(--color-muted)]">
                  {queryText.length} characters
                </span>

                <button
                  type="submit"
                  disabled={isLoading || !queryText.trim()}
                  className="cursor-pointer inline-flex items-center justify-center gap-2 rounded-[var(--radius-compact)] bg-[var(--color-brass)] px-6 py-2.5 text-sm font-semibold text-white shadow-xs transition-colors hover:bg-[var(--color-brass-hover)] active:bg-[var(--color-brass-active)] focus-visible:outline-2 focus-visible:outline-[var(--color-focus)] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {isLoading ? (
                    <>
                      <LoadingSpinner size="sm" label="Analyzing legal query" />
                      <span>Synthesizing Legal Brief...</span>
                    </>
                  ) : (
                    <>
                      <span>Execute Legal Research</span>
                      <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
                      </svg>
                    </>
                  )}
                </button>
              </div>
            </form>
          </section>

          {/* Preset Example Queries */}
          <section aria-label="Example queries" className="space-y-3">
            <h2 className="text-xs font-bold uppercase tracking-wider text-[var(--color-muted)]">
              Example Research Queries
            </h2>
            <div className="grid gap-3 sm:grid-cols-3">
              {EXAMPLE_QUERIES.map((example) => (
                <button
                  key={example.title}
                  type="button"
                  onClick={() => {
                    setQueryText(example.text);
                    handleExecuteQuery(example.text);
                  }}
                  disabled={isLoading}
                  className="cursor-pointer text-left rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-4 shadow-xs transition-all hover:border-[var(--color-brass)] hover:shadow-sm focus-visible:outline-2 focus-visible:outline-[var(--color-focus)] disabled:opacity-50"
                >
                  <p className="font-display text-xs font-bold text-[var(--color-ink)]">
                    {example.title}
                  </p>
                  <p className="mt-1 line-clamp-2 text-xs text-[var(--color-muted)]">
                    {example.text}
                  </p>
                </button>
              ))}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
