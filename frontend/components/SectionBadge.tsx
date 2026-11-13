'use client';

import React, { useState } from 'react';
import { sectionLabelParts, sectionNumberText } from '../lib/section-labels';
import { statuteCode, type StatuteCode } from '../lib/statutes';
import type { SectionReference } from '../lib/types/api';
import { SectionLabelText } from './SectionLabelText';

export interface SectionBadgeProps {
  section: SectionReference;
  variant?: 'compact' | 'detailed';
  showContext?: boolean;
  className?: string;
}

interface StatuteStyle {
  bg: string;
  text: string;
  border: string;
  prefix: string;
}

const NEUTRAL = {
  bg: 'bg-[var(--color-surface-subtle)]',
  text: 'text-[var(--color-ink)]',
  border: 'border-[var(--color-border)]',
};

const EVIDENCE = { bg: 'bg-[#fdf4e8]', text: 'text-[#8b591f]', border: 'border-[#e0c497]' };

const STATUTE_STYLES: Record<StatuteCode, StatuteStyle> = {
  IPC: { bg: 'bg-[#fbf0dc]', text: 'text-[#75440d]', border: 'border-[#e7bd75]', prefix: 'IPC' },
  BNS: { bg: 'bg-[#e8f1fa]', text: 'text-[#174d85]', border: 'border-[#9fc0e1]', prefix: 'BNS' },
  BNSS: { bg: 'bg-[#e8f4ec]', text: 'text-[#155437]', border: 'border-[#9acdad]', prefix: 'BNSS' },
  CrPC: { bg: 'bg-[#f4ebf7]', text: 'text-[#5e2b6e]', border: 'border-[#cfb3d8]', prefix: 'CrPC' },
  BSA: { ...EVIDENCE, prefix: 'BSA' },
  'Evidence Act': { ...EVIDENCE, prefix: 'IEA' },
  'NDPS Act': { ...NEUTRAL, prefix: 'NDPS' },
  'POCSO Act': { ...NEUTRAL, prefix: 'POCSO' },
  'SC/ST Act': { ...NEUTRAL, prefix: 'SC/ST' },
};

/**
 * Visual styling for a statute. Step 27: the statute is recognised by exact, normalized name (`statuteCode`), not
 * by substring, so "BNSS" is never shown as "BNS". Unknown statutes get a neutral "ACT" badge.
 */
function getStatuteStyle(statute: string): StatuteStyle {
  const code = statuteCode(statute);
  return code ? STATUTE_STYLES[code] : { ...NEUTRAL, prefix: 'ACT' };
}

export function SectionBadge({
  section,
  variant = 'detailed',
  showContext = true,
  className = '',
}: SectionBadgeProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const style = getStatuteStyle(section.statute);
  const labelParts = sectionLabelParts(section);
  // Sections named by the answer show their resolved label; the raw answer text is never shown as the label.
  const showLabel = Boolean(section.label) || labelParts.marker !== null;

  const confidencePct =
    typeof section.confidence === 'number' ? Math.round(section.confidence * 100) : null;

  return (
    <div
      className={`inline-flex flex-col rounded-[var(--radius-compact)] border ${style.border} ${style.bg} transition-shadow duration-[var(--motion-fast)] ${className}`}
      data-testid="section-badge"
    >
      <div className="flex items-center gap-2 px-2.5 py-1 text-[0.8125rem] font-medium leading-none">
        <span
          className={`rounded-xs px-1 py-0.5 text-[0.6875rem] font-bold tracking-wider uppercase ${style.text}`}
          title={section.statute}
          data-testid="statute-prefix"
        >
          {style.prefix}
        </span>

        <span className="font-semibold text-[var(--color-ink)]">
          {section.statute === 'Unspecified' ? section.section : sectionNumberText(section.section)}
        </span>

        {confidencePct !== null && (
          <span
            className="ml-auto inline-flex items-center rounded-full bg-white/70 px-1.5 py-0.5 text-[0.6875rem] font-medium text-[var(--color-muted)]"
            title={`Classifier confidence: ${confidencePct}%`}
          >
            {confidencePct}%
          </span>
        )}

        {showContext && section.context && !showLabel && variant === 'detailed' && (
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
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M19 9l-7 7-7-7"
              />
            </svg>
          </button>
        )}
      </div>

      {showLabel && (
        <div className="border-t border-black/10 px-2.5 py-1.5 text-[0.75rem] leading-snug text-[var(--color-body)]">
          <SectionLabelText reference={section} showHeading={false} />
        </div>
      )}

      {isExpanded && section.context && !showLabel && (
        <div className="border-t border-black/10 px-2.5 py-2 text-[0.75rem] leading-relaxed text-[var(--color-body)]">
          <p className="font-medium text-[var(--color-ink)] mb-0.5">{section.statute}</p>
          <p>{section.context}</p>
        </div>
      )}
    </div>
  );
}
