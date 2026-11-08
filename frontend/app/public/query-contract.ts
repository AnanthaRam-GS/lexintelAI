import type { SectionReference } from '../../lib/types/api';

export type PublicQueryInput =
  { kind: 'text'; content: string } | { kind: 'file'; file: File; question: string };

export interface PublicQueryResponse {
  explanation: string;
  sections: Array<{
    title: string;
    explanation: string;
    link: string;
    /** Each section the answer named, with its label resolution (step 25). */
    references?: SectionReference[];
  }>;
  sources: Array<{ title: string; link: string }>;
  nextStepGuidance: string;
  /** Caveats about an uploaded document (for example low-confidence OCR); empty for text questions. */
  limitations?: string[];
}
