import { afterEach, describe, expect, it, vi } from 'vitest';

import { fetchPublicQuery } from './query-client';

const delayEnvironmentKey = 'NEXT_PUBLIC_LEGALAI_PUBLIC_QUERY_MOCK_DELAY_MS';
const failureEnvironmentKey = 'NEXT_PUBLIC_LEGALAI_PUBLIC_QUERY_MOCK_FAILURE';
const originalDelay = process.env[delayEnvironmentKey];
const originalFailure = process.env[failureEnvironmentKey];

afterEach(() => {
  vi.useRealTimers();

  if (originalDelay === undefined) {
    delete process.env[delayEnvironmentKey];
  } else {
    process.env[delayEnvironmentKey] = originalDelay;
  }

  if (originalFailure === undefined) {
    delete process.env[failureEnvironmentKey];
  } else {
    process.env[failureEnvironmentKey] = originalFailure;
  }
});

describe('fetchPublicQuery', () => {
  it('keeps the import boundary response limited to public fields', async () => {
    process.env[delayEnvironmentKey] = '0';

    const response = await fetchPublicQuery({
      kind: 'text',
      content: 'Help me understand my notice',
    });

    expect(response).toEqual({
      explanation: expect.any(String),
      sections: [
        {
          title: expect.any(String),
          explanation: expect.any(String),
          link: expect.stringMatching(/^https:\/\//),
        },
      ],
      sources: [{ title: expect.any(String), link: expect.stringMatching(/^https:\/\//) }],
      nextStepGuidance: expect.any(String),
    });
    expect(response).not.toHaveProperty('confidence');
    expect(response).not.toHaveProperty('metadata');
  });

  it('honors the configured mock delay without changing the one-input request shape', async () => {
    vi.useFakeTimers();
    process.env[delayEnvironmentKey] = '800';

    const request = fetchPublicQuery({ kind: 'file', file: new File(['pdf'], 'notice.pdf') });
    let settled = false;
    void request.then(() => {
      settled = true;
    });

    await vi.advanceTimersByTimeAsync(799);
    expect(settled).toBe(false);

    await vi.advanceTimersByTimeAsync(1);
    await expect(request).resolves.toEqual(
      expect.objectContaining({ explanation: expect.stringContaining('PDF') }),
    );
  });

  it('rejects through the configured public mock failure input', async () => {
    process.env[delayEnvironmentKey] = '0';
    process.env[failureEnvironmentKey] = 'true';

    await expect(fetchPublicQuery({ kind: 'text', content: 'Help me' })).rejects.toThrow(
      'Public query mock failed',
    );
  });
});
