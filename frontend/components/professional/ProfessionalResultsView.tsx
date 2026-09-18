'use client';

import React, { useState } from 'react';
import { CitationCard } from '../CitationCard';
import { SectionBadge } from '../SectionBadge';
import type { ProfessionalQueryResponse } from '../../lib/types/api';

export interface ProfessionalResultsViewProps {
  result: ProfessionalQueryResponse;
  queryTitle?: string;
  onReset?: () => void;
  className?: string;
}

export function ProfessionalResultsView({
  result,
  queryTitle,
  onReset,
  className = '',
}: ProfessionalResultsViewProps) {
  const [copied, setCopied] = useState(false);
  const [activeTab, setActiveTab] = useState<'brief' | 'precedents' | 'sections'>('brief');

  const { identified_sections, precedents, case_brief } = result;
  const optionalSections = [
    ['Parties & Roles', case_brief.parties_and_roles],
    ['Material Facts', case_brief.material_facts],
    ['Chronology / Procedural History', case_brief.chronology],
    ['Explicit Statutory Provisions', case_brief.statutory_provisions],
    ['Evidence Identified', case_brief.evidence_identified],
  ].filter(([, items]) => Array.isArray(items) && items.length > 0) as [string, string[]][];

  const handleCopyBrief = async () => {
    const textToCopy = `LEGAL BRIEF: ${queryTitle || 'Case Analysis'}

1. EXECUTIVE SUMMARY
${case_brief.summary}

2. APPLICABLE LAW
${case_brief.applicable_law.map((law) => `• ${law}`).join('\n')}

3. KEY LEGAL ISSUES
${case_brief.key_issues.map((issue) => `• ${issue}`).join('\n')}

4. PROCEDURAL CONSIDERATIONS
${case_brief.procedural_considerations.map((proc) => `• ${proc}`).join('\n')}

5. PRECEDENT ANALYSIS
${case_brief.precedent_analysis.map((prec) => `• ${prec}`).join('\n')}

6. LIMITATIONS & RISKS
${case_brief.limitations.map((lim) => `• ${lim}`).join('\n')}

RELEVANT CITATIONS:
${precedents.map((p) => `${p.case_name} (${p.year || 'N/A'}, ${p.court || 'Court'}) - Relevance: ${Math.round(p.relevance_score * 100)}%\nExcerpt: ${p.excerpt || 'None'}`).join('\n\n')}
`;

    try {
      await navigator.clipboard.writeText(textToCopy);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch {
      // Fallback if clipboard API is not available
    }
  };

  return (
    <div
      className={`space-y-6 ${className}`}
      data-testid="professional-results-view"
      aria-label="Professional Case Analysis Result"
    >
      {/* Top Action & Navigation Banner */}
      <div className="flex flex-col gap-3 rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-4 shadow-xs sm:flex-row sm:items-center sm:justify-between">
        <div>
          <span className="text-[0.6875rem] font-bold uppercase tracking-wider text-[var(--color-brass)]">
            Analysis Complete
          </span>
          <h2 className="font-display text-lg font-bold text-[var(--color-ink)] truncate max-w-xl">
            {queryTitle || 'Structured Legal Research Brief'}
          </h2>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleCopyBrief}
            className="cursor-pointer inline-flex items-center gap-1.5 rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-xs font-semibold text-[var(--color-body)] transition-colors hover:border-[var(--color-brass)] hover:text-[var(--color-ink)] focus-visible:outline-2 focus-visible:outline-[var(--color-focus)]"
          >
            <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3"
              />
            </svg>
            <span>{copied ? 'Copied Brief!' : 'Copy Brief'}</span>
          </button>

          {onReset && (
            <button
              type="button"
              onClick={onReset}
              className="cursor-pointer inline-flex items-center gap-1 rounded-[var(--radius-compact)] bg-[var(--color-ink)] px-3 py-1.5 text-xs font-semibold text-white shadow-xs transition-colors hover:bg-[var(--color-body)] focus-visible:outline-2 focus-visible:outline-[var(--color-focus)]"
            >
              <span>New Analysis</span>
            </button>
          )}
        </div>
      </div>

      {/* Identified Statutory Sections Horizontal Bar */}
      {identified_sections.length > 0 && (
        <section aria-label="Identified statutory sections" className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-bold uppercase tracking-wider text-[var(--color-muted)]">
              Identified Statutory Sections ({identified_sections.length})
            </h3>
            <span className="text-[0.6875rem] text-[var(--color-muted)]">
              IPC &amp; BNS Transitional Alignment
            </span>
          </div>

          <div className="flex flex-wrap gap-2">
            {identified_sections.map((sec, idx) => (
              <SectionBadge key={`${sec.statute}-${sec.section}-${idx}`} section={sec} />
            ))}
          </div>
        </section>
      )}

      {/* Tab Navigation for Desktop / Tablet */}
      <div className="border-b border-[var(--color-border)]">
        <nav className="flex space-x-6" aria-label="Results tabs">
          <button
            type="button"
            onClick={() => setActiveTab('brief')}
            className={`cursor-pointer pb-3 text-sm font-semibold transition-colors border-b-2 ${
              activeTab === 'brief'
                ? 'border-[var(--color-brass)] text-[var(--color-ink)]'
                : 'border-transparent text-[var(--color-muted)] hover:text-[var(--color-ink)]'
            }`}
          >
            Structured Case Brief
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('precedents')}
            className={`cursor-pointer pb-3 text-sm font-semibold transition-colors border-b-2 ${
              activeTab === 'precedents'
                ? 'border-[var(--color-brass)] text-[var(--color-ink)]'
                : 'border-transparent text-[var(--color-muted)] hover:text-[var(--color-ink)]'
            }`}
          >
            Precedent Citations ({precedents.length})
          </button>
        </nav>
      </div>

      {/* Tab 1: Case Brief */}
      {activeTab === 'brief' && (
        <div className="grid gap-6 lg:grid-cols-3">
          {/* Main Brief Content (2 cols) */}
          <div className="space-y-6 lg:col-span-2">
            {/* Executive Summary */}
            <article className="rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-5 shadow-xs">
              <h4 className="font-display text-base font-bold text-[var(--color-ink)]">
                1. Executive Summary
              </h4>
              <p className="mt-2 text-sm leading-relaxed text-[var(--color-body)]">
                {case_brief.summary}
              </p>
            </article>

            {optionalSections.map(([title, items]) => (
              <article
                key={title}
                className="rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-5 shadow-xs"
              >
                <h4 className="font-display text-base font-bold text-[var(--color-ink)]">
                  {title}
                </h4>
                <ul className="mt-3 space-y-2 text-sm leading-relaxed text-[var(--color-body)]">
                  {items.map((item, idx) => (
                    <li key={idx} className="border-l-2 border-[var(--color-border)] pl-3">
                      {item}
                    </li>
                  ))}
                </ul>
              </article>
            ))}

            {/* Key Issues */}
            <article className="rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-5 shadow-xs">
              <h4 className="font-display text-base font-bold text-[var(--color-ink)]">
                2. Key Legal Issues
              </h4>
              <ul className="mt-3 list-disc space-y-2 pl-5 text-sm text-[var(--color-body)]">
                {case_brief.key_issues.map((issue, idx) => (
                  <li key={idx}>{issue}</li>
                ))}
              </ul>
            </article>

            {/* Precedent Analysis */}
            <article className="rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-5 shadow-xs">
              <h4 className="font-display text-base font-bold text-[var(--color-ink)]">
                3. Precedent Analysis &amp; Judicial Rationale
              </h4>
              <ul className="mt-3 space-y-2.5 text-sm text-[var(--color-body)]">
                {case_brief.precedent_analysis.map((analysis, idx) => (
                  <li
                    key={idx}
                    className="rounded-[var(--radius-compact)] border-l-2 border-[var(--color-brass)] bg-[var(--color-canvas)]/50 p-3"
                  >
                    {analysis}
                  </li>
                ))}
              </ul>
            </article>
          </div>

          {/* Right Sidebar: Law, Procedural & Limitations (1 col) */}
          <div className="space-y-6">
            {/* Applicable Law */}
            <article className="rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-5 shadow-xs">
              <h4 className="font-display text-sm font-bold text-[var(--color-ink)]">
                Applicable Law
              </h4>
              <ul className="mt-2.5 space-y-1.5 text-xs text-[var(--color-body)]">
                {case_brief.applicable_law.map((law, idx) => (
                  <li key={idx} className="flex items-start gap-1.5">
                    <span className="font-bold text-[var(--color-brass)]">§</span>
                    <span>{law}</span>
                  </li>
                ))}
              </ul>
            </article>

            {/* Procedural Considerations */}
            <article className="rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-5 shadow-xs">
              <h4 className="font-display text-sm font-bold text-[var(--color-ink)]">
                Procedural Considerations
              </h4>
              <ul className="mt-2.5 list-disc space-y-1.5 pl-4 text-xs text-[var(--color-body)]">
                {case_brief.procedural_considerations.map((proc, idx) => (
                  <li key={idx}>{proc}</li>
                ))}
              </ul>
            </article>

            {/* Limitations & Risks */}
            <article className="rounded-[var(--radius-standard)] border border-[var(--color-warning-border)] bg-[var(--color-warning-surface)] p-5 shadow-xs">
              <h4 className="font-display text-sm font-bold text-[var(--color-warning-foreground)]">
                Limitations &amp; Legal Risks
              </h4>
              <ul className="mt-2.5 list-disc space-y-1.5 pl-4 text-xs text-[var(--color-body)]">
                {case_brief.limitations.map((lim, idx) => (
                  <li key={idx}>{lim}</li>
                ))}
              </ul>
            </article>
          </div>
        </div>
      )}

      {/* Tab 2: Precedents */}
      {activeTab === 'precedents' && (
        <section aria-label="Retrieved precedents" className="space-y-4">
          {precedents.length === 0 ? (
            <div className="rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-8 text-center text-sm text-[var(--color-muted)]">
              No matching precedents retrieved for this specific query.
            </div>
          ) : (
            precedents.map((precedent) => (
              <CitationCard key={precedent.document_id} precedent={precedent} />
            ))
          )}
        </section>
      )}
    </div>
  );
}
