import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { authApi } from '../../lib/api';
import VerifyEmailPage from './page';

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace }),
  useSearchParams: () => new URLSearchParams('email=public%40example.test&next=%2Flawyer%2Fapply'),
}));

describe('VerifyEmailPage', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    replace.mockReset();
  });

  it('validates and verifies a six-digit OTP', async () => {
    const verify = vi
      .spyOn(authApi, 'verifyEmail')
      .mockResolvedValue({ email_verified: true, message: 'ok' });
    const user = userEvent.setup();

    render(<VerifyEmailPage />);

    await user.type(screen.getByLabelText('Verification code'), '123456');
    await user.click(screen.getByRole('button', { name: 'Verify email' }));

    await waitFor(() => expect(verify).toHaveBeenCalledWith('public@example.test', '123456'));
    expect(replace).toHaveBeenCalledWith('/lawyer/apply');
  });

  it('resends a code for the current email', async () => {
    const resend = vi
      .spyOn(authApi, 'resendVerification')
      .mockResolvedValue({ email_verified: false, message: 'sent' });
    const user = userEvent.setup();

    render(<VerifyEmailPage />);

    await user.click(screen.getByRole('button', { name: 'Resend code' }));

    await waitFor(() => expect(resend).toHaveBeenCalledWith('public@example.test'));
  });
});
