'use client';

import { useEffect, type ReactNode } from 'react';
import { useRouter } from 'next/navigation';

import { useAuth } from '../../lib/auth/AuthContext';
import { LoadingSpinner } from '../shared/LoadingSpinner';

export function ProtectedRoute({
  children,
  requiredRole,
}: {
  children: ReactNode;
  requiredRole: 'admin' | 'lawyer';
}) {
  const router = useRouter();
  const { isLoading, user } = useAuth();
  const isAuthorized = user?.role === requiredRole;

  useEffect(() => {
    if (isLoading || isAuthorized) return;
    router.replace(
      user?.role === 'admin' ? '/admin' : user?.role === 'lawyer' ? '/professional' : '/login',
    );
  }, [isAuthorized, isLoading, router, user?.role]);

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[var(--color-canvas)]">
        <LoadingSpinner label="Checking access" />
      </div>
    );
  }

  return isAuthorized ? children : null;
}
