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
    headers: {
      'Content-Type': 'application/json',
      ...init.headers,
    },
  });

  if (!response.ok) {
    throw await apiError(response);
  }

  return (await response.json()) as TResponse;
}

function apiBaseUrl(): string {
  return (process.env.NEXT_PUBLIC_API_BASE_URL || defaultApiBaseUrl).replace(/\/+$/, '');
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
