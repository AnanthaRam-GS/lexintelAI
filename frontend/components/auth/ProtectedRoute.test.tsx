import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ProtectedRoute } from './ProtectedRoute';
import { AuthProvider } from '../../lib/auth/AuthContext';

const replace = vi.fn();
let pathname = '/professional';

vi.mock('next/navigation', () => ({
  usePathname: () => pathname,
  useRouter: () => ({ replace }),
}));

describe('ProtectedRoute', () => {
  beforeEach(() => {
    replace.mockClear();
    pathname = '/professional';
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('redirects unauthenticated users to login without rendering protected content', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 401 })));

    render(
      <AuthProvider>
        <ProtectedRoute requiredRole="lawyer">
          <p>Protected content</p>
        </ProtectedRoute>
      </AuthProvider>,
    );

    expect(screen.queryByText('Protected content')).not.toBeInTheDocument();
    await waitFor(() => {
      expect(replace).toHaveBeenCalledWith('/login?next=%2Fprofessional');
    });
  });

  it('allows admin users into lawyer routes but denies lawyer users on admin routes', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ id: 1, email: 'admin@example.test', role: 'admin' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    );

    render(
      <AuthProvider>
        <ProtectedRoute requiredRole="lawyer">
          <p>Protected content</p>
        </ProtectedRoute>
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText('Protected content')).toBeInTheDocument();
    });
  });

  it('redirects authenticated users away from disallowed roles', async () => {
    pathname = '/admin';
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ id: 2, email: 'lawyer@example.test', role: 'lawyer' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    );

    render(
      <AuthProvider>
        <ProtectedRoute requiredRole="admin">
          <p>Admin content</p>
        </ProtectedRoute>
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(replace).toHaveBeenCalledWith('/professional');
    });
    expect(screen.queryByText('Admin content')).not.toBeInTheDocument();
  });
});
