import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  adminIngestionApi,
  analyticsApi,
  ApiClientError,
  authApi,
  historyApi,
  dailyCapacityMessage,
  limitMessage,
  limitTitle,
  queryApi,
} from './api';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('frontend API adapters', () => {
  it('uses the backend cookie-auth contract for login, session lookup, and logout', async () => {
    const fetchMock = mockFetch([
      { user: { id: 1, email: 'admin@legalai.test', role: 'admin' }, message: 'ok' },
      { id: 1, email: 'admin@legalai.test', role: 'admin' },
      { message: 'logged out' },
    ]);

    await authApi.login('admin@legalai.test', 'password');
    await authApi.me();
    await authApi.logout();

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      'http://127.0.0.1:8000/auth/login',
      'http://127.0.0.1:8000/auth/me',
      'http://127.0.0.1:8000/auth/logout',
    ]);
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({
      method: 'POST',
      credentials: 'include',
      body: JSON.stringify({ email: 'admin@legalai.test', password: 'password' }),
    });
    expect(new Headers(fetchMock.mock.calls[1]?.[1]?.headers).has('Content-Type')).toBe(false);
  });

  it('sends text and PDF professional queries using their backend contracts', async () => {
    const fetchMock = mockFetch([professionalResponse(), professionalResponse()]);
    const file = new File(['pdf'], 'brief.pdf', { type: 'application/pdf' });

    await queryApi.submitText('Explain section 35');
    await queryApi.submitPdf(file);

    expect(fetchMock.mock.calls[0]?.[0]).toBe('http://127.0.0.1:8000/query/professional');
    expect(fetchMock.mock.calls[0]?.[1]?.body).toBe(JSON.stringify({ text: 'Explain section 35' }));
    const pdfRequest = fetchMock.mock.calls[1]?.[1];
    expect(fetchMock.mock.calls[1]?.[0]).toBe('http://127.0.0.1:8000/query/professional/pdf');
    expect(pdfRequest?.body).toBeInstanceOf(FormData);
    expect((pdfRequest?.body as FormData).get('file')).toBe(file);
    expect((pdfRequest?.body as FormData).get('query')).toBe('Analyze this legal document.');
    expect(new Headers(pdfRequest?.headers).has('Content-Type')).toBe(false);
  });

  it('bounds query-history limits before building the request URL', async () => {
    const fetchMock = mockFetch([[], []]);

    await historyApi.getQueryHistory(500);
    await historyApi.getQueryHistory(-5);

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      'http://127.0.0.1:8000/query/history?limit=100',
      'http://127.0.0.1:8000/query/history?limit=1',
    ]);
  });

  it('maps every Professional analytics panel to the merged backend endpoint', async () => {
    const fetchMock = mockFetch([[], [], [], [], []]);

    await Promise.all([
      analyticsApi.getOffenseFrequency(),
      analyticsApi.getOutcomeDistribution(),
      analyticsApi.getSectionCooccurrence(),
      analyticsApi.getIpcBnsMap(),
      analyticsApi.getNcrbStats(),
    ]);

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      'http://127.0.0.1:8000/analytics/offense-frequency',
      'http://127.0.0.1:8000/analytics/outcome-distribution',
      'http://127.0.0.1:8000/analytics/section-cooccurrence',
      'http://127.0.0.1:8000/analytics/ipc-bns-map',
      'http://127.0.0.1:8000/analytics/ncrb-stats',
    ]);
  });

  it('uses live admin ingestion endpoints with cookie auth and multipart metadata', async () => {
    const fetchMock = mockFetch([
      { job_id: 'job-1', status: 'QUEUED' },
      { job_id: 'job-1', status: 'INDEXING', progress: 80 },
      {
        total_documents: 7,
        last_updated: '2026-09-08T09:00:00.000Z',
        by_type: [
          { doc_type: 'judgment', count: 3 },
          { doc_type: 'statute', count: 2 },
          { doc_type: 'other', count: 1 },
          { doc_type: 'ignored', count: 99 },
        ],
        postgres_status: 'healthy',
        chroma_status: 'degraded',
      },
    ]);
    const file = new File(['%PDF-1.7'], 'judgment.pdf', { type: 'application/pdf' });

    await adminIngestionApi.uploadDocument(file, {
      documentType: 'judgment',
      courtLevel: 'High Court',
      year: 2026,
      sourceUrl: 'https://example.test/case.pdf',
      caseName: 'State v Example',
    });
    await adminIngestionApi.getStatus('job/1');
    const stats = await adminIngestionApi.getCorpusStats();

    const upload = fetchMock.mock.calls[0]?.[1];
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      'http://127.0.0.1:8000/ingest/upload',
      'http://127.0.0.1:8000/ingest/status/job%2F1',
      'http://127.0.0.1:8000/ingest/corpus/stats',
    ]);
    expect(upload).toMatchObject({ method: 'POST', credentials: 'include' });
    expect(upload?.body).toBeInstanceOf(FormData);
    const body = upload?.body as FormData;
    expect(body.get('file')).toBe(file);
    expect(body.get('doc_type')).toBe('judgment');
    expect(body.get('court_level')).toBe('High Court');
    expect(body.get('year')).toBe('2026');
    expect(body.get('source_url')).toBe('https://example.test/case.pdf');
    expect(body.get('case_name')).toBe('State v Example');
    const headers = new Headers(upload?.headers);
    expect(headers.has('Content-Type')).toBe(false);
    expect(headers.has('Authorization')).toBe(false);
    expect(stats).toMatchObject({
      totalDocuments: 7,
      breakdown: { judgment: 3, statute: 2, other: 1 },
      chromaDb: { status: 'degraded' },
      postgresql: { status: 'healthy' },
      keywordIndex: { status: 'down' },
      chromaRecordCount: null,
      reconciliationJobCount: 0,
      reconciliationJobs: [],
    });
  });

  it('maps store counts, reasons and reconciliation jobs from corpus stats', async () => {
    mockFetch([
      {
        total_documents: 70,
        last_updated: null,
        by_type: [{ doc_type: 'judgment', count: 70 }],
        postgres_status: 'healthy',
        chroma_status: 'degraded',
        chroma_detail: '1358 vectors but 1356 PostgreSQL chunks.',
        chroma_record_count: 1358,
        bm25_status: 'healthy',
        bm25_detail: null,
        bm25_record_count: 1356,
        postgres_chunk_count: 1356,
        reconciliation_job_count: 1,
        reconciliation_jobs: [
          {
            job_id: 'job-7',
            error_code: 'LEXICAL_INDEX_FAILED',
            error_message: 'The keyword index could not be updated.',
            completed_at: '2026-10-19T08:30:00Z',
          },
        ],
      },
    ]);

    const stats = await adminIngestionApi.getCorpusStats();

    expect(stats).toMatchObject({
      chromaDb: { status: 'degraded', detail: '1358 vectors but 1356 PostgreSQL chunks.' },
      keywordIndex: { status: 'healthy' },
      chromaRecordCount: 1358,
      keywordRecordCount: 1356,
      postgresChunkCount: 1356,
      reconciliationJobCount: 1,
      reconciliationJobs: [
        {
          jobId: 'job-7',
          errorCode: 'LEXICAL_INDEX_FAILED',
          message: 'The keyword index could not be updated.',
          completedAt: '2026-10-19T08:30:00Z',
        },
      ],
    });
    expect(stats.keywordIndex).not.toHaveProperty('detail');
  });
});

