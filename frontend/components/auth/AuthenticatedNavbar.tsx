'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';

import { useAuth } from '../../lib/auth/AuthContext';
import { Navbar } from '../Navbar';
import { ErrorMessage } from '../shared/ErrorMessage';

export function AuthenticatedNavbar() {
  const router = useRouter();
  const { logout, user } = useAuth();
  const [logoutFailed, setLogoutFailed] = useState(false);

  const handleLogout = async () => {
    setLogoutFailed(false);
    try {
      await logout();
    } catch {
      setLogoutFailed(true);
      return;
    }
    router.replace('/login');
  };

  return (
    <>
      <Navbar onLogout={handleLogout} user={user} />
      {logoutFailed ? (
        <div className="mx-auto w-full max-w-7xl px-4 pt-4 sm:px-6 lg:px-8">
          <ErrorMessage
            message="Your session is still active. Check your connection, then try again."
            onRetry={() => void handleLogout()}
            title="Couldn't sign out"
            variant="banner"
          />
        </div>
      ) : null}
    </>
  );
}
