import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { authApi } from '../../lib/api';
import { AuthProvider } from '../../lib/auth/AuthContext';
import { ProtectedRoute } from './ProtectedRoute';

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));

vi.mock('next/navigation', () => ({
  usePathname: () => null,
  useRouter: () => ({ replace }),
}));

describe('ProtectedRoute', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    replace.mockReset();
  });

  it('renders the protected content after the backend confirms the required role', async () => {
    vi.spyOn(authApi, 'me').mockResolvedValue({
      id: 1,
      email: 'admin@legalai.test',
      role: 'admin',
    });

    render(
      <AuthProvider>
        <ProtectedRoute allowedRoles={['admin']}>
          <p>Protected admin content</p>
        </ProtectedRoute>
      </AuthProvider>,
    );

    expect(await screen.findByText('Protected admin content')).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it('redirects an unauthenticated visitor without exposing protected content', async () => {
    vi.spyOn(authApi, 'me').mockRejectedValue(new Error('Not authenticated'));

    render(
      <AuthProvider>
        <ProtectedRoute allowedRoles={['admin']}>
          <p>Protected admin content</p>
        </ProtectedRoute>
      </AuthProvider>,
    );

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/login'));
    expect(screen.queryByText('Protected admin content')).not.toBeInTheDocument();
  });

  it('redirects a signed-in user away from a portal for another role', async () => {
    vi.spyOn(authApi, 'me').mockResolvedValue({
      id: 2,
      email: 'lawyer@legalai.test',
      role: 'lawyer',
    });

    render(
      <AuthProvider>
        <ProtectedRoute allowedRoles={['admin']}>
          <p>Protected admin content</p>
        </ProtectedRoute>
      </AuthProvider>,
    );

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/professional'));
    expect(screen.queryByText('Protected admin content')).not.toBeInTheDocument();
  });

  it('allows an admin into Professional Mode when both authenticated roles are permitted', async () => {
    vi.spyOn(authApi, 'me').mockResolvedValue({
      id: 1,
      email: 'admin@legalai.test',
      role: 'admin',
    });

    render(
      <AuthProvider>
        <ProtectedRoute allowedRoles={['lawyer', 'admin']}>
          <p>Professional content</p>
        </ProtectedRoute>
      </AuthProvider>,
    );

    expect(await screen.findByText('Professional content')).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });
});
