'use client';

import React, { useEffect } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { LoadingSpinner } from '../shared';
import { useAuth } from '../../lib/auth/AuthContext';
import type { UserRole } from '../../lib/types/api';

interface ProtectedRouteProps {
  children: React.ReactNode;
  requiredRole?: UserRole;
  allowedRoles?: UserRole[];
}

export function ProtectedRoute({ children, requiredRole, allowedRoles }: ProtectedRouteProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { isAuthenticated, isLoading, role } = useAuth();
  const roles = allowedRoles ?? (requiredRole ? allowedRolesFor(requiredRole) : undefined);
  const isAllowed = !roles || (role ? roles.includes(role) : false);

  useEffect(() => {
    if (isLoading) return;
    if (!isAuthenticated) {
      router.replace(`/login?next=${encodeURIComponent(pathname || '/')}`);
      return;
    }
    if (!isAllowed) {
      router.replace(role === 'admin' ? '/admin' : '/professional');
    }
  }, [isAllowed, isAuthenticated, isLoading, pathname, role, router]);

  if (isLoading || !isAuthenticated || !isAllowed) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[var(--color-canvas)]">
        <LoadingSpinner size="lg" label="Checking secure session" />
      </div>
    );
  }

  return <>{children}</>;
}

function allowedRolesFor(requiredRole: UserRole): UserRole[] {
  if (requiredRole === 'lawyer') {
    return ['lawyer', 'admin'];
  }
  return [requiredRole];
}
