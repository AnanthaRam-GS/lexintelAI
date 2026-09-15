import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { authApi } from '../api';
import { AuthProvider, useAuth } from './AuthContext';

function SessionProbe() {
  const { isLoading, logout, user } = useAuth();
  if (isLoading) return <p>Loading</p>;

  return (
    <div>
      <p>{user?.email ?? 'Signed out'}</p>
      <button onClick={() => void logout().catch(() => undefined)} type="button">
        Log out
      </button>
    </div>
  );
}

describe('AuthProvider', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('retains the authenticated identity when the server does not confirm logout', async () => {
    vi.spyOn(authApi, 'me').mockResolvedValue({
      id: 1,
      email: 'lawyer@legalai.test',
      role: 'lawyer',
    });
    vi.spyOn(authApi, 'logout').mockRejectedValue(new TypeError('Failed to fetch'));
    const user = userEvent.setup();

    render(
      <AuthProvider>
        <SessionProbe />
      </AuthProvider>,
    );

    expect(await screen.findByText('lawyer@legalai.test')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Log out' }));

    expect(screen.getByText('lawyer@legalai.test')).toBeInTheDocument();
    expect(screen.queryByText('Signed out')).not.toBeInTheDocument();
  });
});
