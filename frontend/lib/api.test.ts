import { afterEach, describe, expect, it, vi } from 'vitest';

import { adminIngestionApi, analyticsApi, authApi, historyApi, queryApi } from './api';

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
    });
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
