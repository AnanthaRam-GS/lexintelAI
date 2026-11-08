export interface AnswerContent {
  heading: string;
  paragraphs: string[];
  keyPoints?: string[];
}

export interface Citation {
  title: string;
  court?: string;
  year?: number;
  sourceUrl: string;
  excerpt?: string;
}

export interface LegalSection {
  code: 'IPC' | 'BNS' | 'CrPC' | 'BNSS' | string;
  section: string;
  title: string;
  explanation?: string;
  sourceUrl: string;
  confidence?: number;
  /** Step 25: 'unverified' when the title is the answer's own wording, 'conflict' when no title is shown. */
  labelMarker?: 'unverified' | 'conflict' | null;
  /** Step 25: a short note, for example a corrected statute. */
  labelNote?: string | null;
}

export interface ResponseCardProps {
  mode: 'professional' | 'public';
  content: AnswerContent;
  citations: Citation[];
  sections: LegalSection[];
  /** Caveats about the uploaded document, e.g. low-confidence OCR; shown as a note above the answer. */
  limitations?: string[];
}
