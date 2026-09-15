import type {
  AuthenticatedUser,
  IpcBnsMappingRow,
  LoginResponse,
  NcrbStatPoint,
  OffenseFrequencyPoint,
  OutcomeDistributionPoint,
  ProfessionalQueryResponse,
  QueryHistoryItem,
  SectionCooccurrencePoint,
} from './types/api';

const defaultApiBaseUrl = 'http://127.0.0.1:8000';

export class ApiClientError extends Error {
  constructor(
    message: string,
    readonly status?: number,
    readonly code?: string,
  ) {
    super(message);
    this.name = 'ApiClientError';
  }
}

export async function apiFetch<TResponse>(
  path: string,
  init: RequestInit = {},
): Promise<TResponse> {
  const headers = requestHeaders(init);
  const headers = new Headers(init.headers);
  if (init.body != null && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(`${apiBaseUrl()}${path}`, {
    ...init,
    credentials: 'include',
    headers,
  });

  if (!response.ok) {
    throw await apiError(response);
  }

  return (await response.json()) as TResponse;
}

export const authApi = {
  login(email: string, password: string): Promise<LoginResponse> {
    return apiFetch<LoginResponse>('/auth/login', {
  login(email: string, password: string) {
    return apiFetch<{ user: AuthenticatedUser; message: string }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
  },

  me(): Promise<AuthenticatedUser> {
    return apiFetch<AuthenticatedUser>('/auth/me');
  },

  logout(): Promise<{ message: string }> {
    return apiFetch<{ message: string }>('/auth/logout', { method: 'POST' });
  },
};

export const queryApi = {
  submitText(text: string, sessionId?: string): Promise<ProfessionalQueryResponse> {
    return apiFetch<ProfessionalQueryResponse>('/query/professional', {
      method: 'POST',
      body: JSON.stringify({ text, ...(sessionId ? { session_id: sessionId } : {}) }),
    });
  },

  submitPdf(
    file: File,
    query = 'Analyze this legal document.',
    sessionId?: string,
  ): Promise<ProfessionalQueryResponse> {
    const body = new FormData();
    body.append('query', query);
    body.append('file', file);
    if (sessionId) {
      body.append('session_id', sessionId);
    }
  logout() {
    return apiFetch<{ message: string }>('/auth/logout', { method: 'POST' });
  },
  me() {
    return apiFetch<AuthenticatedUser>('/auth/me');
  },
};

export const queryApi = {
  submitText(text: string) {
    return apiFetch<ProfessionalQueryResponse>('/query/professional', {
      method: 'POST',
      body: JSON.stringify({ text }),
    });
  },
  submitPdf(file: File) {
    const body = new FormData();
    body.set('file', file);
    body.set('query', 'Analyze this legal document.');
    return apiFetch<ProfessionalQueryResponse>('/query/professional/pdf', {
      method: 'POST',
      body,
    });
  },
};

export const historyApi = {
  getQueryHistory(limit = 50): Promise<QueryHistoryItem[]> {
    return apiFetch<QueryHistoryItem[]>(`/query/history?limit=${encodeURIComponent(limit)}`);
  getQueryHistory(limit = 50) {
    const safeLimit = Math.min(100, Math.max(1, Math.trunc(limit)));
    return apiFetch<QueryHistoryItem[]>(`/query/history?limit=${safeLimit}`);
  },
};

export const analyticsApi = {
  getOffenseFrequency(): Promise<OffenseFrequencyPoint[]> {
    return apiFetch<OffenseFrequencyPoint[]>('/analytics/offence-frequency');
  },

  getOutcomeDistribution(): Promise<OutcomeDistributionPoint[]> {
    return apiFetch<OutcomeDistributionPoint[]>('/analytics/outcome-distribution');
  },

  getSectionCooccurrence(): Promise<SectionCooccurrencePoint[]> {
    return apiFetch<SectionCooccurrencePoint[]>('/analytics/section-cooccurrence');
  },

  getIpcBnsMap(): Promise<IpcBnsMappingRow[]> {
    return apiFetch<IpcBnsMappingRow[]>('/analytics/ipc-bns-map');
  },

  getNcrbStats(): Promise<NcrbStatPoint[]> {
    return apiFetch<NcrbStatPoint[]>('/analytics/ncrb-stats');
  },
  getOffenseFrequency: () => apiFetch<OffenseFrequencyPoint[]>('/analytics/offense-frequency'),
  getOutcomeDistribution: () =>
    apiFetch<OutcomeDistributionPoint[]>('/analytics/outcome-distribution'),
  getSectionCooccurrence: () =>
    apiFetch<SectionCooccurrencePoint[]>('/analytics/section-cooccurrence'),
  getIpcBnsMap: () => apiFetch<IpcBnsMappingRow[]>('/analytics/ipc-bns-map'),
  getNcrbStats: () => apiFetch<NcrbStatPoint[]>('/analytics/ncrb-stats'),
};

function apiBaseUrl(): string {
  return (process.env.NEXT_PUBLIC_API_BASE_URL || defaultApiBaseUrl).replace(/\/+$/, '');
}

function requestHeaders(init: RequestInit): HeadersInit | undefined {
  if (init.body instanceof FormData) {
    return init.headers;
  }
  const headers = headerRecord(init.headers);
  if (!hasHeader(headers, 'Content-Type')) {
    headers['Content-Type'] = 'application/json';
  }
  return headers;
}

function headerRecord(headers: HeadersInit | undefined): Record<string, string> {
  if (!headers) {
    return {};
  }
  if (headers instanceof Headers) {
    return Object.fromEntries(headers.entries());
  }
  if (Array.isArray(headers)) {
    return Object.fromEntries(headers);
  }
  return { ...headers };
}

function hasHeader(headers: Record<string, string>, name: string): boolean {
  return Object.keys(headers).some((key) => key.toLowerCase() === name.toLowerCase());
}

async function apiError(response: Response): Promise<ApiClientError> {
  const fallback =
    response.status >= 500
      ? 'The LegalAI service is temporarily unavailable.'
      : 'The request could not be completed.';
  try {
    const body: unknown = await response.json();
    if (isBackendError(body)) {
      return new ApiClientError(body.detail.message, response.status, body.detail.code);
    }
  } catch {
    return new ApiClientError(fallback, response.status);
  }
  return new ApiClientError(fallback, response.status);
}

function isBackendError(value: unknown): value is { detail: { code: string; message: string } } {
  if (!value || typeof value !== 'object' || !('detail' in value)) {
    return false;
  }
  const detail = (value as { detail: unknown }).detail;
  return (
    !!detail &&
    typeof detail === 'object' &&
    typeof (detail as { code?: unknown }).code === 'string' &&
    typeof (detail as { message?: unknown }).message === 'string'
  );
}
