'use client';

import React, { useState } from 'react';
import type { SectionReference } from '../lib/types/api';

export interface SectionBadgeProps {
  section: SectionReference;
  variant?: 'compact' | 'detailed';
  showContext?: boolean;
  className?: string;
}

/**
 * Derives visual styling for different Indian statutory frameworks.
 */
function getStatuteStyle(statute: string): {
  bg: string;
  text: string;
  border: string;
  prefix: string;
} {
  const normalized = statute.toLowerCase();
  if (normalized.includes('penal code') || normalized.includes('ipc')) {
    return {
      bg: 'bg-[#fbf0dc]',
      text: 'text-[#75440d]',
      border: 'border-[#e7bd75]',
      prefix: 'IPC',
    };
  }
  if (normalized.includes('nyaya sanhita') || normalized.includes('bns')) {
    return {
      bg: 'bg-[#e8f1fa]',
      text: 'text-[#174d85]',
      border: 'border-[#9fc0e1]',
      prefix: 'BNS',
    };
  }
  if (normalized.includes('nagarik suraksha') || normalized.includes('bnss')) {
    return {
      bg: 'bg-[#e8f4ec]',
      text: 'text-[#155437]',
      border: 'border-[#9acdad]',
      prefix: 'BNSS',
    };
  }
  if (normalized.includes('criminal procedure') || normalized.includes('crpc')) {
    return {
      bg: 'bg-[#f4ebf7]',
      text: 'text-[#5e2b6e]',
      border: 'border-[#cfb3d8]',
      prefix: 'CrPC',
    };
  }
  if (normalized.includes('evidence') || normalized.includes('sakshya') || normalized.includes('bsa')) {
    return {
      bg: 'bg-[#fdf4e8]',
      text: 'text-[#8b591f]',
      border: 'border-[#e0c497]',
      prefix: 'BSA/IEA',
    };
  }
  return {
    bg: 'bg-[var(--color-surface-subtle)]',
    text: 'text-[var(--color-ink)]',
    border: 'border-[var(--color-border)]',
    prefix: 'ACT',
  };
}

export function SectionBadge({
  section,
  variant = 'detailed',
  showContext = true,
  className = '',
}: SectionBadgeProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const style = getStatuteStyle(section.statute);

  const confidencePct =
    typeof section.confidence === 'number'
      ? Math.round(section.confidence * 100)
      : null;

  return (
    <div
      className={`inline-flex flex-col rounded-[var(--radius-compact)] border ${style.border} ${style.bg} transition-shadow duration-[var(--motion-fast)] ${className}`}
      data-testid="section-badge"
    >
      <div className="flex items-center gap-2 px-2.5 py-1 text-[0.8125rem] font-medium leading-none">
        <span
          className={`rounded-xs px-1 py-0.5 text-[0.6875rem] font-bold tracking-wider uppercase ${style.text}`}
          title={section.statute}
        >
          {style.prefix}
        </span>

        <span className="font-semibold text-[var(--color-ink)]">
          {section.section}
        </span>

        {confidencePct !== null && (
          <span
            className="ml-auto inline-flex items-center rounded-full bg-white/70 px-1.5 py-0.5 text-[0.6875rem] font-medium text-[var(--color-muted)]"
            title={`Classifier confidence: ${confidencePct}%`}
          >
            {confidencePct}%
          </span>
        )}

        {showContext && section.context && variant === 'detailed' && (
          <button
            type="button"
            onClick={() => setIsExpanded((prev) => !prev)}
            aria-expanded={isExpanded}
            aria-label={`Toggle description for ${section.section}`}
            className="ml-1 cursor-pointer rounded p-0.5 text-[var(--color-muted)] hover:bg-black/5 hover:text-[var(--color-ink)] focus-visible:outline-2 focus-visible:outline-[var(--color-focus)]"
          >
            <svg
              className={`h-3.5 w-3.5 transition-transform duration-[var(--motion-fast)] ${isExpanded ? 'rotate-180' : ''}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>
        )}
      </div>

      {isExpanded && section.context && (
        <div className="border-t border-black/10 px-2.5 py-2 text-[0.75rem] leading-relaxed text-[var(--color-body)]">
          <p className="font-medium text-[var(--color-ink)] mb-0.5">{section.statute}</p>
          <p>{section.context}</p>
        </div>
      )}
    </div>
  );
}
