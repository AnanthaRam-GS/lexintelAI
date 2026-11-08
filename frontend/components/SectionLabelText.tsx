import React from 'react';
import { SECTION_MARKER_COPY, sectionLabelParts } from '../lib/section-labels';
import type { SectionReference } from '../lib/types/api';

export interface SectionLabelTextProps {
  reference: SectionReference;
  /** Hide the "Section N Statute" heading when the surrounding element already shows it. */
  showHeading?: boolean;
  className?: string;
}

/**
 * A section with its resolved label (step 25): the trusted title, or the answer's own wording marked
 * "Unverified label", plus a short note for a corrected statute or disagreeing sources.
 */
export function SectionLabelText({
  reference,
  showHeading = true,
  className = '',
}: SectionLabelTextProps) {
  const parts = sectionLabelParts(reference);
  return (
    <span
      className={`inline ${className}`}
      data-testid="section-label"
      data-label-state={parts.state}
    >
      {showHeading && (
        <span className="font-semibold text-[var(--color-ink)]">{parts.heading}</span>
      )}
      {parts.text && (
        <>
          {showHeading && <span aria-hidden="true"> — </span>}
          <span className={parts.marker ? 'italic' : undefined}>{parts.text}</span>
        </>
      )}
      {parts.marker && (
        <span
          className="ml-1.5 inline-flex items-center rounded-full border border-[var(--color-warning-border)] bg-[var(--color-warning-surface)] px-1.5 py-0.5 align-middle text-[0.6875rem] font-semibold text-[var(--color-warning-foreground)]"
          data-testid="section-label-marker"
        >
          {SECTION_MARKER_COPY[parts.marker]}
        </span>
      )}
      {parts.note && (
        <span
          className="mt-0.5 block text-[0.75rem] text-[var(--color-muted)]"
          data-testid="section-label-note"
        >
          {parts.note}
        </span>
      )}
    </span>
  );
}
