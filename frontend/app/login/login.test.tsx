import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import LoginPage from './page';

const replace = vi.fn();
let nextPath: string | null = null;

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace }),
  useSearchParams: () => ({
    get: (key: string) => (key === 'next' ? nextPath : null),
  }),
}));

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

describe('LoginPage', () => {
  beforeEach(() => {
    replace.mockClear();
    nextPath = null;
    vi.stubEnv('NEXT_PUBLIC_API_BASE_URL', 'http://api.test');
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it('posts credentials, refreshes /auth/me, and redirects by backend role', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse({}, 401))
        .mockResolvedValueOnce(
          jsonResponse({
            user: { id: 1, email: 'admin@example.test', role: 'admin', email_verified: true },
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({ id: 1, email: 'admin@example.test', role: 'admin', email_verified: true }),
        ),
    );

    render(<LoginPage />);

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        'http://api.test/auth/me',
        expect.objectContaining({ credentials: 'include' }),
      );
    });

    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'admin@example.test' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'secret-password' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));

    await waitFor(() => {
      expect(replace).toHaveBeenCalledWith('/admin');
    });

    const loginInit = vi.mocked(fetch).mock.calls[1][1] as RequestInit;
    expect(loginInit.body).toBe(
      JSON.stringify({ email: 'admin@example.test', password: 'secret-password' }),
    );
    expect(String(loginInit.body)).not.toContain('role');
  });

  it('uses a safe next path when the backend role is authorized for it', async () => {
    nextPath = '/professional/query';
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse({}, 401))
        .mockResolvedValueOnce(
          jsonResponse({
            user: { id: 2, email: 'lawyer@example.test', role: 'lawyer', email_verified: true },
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            id: 2,
            email: 'lawyer@example.test',
            role: 'lawyer',
            email_verified: true,
          }),
        ),
    );

    render(<LoginPage />);

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        'http://api.test/auth/me',
        expect.objectContaining({ credentials: 'include' }),
      );
    });

    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'lawyer@example.test' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'secret-password' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));

    await waitFor(() => {
      expect(replace).toHaveBeenCalledWith('/professional/query');
    });
  });
});
