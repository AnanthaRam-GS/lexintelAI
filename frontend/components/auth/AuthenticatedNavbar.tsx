'use client';

import { useRouter } from 'next/navigation';

import { useAuth } from '../../lib/auth/AuthContext';
import { Navbar } from '../Navbar';

export function AuthenticatedNavbar() {
  const router = useRouter();
  const { logout, user } = useAuth();

  const handleLogout = async () => {
    try {
      await logout();
    } catch {
      // AuthContext clears local identity even if the server cannot be reached.
    } finally {
      router.replace('/login');
    }
  };

  return <Navbar onLogout={handleLogout} user={user} />;
}
