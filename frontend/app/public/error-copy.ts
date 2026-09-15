export type PublicAnswerFailure = 'cancelled' | 'network' | 'service';
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
