import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { AuthenticatedNavbar } from './AuthenticatedNavbar';

const { logout, replace } = vi.hoisted(() => ({
  logout: vi.fn<() => Promise<void>>(),
  replace: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  usePathname: () => '/professional',
  useRouter: () => ({ replace }),
}));

vi.mock('../../lib/auth/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 1, email: 'lawyer@legalai.test', role: 'lawyer' },
    isLoading: false,
    login: vi.fn(),
    logout,
  }),
}));

describe('AuthenticatedNavbar', () => {
  afterEach(() => {
    cleanup();
    logout.mockReset();
    replace.mockReset();
  });

  it('shows the authenticated identity and returns to login after signing out', async () => {
    logout.mockResolvedValue();
    const user = userEvent.setup();
    render(<AuthenticatedNavbar />);

    expect(screen.getByText('lawyer@legalai.test')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Sign out' }));

    expect(logout).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/login'));
  });

  it('still returns to login when the logout request cannot reach the server', async () => {
    logout.mockRejectedValue(new TypeError('Failed to fetch'));
    const user = userEvent.setup();
    render(<AuthenticatedNavbar />);

    await user.click(screen.getByRole('button', { name: 'Sign out' }));

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/login'));
  });
});
