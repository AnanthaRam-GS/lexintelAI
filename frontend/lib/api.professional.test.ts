import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { analyticsApi, authApi, historyApi, queryApi } from './api';

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

describe('professional API contracts', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({}))),
    );
    vi.stubEnv('NEXT_PUBLIC_API_BASE_URL', 'http://api.test/');
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it('submits login credentials without a client-provided role', async () => {
    await authApi.login('lawyer@example.test', 'secret-password');

    expect(fetch).toHaveBeenCalledWith(
      'http://api.test/auth/login',
      expect.objectContaining({
        credentials: 'include',
        method: 'POST',
        body: JSON.stringify({ email: 'lawyer@example.test', password: 'secret-password' }),
      }),
    );
    const init = vi.mocked(fetch).mock.calls[0][1] as RequestInit;
    expect(String(init.body)).not.toContain('role');
  });

  it('checks and clears the cookie-backed session', async () => {
    await authApi.me();
    await authApi.logout();

    expect(fetch).toHaveBeenNthCalledWith(
      1,
      'http://api.test/auth/me',
      expect.objectContaining({ credentials: 'include' }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      'http://api.test/auth/logout',
      expect.objectContaining({ credentials: 'include', method: 'POST' }),
    );
  });

  it('submits professional text queries using the backend JSON schema', async () => {
    await queryApi.submitText('Research bail', 'session-1');

    expect(fetch).toHaveBeenCalledWith(
      'http://api.test/query/professional',
      expect.objectContaining({
        credentials: 'include',
        method: 'POST',
        body: JSON.stringify({ text: 'Research bail', session_id: 'session-1' }),
      }),
    );
  });

  it('submits private professional PDFs as multipart without an Authorization header', async () => {
    const file = new File(['%PDF-1.4'], 'brief.pdf', { type: 'application/pdf' });

    await queryApi.submitPdf(file, 'Analyze this brief', 'session-2');

    expect(fetch).toHaveBeenCalledWith(
      'http://api.test/query/professional/pdf',
      expect.objectContaining({
        credentials: 'include',
        method: 'POST',
      }),
    );
    const init = vi.mocked(fetch).mock.calls[0][1] as RequestInit;
    expect(init.headers).toBeUndefined();
    expect(init.body).toBeInstanceOf(FormData);
    const body = init.body as FormData;
    expect(body.get('query')).toBe('Analyze this brief');
    expect(body.get('file')).toBe(file);
    expect(body.get('session_id')).toBe('session-2');
  });

  it('uses authenticated history and analytics endpoints', async () => {
    await historyApi.getQueryHistory(25);
    await analyticsApi.getOffenseFrequency();
    await analyticsApi.getOutcomeDistribution();
    await analyticsApi.getSectionCooccurrence();
    await analyticsApi.getIpcBnsMap();
    await analyticsApi.getNcrbStats();

    expect(vi.mocked(fetch).mock.calls.map(([url]) => url)).toEqual([
      'http://api.test/query/history?limit=25',
      'http://api.test/analytics/offense-frequency',
      'http://api.test/analytics/outcome-distribution',
      'http://api.test/analytics/section-cooccurrence',
      'http://api.test/analytics/ipc-bns-map',
      'http://api.test/analytics/ncrb-stats',
    ]);
  });
});
