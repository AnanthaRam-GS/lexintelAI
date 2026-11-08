import type { SectionReference } from './types/api';

/** Context of sections named by the answer model (backend GENERATED_CONTEXT). */
export const GENERATED_SECTION_CONTEXT = 'generated_from_grounded_answer';

/** "302" -> "Section 302"; a value that already says "Section …" is kept as it is. */
export function sectionNumberText(section: string): string {
  return /^sections?\b/i.test(section.trim()) ? section.trim() : `Section ${section}`;
}

export type SectionLabelMarker = 'unverified' | 'conflict' | null;

export interface SectionLabelParts {
  /** "Section 309(4) BNS", or the provision as written when no section could be read. */
  heading: string;
  /** The trusted title, or the answer's own wording when `marker` is 'unverified'; null when none is shown. */
  text: string | null;
  marker: SectionLabelMarker;
  /** A short note, for example a corrected statute. */
  note: string | null;
  state: 'verified' | 'corrected_statute' | 'unverified' | 'conflict';
}

/**
 * What to show for a section reference (step 25). A label written by the answer model is never shown as
 * authoritative: it appears only when no trusted title exists, and then with the 'unverified' marker. References
 * without a label (older history entries) that came from the answer are treated as unverified.
 */
export function sectionLabelParts(reference: SectionReference): SectionLabelParts {
  const unspecified = reference.statute === 'Unspecified';
  const heading = unspecified
    ? reference.section
    : `${sectionNumberText(reference.section)} ${reference.statute}`;
  const label = reference.label;
  if (!label) {
    const fromAnswer = !reference.context || reference.context === GENERATED_SECTION_CONTEXT;
    return {
      heading,
      text: null,
      marker: fromAnswer ? 'unverified' : null,
      note: null,
      state: 'unverified',
    };
  }
  if (unspecified) {
    return { heading, text: null, marker: 'unverified', note: null, state: label.state };
  }
  switch (label.state) {
    case 'verified':
      return { heading, text: label.title ?? null, marker: null, note: null, state: 'verified' };
    case 'corrected_statute':
      return {
        heading,
        text: label.title ?? label.model_label ?? null,
        marker: label.title ? null : 'unverified',
        note: `Statute corrected: the answer cited ${label.statute_corrected_from ?? 'another statute'} ${reference.section}.`,
        state: 'corrected_statute',
      };
    case 'conflict':
      return {
        heading,
        text: null,
        marker: 'conflict',
        note: 'Title not shown: the trusted sources disagree.',
        state: 'conflict',
      };
    default:
      return {
        heading,
        text: label.model_label ?? null,
        marker: 'unverified',
        note: null,
        state: 'unverified',
      };
  }
}

export const SECTION_MARKER_COPY: Record<'unverified' | 'conflict', string> = {
  unverified: 'Unverified label',
  conflict: 'Sources disagree',
};