describe('rate limit errors', () => {
  it('keeps the Retry-After seconds and the plain-language message', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>().mockResolvedValue({
        ok: false,
        status: 429,
        headers: new Headers({ 'Retry-After': '42' }),
        json: async () => ({
          error:
            "You've asked several questions in a short time. Please wait about a minute and try again.",
          code: 'RATE_LIMITED',
          detail: { retry_after: 42 },
        }),
      } as Response),
    );
    const error = await queryApi.submitText('What is bail?').catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiClientError);
    expect((error as ApiClientError).retryAfterSeconds).toBe(42);
    expect(limitMessage(error)).toContain('Please wait about a minute');
    expect(limitMessage(new ApiClientError('boom', 500, 'QUERY_PIPELINE_UNAVAILABLE'))).toBeNull();
    // Step 18: the models are still warming up; its message is written for end users too.
    expect(
      limitMessage(
        new ApiClientError('The legal search is still starting up.', 503, 'MODELS_LOADING'),
      ),
    ).toBe('The legal search is still starting up.');
    vi.unstubAllGlobals();
  });
});

function mockFetch(bodies: unknown[]) {
  const fetchMock = vi.fn<typeof fetch>();
  bodies.forEach((body) =>
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => body,
    } as Response),
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function professionalResponse() {
  return {
    identified_sections: [],
    precedents: [],
    case_brief: {
      summary: 'Summary',
      applicable_law: [],
      key_issues: [],
      procedural_considerations: [],
      precedent_analysis: [],
      limitations: [],
    },
  };
}

