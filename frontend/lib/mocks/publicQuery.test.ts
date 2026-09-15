import { afterEach, describe, expect, it } from 'vitest';

import {
  configurePublicQueryMockForTests,
  fetchPublicQueryMock,
  resetPublicQueryMockForTests,
} from './publicQuery';

describe('public query mock Phase 5 controls', () => {
  afterEach(() => {
    resetPublicQueryMockForTests();
  });

  it('supports deterministic delay without changing the response contract', async () => {
    configurePublicQueryMockForTests({ delayMs: 0 });

    await expect(
      fetchPublicQueryMock({ kind: 'text', content: 'Please explain this notice' }),
    ).resolves.toMatchObject({
      explanation: expect.any(String),
      sections: expect.any(Array),
      sources: expect.any(Array),
      nextStepGuidance: expect.any(String),
    });
  });

  it('can fail a bounded number of requests as network loss and then recover', async () => {
    configurePublicQueryMockForTests({
      delayMs: 0,
      failRequests: 1,
      failureMode: 'network',
    });
    const input = { kind: 'text' as const, content: 'Please explain this notice' };

    await expect(fetchPublicQueryMock(input)).rejects.toBeInstanceOf(TypeError);
    await expect(fetchPublicQueryMock(input)).resolves.toHaveProperty('explanation');
  });

  it('can model a service failure separately from network loss', async () => {
    configurePublicQueryMockForTests({
      delayMs: 0,
      failRequests: 1,
      failureMode: 'service',
    });

    await expect(
      fetchPublicQueryMock({ kind: 'text', content: 'Please explain this notice' }),
    ).rejects.toThrow('Public query mock failed.');
  });
});
