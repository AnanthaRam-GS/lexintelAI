import type { AnswerContent, Citation, IngestionJob, LegalSection } from '@/components/shared';

/**
 * Presentation-only mocks mapped from the frozen Phase 0 API contract.
 * They remain local to this preview and must never be treated as live legal data.
 */

export const initialIngestionJobs: IngestionJob[] = [
  {
    id: 'job-delhi-queued',
    filename: 'Delhi High Court bail order.pdf',
    stage: 'QUEUED',
    progress: 0,
  },
  {
    id: 'job-constitution-extracting',
    filename: 'Constitution Bench reference.pdf',
    stage: 'EXTRACTING',
    progress: 32,
  },
  {
    id: 'job-bnss-chunking',
    filename: 'BNSS procedural note.pdf',
    stage: 'CHUNKING',
    progress: 48,
  },
  {
    id: 'job-dk-basu-embedding',
    filename: 'D.K. Basu safeguards.pdf',
    stage: 'EMBEDDING',
    progress: 66,
  },
  {
    id: 'job-arnesh-indexing',
    filename: 'Arnesh Kumar arrest guidance.pdf',
    stage: 'INDEXING',
    progress: 84,
  },
  {
    id: 'job-lalita-completed',
    filename: 'Lalita Kumari FIR ruling.pdf',
    stage: 'COMPLETED',
    progress: 100,
  },
  {
    id: 'job-satender-failed',
    filename: 'Satender Kumar Antil directions.pdf',
    stage: 'FAILED',
    progress: 71,
    error: 'Indexing could not be completed. Retry this document.',
  },
];

export const advancedIngestionJobs: IngestionJob[] = [
  {
    id: 'job-delhi-queued',
    filename: 'Delhi High Court bail order.pdf',
    stage: 'EXTRACTING',
    progress: 18,
  },
  {
    id: 'job-constitution-extracting',
    filename: 'Constitution Bench reference.pdf',
    stage: 'CHUNKING',
    progress: 58,
  },
  {
    id: 'job-bnss-chunking',
    filename: 'BNSS procedural note.pdf',
    stage: 'EMBEDDING',
    progress: 67,
  },
  {
    id: 'job-dk-basu-embedding',
    filename: 'D.K. Basu safeguards.pdf',
    stage: 'INDEXING',
    progress: 81,
  },
  {
    id: 'job-arnesh-indexing',
    filename: 'Arnesh Kumar arrest guidance.pdf',
    stage: 'FAILED',
    progress: 84,
    error: 'Indexing could not be completed. Retry this document.',
  },
  {
    id: 'job-lalita-completed',
    filename: 'Lalita Kumari FIR ruling.pdf',
    stage: 'COMPLETED',
    progress: 100,
  },
  {
    id: 'job-satender-failed',
    filename: 'Satender Kumar Antil directions.pdf',
    stage: 'FAILED',
    progress: 71,
    error: 'Indexing could not be completed. Retry this document.',
  },
];

export const professionalAnswer: AnswerContent = {
  heading: 'Safeguards governing arrest without warrant',
  paragraphs: [
    'An arrest for an offence punishable by up to seven years requires the police officer to record why arrest is necessary under the statutory conditions. The power to arrest is not a direction to arrest in every eligible case.',
    'The person arrested must be told the grounds of arrest, allowed to consult an advocate during interrogation, and produced before the nearest magistrate within twenty-four hours, excluding travel time.',
  ],
  keyPoints: [
    'Record the reasons supporting the necessity of arrest.',
    'Communicate the grounds of arrest to the arrested person.',
    'Forward the arrest memorandum and relevant records for judicial scrutiny.',
  ],
};

export const publicAnswer: AnswerContent = {
  heading: 'Plain-language answer',
  paragraphs: [
    'The police cannot arrest someone automatically just because an accusation has been made. For many offences, they must explain why an arrest is genuinely needed and follow the safeguards set out in law.',
    'A person who is arrested has the right to know the reason, speak with a lawyer during questioning, and be brought before a magistrate within twenty-four hours, apart from travel time.',
  ],
  keyPoints: [
    'Ask for the grounds of arrest in clear language.',
    'Tell a family member or trusted person what has happened.',
    'Seek help from a qualified lawyer or the nearest legal services authority.',
  ],
};

export const responseCitations: Citation[] = [
  {
    title: 'D.K. Basu v. State of West Bengal',
    court: 'Supreme Court of India',
    year: 1997,
    sourceUrl: 'https://indiankanoon.org/doc/501198/',
    excerpt:
      'The judgment established procedural safeguards intended to prevent abuse during arrest and detention.',
  },
  {
    title: 'Arnesh Kumar v. State of Bihar',
    court: 'Supreme Court of India',
    year: 2014,
    sourceUrl: 'https://indiankanoon.org/doc/2982624/',
    excerpt:
      'The Court required police and magistrates to scrutinise whether statutory conditions for arrest are satisfied.',
  },
];

export const responseSections: LegalSection[] = [
  {
    code: 'BNSS',
    section: '35',
    title: 'When police may arrest without warrant',
    explanation:
      'This section sets conditions for arrest and requires recorded reasons in specified cases.',
    sourceUrl: 'https://www.indiacode.nic.in/handle/123456789/20099',
    confidence: 94,
  },
  {
    code: 'BNSS',
    section: '47',
    title: 'Grounds of arrest and right to bail information',
    explanation:
      'The arrested person must be told the grounds of arrest and informed about bail where applicable.',
    sourceUrl: 'https://www.indiacode.nic.in/handle/123456789/20099',
    confidence: 91,
  },
];
