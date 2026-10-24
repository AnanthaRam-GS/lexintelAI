import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiClientError, apiFetch } from '../../lib/api';

import { classifyPublicAnswerFailure, errorCopy } from './error-copy';

describe('classifyPublicAnswerFailure', () => {
  it('maps a 429 quota code to the quota-safe failure kind', () => {
    const error = new ApiClientError('rate limited', 429, 'MODEL_PROVIDER_QUOTA_EXCEEDED');

    expect(classifyPublicAnswerFailure(error)).toBe('model-quota-exceeded');
    expect(errorCopy.public.answer['model-quota-exceeded'].message).toBe(
      'AI answer service has reached its temporary usage limit. Please try again later.',
    );
  });

  it('maps the OCR errors to plain-language scanned-document kinds', () => {
    expect(classifyPublicAnswerFailure(new ApiClientError('cap', 422, 'OCR_LIMIT_EXCEEDED'))).toBe(
      'ocr-too-many-pages',
    );
    expect(classifyPublicAnswerFailure(new ApiClientError('no ocr', 503, 'OCR_UNAVAILABLE'))).toBe(
      'ocr-unavailable',
    );
    expect(errorCopy.public.answer['ocr-unavailable'].message).toContain('selectable text');
  });

  it('maps our own rate limit and busy answers to plain-language kinds, not the quota kind', () => {
    expect(classifyPublicAnswerFailure(new ApiClientError('wait', 429, 'RATE_LIMITED', 42))).toBe(
      'rate-limited',
    );
    expect(classifyPublicAnswerFailure(new ApiClientError('busy', 503, 'MODEL_BUSY', 15))).toBe(
      'model-busy',
    );
    expect(errorCopy.public.answer['rate-limited'].title).toBe('Please slow down');
    expect(errorCopy.public.answer['rate-limited'].message).toContain(
      'Your question is still here',
    );
  });

  it('maps a bare 429 status without a recognized code to the quota-safe failure kind', () => {
    const error = new ApiClientError('rate limited', 429, 'SOME_OTHER_CODE');

    expect(classifyPublicAnswerFailure(error)).toBe('model-quota-exceeded');
  });

  it('maps MODEL_UNAVAILABLE to the generic unavailable failure kind', () => {
    const error = new ApiClientError('unavailable', 503, 'MODEL_UNAVAILABLE');

    expect(classifyPublicAnswerFailure(error)).toBe('model-unavailable');
    expect(errorCopy.public.answer['model-unavailable'].title).toBe('Answer service unavailable');
  });

  it('maps MODEL_PROVIDER_ERROR to the generic unavailable failure kind', () => {
    const error = new ApiClientError('provider failed', 503, 'MODEL_PROVIDER_ERROR');

    expect(classifyPublicAnswerFailure(error)).toBe('model-unavailable');
  });

  it('maps a bare 503 status without a recognized code to the unavailable failure kind', () => {
    const error = new ApiClientError('service failed', 503, 'UNMAPPED_CODE');

    expect(classifyPublicAnswerFailure(error)).toBe('model-unavailable');
  });

  it('never leaks the raw provider error message into the classification result', () => {
    const error = new ApiClientError(
      'Gemini request failed with HTTP 429: quota exceeded for project abc123',
      429,
      'MODEL_PROVIDER_QUOTA_EXCEEDED',
    );

    const failure = classifyPublicAnswerFailure(error);

    expect(errorCopy.public.answer[failure].message).not.toContain('abc123');
    expect(errorCopy.public.answer[failure].message).not.toContain('Gemini');
  });

  it('maps a network TypeError to the network failure kind', () => {
    const error = new TypeError('Failed to fetch');

    expect(classifyPublicAnswerFailure(error)).toBe('network');
  });

  it('falls back to the generic service failure kind for an unrecognized error', () => {
    const error = new Error('unexpected');

    expect(classifyPublicAnswerFailure(error)).toBe('service');
  });
});

describe('backend error bodies to public copy', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('classifies the unified {error, code, detail} body by its code', async () => {
    const cases: [number, string, ReturnType<typeof classifyPublicAnswerFailure>][] = [
      [413, 'PDF_TOO_LARGE', 'pdf-too-large'],
      [400, 'INVALID_PDF_HEADER', 'invalid-pdf'],
      [422, 'PDF_CHUNKING_FAILED', 'pdf-empty'],
      [422, 'OCR_LIMIT_EXCEEDED', 'ocr-too-many-pages'],
      [503, 'OCR_UNAVAILABLE', 'ocr-unavailable'],
      [429, 'RATE_LIMITED', 'rate-limited'],
      [503, 'MODEL_BUSY', 'model-busy'],
      [503, 'MODEL_UNAVAILABLE', 'model-unavailable'],
      [500, 'INTERNAL_ERROR', 'service'],
    ];
    for (const [status, code, kind] of cases) {
      vi.stubGlobal(
        'fetch',
        vi.fn<typeof fetch>().mockResolvedValue({
          ok: false,
          status,
          headers: new Headers(),
          json: async () => ({ error: 'server message', code, detail: null }),
        } as Response),
      );
      const caught = await apiFetch('/query/public').catch((error: unknown) => error);
      expect([code, classifyPublicAnswerFailure(caught)]).toEqual([code, kind]);
    }
  });
});