describe('unified error contract (BE-003)', () => {
  function errorResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
    return {
      ok: false,
      status,
      headers: new Headers(headers),
      json: async () => body,
    } as Response;
  }

  async function failure(response: Response): Promise<ApiClientError> {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(response));
    const caught = await queryApi.submitText('What is bail?').catch((error: unknown) => error);
    expect(caught).toBeInstanceOf(ApiClientError);
    return caught as ApiClientError;
  }

  it('reads error, code and detail from every error body', async () => {
    const validation = await failure(
      errorResponse(422, {
        error: 'Some of the submitted information is missing or invalid.',
        code: 'VALIDATION_ERROR',
        detail: { fields: [{ field: 'body.text', message: 'Field required', type: 'missing' }] },
      }),
    );
    expect(validation.message).toBe('Some of the submitted information is missing or invalid.');
    expect([validation.status, validation.code]).toEqual([422, 'VALIDATION_ERROR']);
    expect(validation.detail).toEqual({
      fields: [{ field: 'body.text', message: 'Field required', type: 'missing' }],
    });

    const duplicate = await failure(
      errorResponse(409, {
        error: 'This document has already been ingested.',
        code: 'DOCUMENT_ALREADY_INGESTED',
        detail: { document_id: 7 },
      }),
    );
    expect([duplicate.code, duplicate.detail]).toEqual([
      'DOCUMENT_ALREADY_INGESTED',
      { document_id: 7 },
    ]);

    const signedOut = await failure(
      errorResponse(401, {
        error: 'Please sign in to continue.',
        code: 'NOT_AUTHENTICATED',
        detail: null,
      }),
    );
    expect([signedOut.message, signedOut.code, signedOut.detail]).toEqual([
      'Please sign in to continue.',
      'NOT_AUTHENTICATED',
      undefined,
    ]);
  });

  it('keeps the request ID of a 500 and shows only the generic message', async () => {
    const internal = await failure(
      errorResponse(
        500,
        {
          error: 'Something went wrong on our side. Please try again in a moment.',
          code: 'INTERNAL_ERROR',
          detail: { request_id: 'req-123' },
        },
        { 'X-Request-ID': 'req-123' },
      ),
    );
    expect(internal.message).toBe(
      'Something went wrong on our side. Please try again in a moment.',
    );
    expect([internal.code, internal.requestId, internal.detail]).toEqual([
      'INTERNAL_ERROR',
      'req-123',
      { request_id: 'req-123' },
    ]);
  });

  it('gives the plain-language limit message for MODEL_BUSY with its Retry-After', async () => {
    const busy = await failure(
      errorResponse(
        503,
        {
          error: 'Many people are asking questions right now. Please try again in a moment.',
          code: 'MODEL_BUSY',
          detail: { retry_after: 15 },
        },
        { 'Retry-After': '15' },
      ),
    );
    expect(busy.retryAfterSeconds).toBe(15);
    expect(limitMessage(busy)).toBe(
      'Many people are asking questions right now. Please try again in a moment.',
    );
  });

  it('says when daily capacity returns for DAILY_CAPACITY_REACHED (step 24b)', async () => {
    const reached = await failure(
      errorResponse(
        503,
        {
          error: "Today's answer capacity has been reached. Please try again later.",
          code: 'DAILY_CAPACITY_REACHED',
          detail: { retry_after: 7200 },
        },
        { 'Retry-After': '7200' },
      ),
    );
    expect(reached.retryAfterSeconds).toBe(7200);
    expect(limitTitle(reached)).toBe('Daily capacity reached');
    expect(limitMessage(reached)).toMatch(
      /^Today's AI capacity has been reached — please try again after .+\.$/,
    );
    const now = new Date(2026, 9, 31, 10, 0, 0);
    const later = new Date(2026, 9, 31, 12, 0, 0).toLocaleTimeString([], {
      hour: 'numeric',
      minute: '2-digit',
    });
    expect(dailyCapacityMessage(7200, now)).toBe(
      `Today's AI capacity has been reached — please try again after ${later}.`,
    );
    expect(dailyCapacityMessage(16 * 3600, now)).toMatch(/tomorrow\.$/);
    expect(dailyCapacityMessage(undefined, now)).toBe(
      "Today's AI capacity has been reached — please try again later.",
    );
    expect(limitTitle(new ApiClientError('busy', 503, 'MODEL_BUSY', 15))).toBe('Please slow down');
  });

  it('does not read the retired {detail: {code, message}} or {detail: string} shapes', async () => {
    const retired = await failure(
      errorResponse(429, { detail: { code: 'RATE_LIMITED', message: 'old shape' } }),
    );
    expect([retired.code, retired.message]).toEqual([
      undefined,
      'The request could not be completed.',
    ]);
    const retiredString = await failure(errorResponse(400, { detail: 'old string' }));
    expect(retiredString.message).toBe('The request could not be completed.');
  });

  it('falls back to a safe message when a proxy answers without JSON', async () => {
    const proxy = await failure({
      ok: false,
      status: 502,
      headers: new Headers(),
      json: async () => {
        throw new SyntaxError('Unexpected token <');
      },
    } as unknown as Response);
    expect([proxy.status, proxy.code, proxy.message]).toEqual([
      502,
      undefined,
      'The LegalAI service is temporarily unavailable.',
    ]);
  });
});
