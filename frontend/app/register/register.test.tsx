import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { authApi } from '../../lib/api';
import RegisterPage from './page';

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace }),
}));

describe('RegisterPage', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    replace.mockReset();
  });

  it('creates a public account without sending a role and navigates to OTP verification', async () => {
    const register = vi.spyOn(authApi, 'register').mockResolvedValue({
      email_verification_required: true,
      message: 'ok',
      user: { id: 1, email: 'public@example.test', role: 'public' },
    });
    const user = userEvent.setup();

    render(<RegisterPage />);

    await user.type(screen.getByLabelText('Full name'), 'Public User');
    await user.type(screen.getByLabelText('Email'), 'public@example.test');
    await user.type(screen.getByLabelText('Password'), 'Password123!');
    await user.type(screen.getByLabelText('Confirm password'), 'Password123!');
    await user.click(screen.getByLabelText(/take me to lawyer verification/i));
    await user.click(screen.getByRole('button', { name: 'Create public account' }));

    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith(
        '/verify-email?email=public%40example.test&next=%2Flawyer%2Fapply',
      ),
    );
    expect(register).toHaveBeenCalledWith('Public User', 'public@example.test', 'Password123!');
    expect(JSON.stringify(register.mock.calls)).not.toContain('lawyer');
    expect(screen.getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/login');
  });

  it('validates matching passwords before calling the API', async () => {
    const register = vi.spyOn(authApi, 'register').mockResolvedValue({
      email_verification_required: true,
      message: 'ok',
      user: { id: 1, email: 'public@example.test', role: 'public' },
    });
    const user = userEvent.setup();

    render(<RegisterPage />);

    await user.type(screen.getByLabelText('Full name'), 'Public User');
    await user.type(screen.getByLabelText('Email'), 'public@example.test');
    await user.type(screen.getByLabelText('Password'), 'Password123!');
    await user.type(screen.getByLabelText('Confirm password'), 'Different123!');
    await user.click(screen.getByRole('button', { name: 'Create public account' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Passwords must match.');
    expect(register).not.toHaveBeenCalled();
  });
});
