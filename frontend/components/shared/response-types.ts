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
}

export interface ResponseCardProps {
  mode: 'professional' | 'public';
  content: AnswerContent;
  citations: Citation[];
  sections: LegalSection[];
}
