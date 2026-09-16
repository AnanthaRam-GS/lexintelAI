import type {
  AuthenticatedUser,
  AdminLawyerApplication,
  AdminLawyerApplicationList,
  AdminIngestionMetadata,
  AdminIngestionStatusResponse,
  AdminIngestionUploadResponse,
  CorpusStats,
  CorpusStatsResponse,
  IpcBnsMappingRow,
  LoginResponse,
  LawyerApplication,
  LawyerApplicationEnvelope,
  NcrbStatPoint,
  OffenseFrequencyPoint,
  OutcomeDistributionPoint,
  ProfessionalQueryResponse,
  QueryHistoryItem,
  RegistrationResponse,
  EmailVerificationResponse,
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
  const response = await fetch(`${apiBaseUrl()}${path}`, {
    ...init,
    credentials: 'include',
    headers: requestHeaders(init),
  });

  if (!response.ok) {
    throw await apiError(response);
  }

  return (await response.json()) as TResponse;
}

export const authApi = {
  register(fullName: string, email: string, password: string): Promise<RegistrationResponse> {
    return apiFetch<RegistrationResponse>('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ full_name: fullName, email, password }),
    });
  },

  login(email: string, password: string): Promise<LoginResponse> {
    return apiFetch<LoginResponse>('/auth/login', {
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

  verifyEmail(token: string): Promise<EmailVerificationResponse> {
    return apiFetch<EmailVerificationResponse>('/auth/verify-email', {
      method: 'POST',
      body: JSON.stringify({ token }),
    });
  },

  resendVerification(): Promise<EmailVerificationResponse> {
    return apiFetch<EmailVerificationResponse>('/auth/resend-verification', { method: 'POST' });
  },
};

export const lawyerApplicationApi = {
  getMine(): Promise<LawyerApplicationEnvelope> {
    return apiFetch<LawyerApplicationEnvelope>('/lawyer-applications/me');
  },

  submit(input: {
    barCouncil: string;
    enrollmentNumber: string;
    enrollmentYear: number;
    jurisdiction: string;
    organization?: string;
    proof: File;
  }): Promise<LawyerApplication> {
    const body = new FormData();
    body.append('bar_council', input.barCouncil);
    body.append('enrollment_number', input.enrollmentNumber);
    body.append('enrollment_year', String(input.enrollmentYear));
    body.append('jurisdiction', input.jurisdiction);
    appendOptionalFormValue(body, 'organization', input.organization);
    body.append('proof', input.proof);
    return apiFetch<LawyerApplication>('/lawyer-applications', { method: 'POST', body });
  },
};

export const adminLawyerVerificationApi = {
  list(statusFilter?: string): Promise<AdminLawyerApplicationList> {
    const query = statusFilter ? `?status_filter=${encodeURIComponent(statusFilter)}` : '';
    return apiFetch<AdminLawyerApplicationList>(`/admin/lawyer-applications${query}`);
  },

  get(id: number): Promise<AdminLawyerApplication> {
    return apiFetch<AdminLawyerApplication>(`/admin/lawyer-applications/${id}`);
  },

  approve(id: number): Promise<AdminLawyerApplication> {
    return apiFetch<AdminLawyerApplication>(`/admin/lawyer-applications/${id}/approve`, {
      method: 'POST',
    });
  },

  reject(id: number, reason: string): Promise<AdminLawyerApplication> {
    return apiFetch<AdminLawyerApplication>(`/admin/lawyer-applications/${id}/reject`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    });
  },

  requestResubmission(id: number, reason: string): Promise<AdminLawyerApplication> {
    return apiFetch<AdminLawyerApplication>(
      `/admin/lawyer-applications/${id}/request-resubmission`,
      { method: 'POST', body: JSON.stringify({ reason }) },
    );
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
    return apiFetch<ProfessionalQueryResponse>('/query/professional/pdf', {
      method: 'POST',
      body,
    });
  },
};

export const historyApi = {
  getQueryHistory(limit = 50): Promise<QueryHistoryItem[]> {
    const safeLimit = Math.min(100, Math.max(1, Math.trunc(limit)));
    return apiFetch<QueryHistoryItem[]>(`/query/history?limit=${safeLimit}`);
  },
};

export const analyticsApi = {
  getOffenseFrequency(): Promise<OffenseFrequencyPoint[]> {
    return apiFetch<OffenseFrequencyPoint[]>('/analytics/offense-frequency');
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
};

export const adminIngestionApi = {
  uploadDocument(
    file: File,
    metadata: AdminIngestionMetadata,
    options: { signal?: AbortSignal } = {},
  ): Promise<AdminIngestionUploadResponse> {
    const body = new FormData();
    body.append('file', file);
    body.append('doc_type', metadata.documentType);
    appendOptionalFormValue(body, 'court_level', metadata.courtLevel);
    if (typeof metadata.year === 'number' && Number.isFinite(metadata.year)) {
      body.append('year', String(Math.trunc(metadata.year)));
    }
    appendOptionalFormValue(body, 'source_url', metadata.sourceUrl);
    appendOptionalFormValue(body, 'case_name', metadata.caseName);

    return apiFetch<AdminIngestionUploadResponse>('/ingest/upload', {
      method: 'POST',
      body,
      signal: options.signal,
    });
  },

  getStatus(
    jobId: string,
    options: { signal?: AbortSignal } = {},
  ): Promise<AdminIngestionStatusResponse> {
    return apiFetch<AdminIngestionStatusResponse>(`/ingest/status/${encodeURIComponent(jobId)}`, {
      signal: options.signal,
    });
  },

  async getCorpusStats(options: { signal?: AbortSignal } = {}): Promise<CorpusStats> {
    const stats = await apiFetch<CorpusStatsResponse>('/ingest/corpus/stats', {
      signal: options.signal,
    });
    return toCorpusStats(stats);
  },
};

function apiBaseUrl(): string {
  return (process.env.NEXT_PUBLIC_API_BASE_URL || defaultApiBaseUrl).replace(/\/+$/, '');
}

function requestHeaders(init: RequestInit): HeadersInit | undefined {
  if (init.body instanceof FormData) {
    return init.headers;
  }
  if (init.body == null) {
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

function appendOptionalFormValue(body: FormData, name: string, value: string | undefined): void {
  const normalized = value?.trim();
  if (normalized) {
    body.append(name, normalized);
  }
}

function toCorpusStats(response: CorpusStatsResponse): CorpusStats {
  const breakdown: CorpusStats['breakdown'] = { judgment: 0, statute: 0, other: 0 };
  for (const item of response.by_type) {
    if (item.doc_type === 'judgment' || item.doc_type === 'statute' || item.doc_type === 'other') {
      breakdown[item.doc_type] = item.count;
    }
  }

  const timestamp = response.last_updated ?? '';
  return {
    totalDocuments: response.total_documents,
    lastUpdatedTimestamp: timestamp,
    lastIngestionDate: timestamp,
    breakdown,
    chromaDb: { status: serviceHealth(response.chroma_status) },
    postgresql: { status: serviceHealth(response.postgres_status) },
  };
}

function serviceHealth(value: string): CorpusStats['chromaDb']['status'] {
  const normalized = value.toLowerCase();
  if (normalized === 'healthy') return 'healthy';
  if (normalized === 'degraded') return 'degraded';
  return 'down';
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
    if (isBackendStringError(body)) {
      return new ApiClientError(body.detail, response.status);
    }
  } catch {
    return new ApiClientError(fallback, response.status);
  }
  return new ApiClientError(fallback, response.status);
}

function isBackendStringError(value: unknown): value is { detail: string } {
  return (
    !!value &&
    typeof value === 'object' &&
    'detail' in value &&
    typeof (value as { detail?: unknown }).detail === 'string'
  );
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
