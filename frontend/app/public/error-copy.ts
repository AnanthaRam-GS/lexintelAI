import { ApiClientError } from '../../lib/api';

export type PublicAnswerFailure =
  | 'cancelled'
  | 'network'
  | 'service'
  | 'invalid-pdf'
  | 'pdf-too-large'
  | 'pdf-empty'
  | 'model-unavailable'
  | 'model-quota-exceeded';
export type AdminRequestFailure = 'network' | 'service' | 'timeout';
export type AdminFileFailure = 'corrupted' | 'processing' | 'timeout' | 'too-large' | 'unsupported';

interface ErrorCopy {
  title: string;
  message: string;
}

export const errorCopy = {
  public: {
    answer: {
      service: {
        title: "Couldn't get an answer right now",
        message: 'Your question is still here. Please try again in a moment.',
      },
      network: {
        title: 'Check your connection',
        message: 'We could not reach LegalAI. Reconnect, then try your question again.',
      },
      cancelled: {
        title: 'We stopped waiting',
        message: 'Your question is still here. Retry whenever you are ready.',
      },
      'invalid-pdf': {
        title: "This PDF couldn't be read",
        message: 'Use a standard, readable PDF and try again.',
      },
      'pdf-too-large': {
        title: 'This PDF is too large',
        message: 'Use a smaller PDF and try again.',
      },
      'pdf-empty': {
        title: 'No readable text found',
        message: 'This PDF does not appear to contain readable text.',
      },
      'model-unavailable': {
        title: 'Answer service unavailable',
        message: 'The legal answer model is temporarily unavailable. Try again later.',
      },
      'model-quota-exceeded': {
        title: 'Usage limit reached',
        message: 'AI answer service has reached its temporary usage limit. Please try again later.',
      },
    } satisfies Record<PublicAnswerFailure, ErrorCopy>,
    loading: {
      fast: 'Finding a clear answer…',
      slow: 'Still working on your answer…',
      timeoutTitle: 'Taking longer than expected',
      timeoutMessage: 'You can keep waiting, or cancel without losing your question.',
      continued: 'Still working. You can cancel at any time without losing your question.',
    },
  },
  admin: {
    status: {
      service: {
        title: 'System status is currently unavailable',
        message: 'The status service could not be reached. Try again in a moment.',
      },
      network: {
        title: 'Check your connection',
        message: 'Status could not be refreshed. Reconnect, then try again.',
      },
      timeout: {
        title: 'System status is taking too long',
        message: 'The status service did not respond in time. Try again.',
      },
    } satisfies Record<AdminRequestFailure, ErrorCopy>,
    serviceHealth: {
      healthy: 'Available',
      degraded: 'Limited availability',
      down: 'Currently unavailable',
    },
    submit: {
      service: {
        title: 'Ingestion is currently unavailable',
        message: 'This batch was not started. Keep the files here and try again in a moment.',
      },
      network: {
        title: 'Check your connection',
        message: 'This batch was not started. Reconnect, then try again.',
      },
      timeout: {
        title: 'Ingestion is taking too long to start',
        message: 'This batch was not started. Keep the files here and try again.',
      },
    } satisfies Record<AdminRequestFailure, ErrorCopy>,
    polling: {
      service: {
        title: 'Ingestion status is currently unavailable',
        message: 'Your jobs are still visible. Status checks will retry automatically.',
      },
      network: {
        title: 'Check your connection',
        message: 'Your jobs are still visible. Status checks will resume automatically.',
      },
      timeout: {
        title: 'Ingestion status is taking too long',
        message: 'Your jobs are still visible. Status checks will retry automatically.',
      },
    } satisfies Record<AdminRequestFailure, ErrorCopy>,
    file: {
      corrupted: {
        title: "This file couldn't be processed",
        message: 'The PDF may be damaged. Open it to check it, then add a working copy.',
      },
      unsupported: {
        title: "This file couldn't be processed",
        message: 'This PDF format is not supported. Save it as a standard PDF, then add it again.',
      },
      'too-large': {
        title: "This file couldn't be processed",
        message: 'The PDF is too large. Use a smaller file, then add it in a new batch.',
      },
      timeout: {
        title: "This file couldn't be processed",
        message: 'Processing took too long. Check the PDF, then add it again in a new batch.',
      },
      processing: {
        title: "This file couldn't be processed",
        message: 'Check the PDF, then add it again in a new batch.',
      },
    } satisfies Record<AdminFileFailure, ErrorCopy>,
  },
} as const;

export function classifyRequestFailure(error: unknown): AdminRequestFailure {
  if (typeof navigator !== 'undefined' && navigator.onLine === false) return 'network';
  if (error instanceof TypeError) return 'network';
  return 'service';
}

export function classifyPublicAnswerFailure(error: unknown): PublicAnswerFailure {
  if (error instanceof ApiClientError) {
    if (error.code === 'PDF_TOO_LARGE') return 'pdf-too-large';
    if (
      error.code === 'INVALID_PDF_EXTENSION' ||
      error.code === 'INVALID_PDF_MIME_TYPE' ||
      error.code === 'INVALID_PDF_HEADER'
    )
      return 'invalid-pdf';
    if (error.code === 'PDF_PARSE_FAILED' || error.code === 'PDF_CHUNKING_FAILED')
      return 'pdf-empty';
    if (error.code === 'MODEL_PROVIDER_QUOTA_EXCEEDED' || error.status === 429)
      return 'model-quota-exceeded';
    if (
      error.code === 'MODEL_UNAVAILABLE' ||
      error.code === 'MODEL_PROVIDER_ERROR' ||
      error.code === 'MODEL_PROVIDER_UNAVAILABLE' ||
      error.status === 503
    )
      return 'model-unavailable';
  }
  return classifyRequestFailure(error) === 'network' ? 'network' : 'service';
}

export function toAdminFileFailure(value: unknown): AdminFileFailure {
  return value === 'corrupted' ||
    value === 'unsupported' ||
    value === 'too-large' ||
    value === 'timeout'
    ? value
    : 'processing';
}
