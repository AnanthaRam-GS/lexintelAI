import { afterEach, describe, expect, it, vi } from 'vitest';

import { fetchPublicQuery, type PublicQueryInput, type PublicQueryResponse } from './query-client';

const originalApiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;

afterEach(() => {
  vi.restoreAllMocks();

  if (originalApiBaseUrl === undefined) {
    delete process.env.NEXT_PUBLIC_API_BASE_URL;
  } else {
    process.env.NEXT_PUBLIC_API_BASE_URL = originalApiBaseUrl;
  }
});

describe('fetchPublicQuery', () => {
  it('posts a text query to the public backend endpoint without authorization', async () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = 'https://api.legalai.test/';
    const fetchMock = mockFetch(okResponse(responseFixture()));

    const response = await fetchPublicQuery({
      kind: 'text',
      content: '  Can the police arrest me without notice?  ',
    });

    expect(response).toEqual(responseFixture());
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const firstCall = fetchMock.mock.calls[0];
    const url = firstCall?.[0];
    const init = firstCall?.[1];
    expect(url).toBe('https://api.legalai.test/query/public');
    expect(init).toMatchObject({
      method: 'POST',
      credentials: 'include',
      body: JSON.stringify({ text: 'Can the police arrest me without notice?' }),
    });
    expect(headers(init)).toMatchObject({ 'content-type': 'application/json' });
    expect(headers(init)).not.toHaveProperty('authorization');
  });

  it('uses the development backend URL when no public base URL is configured', async () => {
    delete process.env.NEXT_PUBLIC_API_BASE_URL;
    const fetchMock = mockFetch(okResponse(responseFixture()));

    await fetchPublicQuery({ kind: 'text', content: 'Help me' });

    expect(fetchMock.mock.calls[0]?.[0]).toBe('http://127.0.0.1:8000/query/public');
  });

  it('forwards an AbortSignal so a cancelled public request stops at the network boundary', async () => {
    const fetchMock = mockFetch(okResponse(responseFixture()));
    const controller = new AbortController();

    await fetchPublicQuery({ kind: 'text', content: 'Help me' }, { signal: controller.signal });

    expect(fetchMock.mock.calls[0]?.[1]?.signal).toBe(controller.signal);
  });

  it('parses the exact public response contract', async () => {
    const expected = responseFixture();
    mockFetch(okResponse(expected));

    const response = await fetchPublicQuery({ kind: 'text', content: 'Help me' });

    expect(response).toEqual({
      explanation: expected.explanation,
      sections: expected.sections,
      sources: expected.sources,
      nextStepGuidance: expected.nextStepGuidance,
    });
    expect(response).not.toHaveProperty('confidence');
    expect(response).not.toHaveProperty('metadata');
  });

  it('rejects network errors through the safe public UI path', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>().mockRejectedValue(new Error('/private/path timeout')),
    );

    await expect(fetchPublicQuery({ kind: 'text', content: 'Help me' })).rejects.toThrow(
      '/private/path timeout',
    );
  });

  it('maps backend validation errors without requiring provider internals', async () => {
    mockFetch({
      ok: false,
      status: 422,
      json: async () => ({
        detail: {
          code: 'INVALID_QUERY_REQUEST',
          message: 'The request could not be completed.',
        },
      }),
    } as Response);

    await expect(fetchPublicQuery({ kind: 'text', content: 'Help me' })).rejects.toThrow(
      'The request could not be completed.',
    );
  });

  it('maps backend/provider failures to safe errors', async () => {
    mockFetch({
      ok: false,
      status: 503,
      json: async () => ({
        detail: {
          code: 'MODEL_UNAVAILABLE',
          message: 'The legal answer model is temporarily unavailable.',
        },
      }),
    } as Response);

    await expect(fetchPublicQuery({ kind: 'text', content: 'Help me' })).rejects.toThrow(
      'The legal answer model is temporarily unavailable.',
    );
  });

  it('does not send empty queries', async () => {
    const fetchMock = mockFetch(okResponse(responseFixture()));

    await expect(fetchPublicQuery({ kind: 'text', content: '   ' })).rejects.toThrow(
      'Public query text must not be empty.',
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('sends PDF input plus the user-entered question to the public multipart endpoint', async () => {
    const fetchMock = mockFetch(okResponse(responseFixture()));
    const file = new File(['%PDF-1.4'], 'notice.pdf', { type: 'application/pdf' });

    await fetchPublicQuery({
      kind: 'file',
      file,
      question: '  What does this notice require me to do?  ',
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe('http://127.0.0.1:8000/query/public/pdf');
    const request = fetchMock.mock.calls[0]?.[1];
    expect(request?.body).toBeInstanceOf(FormData);
    expect((request?.body as FormData).get('file')).toBe(file);
    expect((request?.body as FormData).get('query')).toBe(
      'What does this notice require me to do?',
    );
    expect(new Headers(request?.headers).has('Content-Type')).toBe(false);
  });

  it('does not invent a question and does not send PDF queries with no question', async () => {
    const fetchMock = mockFetch(okResponse(responseFixture()));
    const file = new File(['%PDF-1.4'], 'notice.pdf', { type: 'application/pdf' });

    await expect(fetchPublicQuery({ kind: 'file', file, question: '   ' })).rejects.toThrow(
      'A question is required to analyze this PDF.',
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('rejects an invalid discriminant before fetch', async () => {
    const fetchMock = mockFetch(okResponse(responseFixture()));

    await expect(
      fetchPublicQuery({ kind: 'unsupported' } as unknown as PublicQueryInput),
    ).rejects.toThrow('Public query input must have a text or file kind.');
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

function responseFixture(): PublicQueryResponse {
  return {
    explanation: 'This is general legal information.',
    sections: [
      {
        title: 'BNSS section 35',
        explanation: 'Applicability depends on the facts.',
        link: 'https://www.indiacode.nic.in/',
      },
    ],
    sources: [{ title: 'Example v State', link: 'https://example.test/judgment' }],
    nextStepGuidance: 'Keep copies of relevant documents.',
  };
}

function okResponse(body: PublicQueryResponse): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
  } as Response;
}

function mockFetch(response: Response) {
  const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(response);
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function headers(init: RequestInit | undefined): Record<string, string> {
  return Object.fromEntries(new Headers(init?.headers).entries());
}
