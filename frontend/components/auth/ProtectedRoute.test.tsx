import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ProtectedRoute } from './ProtectedRoute';
import { AuthProvider } from '../../lib/auth/AuthContext';

const replace = vi.fn();
let pathname = '/professional';

vi.mock('next/navigation', () => ({
  usePathname: () => pathname,
import { afterEach, describe, expect, it, vi } from 'vitest';

import { authApi } from '../../lib/api';
import { AuthProvider } from '../../lib/auth/AuthContext';
import { ProtectedRoute } from './ProtectedRoute';

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));

vi.mock('next/navigation', () => ({
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

    await waitFor(() => {
      expect(replace).toHaveBeenCalledWith('/professional');
    });
    expect(screen.queryByText('Admin content')).not.toBeInTheDocument();
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
