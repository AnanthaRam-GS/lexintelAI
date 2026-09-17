import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { authApi } from '../../lib/api';
import { AuthProvider } from '../../lib/auth/AuthContext';
import { LoginForm } from './LoginForm';

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace }),
  useSearchParams: () => ({
    get: () => null,
  }),
}));

describe('LoginForm', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    replace.mockReset();
  });

  it('redirects an authenticated admin to the admin workspace', async () => {
    vi.spyOn(authApi, 'me').mockRejectedValue(new Error('Not authenticated'));
    vi.spyOn(authApi, 'login').mockResolvedValue({
      message: 'Login successful',
      user: { id: 1, email: 'admin@legalai.test', role: 'admin', email_verified: true },
    });
    const user = userEvent.setup();

    render(
      <AuthProvider>
        <LoginForm />
      </AuthProvider>,
    );

    await user.type(screen.getByLabelText('Email'), 'admin@legalai.test');
    await user.type(screen.getByLabelText('Password'), 'password123');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/admin'));
  });

  it('offers explicit guest access', async () => {
    vi.spyOn(authApi, 'me').mockRejectedValue(new Error('Not authenticated'));

    render(
      <AuthProvider>
        <LoginForm />
      </AuthProvider>,
    );

    expect(await screen.findByRole('link', { name: 'Continue as guest' })).toHaveAttribute(
      'href',
      '/public',
    );
  });

  it('routes unverified users to email verification after login', async () => {
    vi.spyOn(authApi, 'me').mockRejectedValue(new Error('Not authenticated'));
    vi.spyOn(authApi, 'login').mockResolvedValue({
      message: 'Login successful',
      user: {
        id: 1,
        email: 'public@legalai.test',
        role: 'public',
        email_verified: false,
      },
    });
    const user = userEvent.setup();

    render(
      <AuthProvider>
        <LoginForm />
      </AuthProvider>,
    );

    await user.type(screen.getByLabelText('Email'), 'public@legalai.test');
    await user.type(screen.getByLabelText('Password'), 'password123');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith('/verify-email?email=public%40legalai.test'),
    );
  });

  it('shows fixed safe copy instead of a raw authentication error', async () => {
    vi.spyOn(authApi, 'me').mockRejectedValue(new Error('Not authenticated'));
    vi.spyOn(authApi, 'login').mockRejectedValue(
      new Error('postgresql://private-host users table stack trace'),
    );
    const user = userEvent.setup();

    render(
      <AuthProvider>
        <LoginForm />
      </AuthProvider>,
    );

    await user.type(screen.getByLabelText('Email'), 'admin@legalai.test');
    await user.type(screen.getByLabelText('Password'), 'wrong-password');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'We could not sign you in. Check your details and try again.',
    );
    expect(screen.getByRole('alert')).not.toHaveTextContent('private-host');
  });
});
