'use client';

import { useEffect, type ReactNode } from 'react';
import { usePathname, useRouter } from 'next/navigation';

import { useAuth } from '../../lib/auth/AuthContext';
import type { UserRole } from '../../lib/types/api';
import { LoadingSpinner } from '../shared/LoadingSpinner';

interface ProtectedRouteProps {
  allowedRoles?: readonly UserRole[];
  requiredRole?: UserRole;
  children: ReactNode;
}

export function ProtectedRoute({ allowedRoles, requiredRole, children }: ProtectedRouteProps) {
  const router = useRouter();
  const pathname = usePathname();
  const { isLoading, user } = useAuth();
  const effectiveRoles = allowedRoles ?? (requiredRole ? allowedRolesFor(requiredRole) : undefined);
  const isAuthorized = user && effectiveRoles ? effectiveRoles.includes(user.role) : false;

  useEffect(() => {
    if (isLoading || isAuthorized) return;
    router.replace(user ? workspaceFor(user.role) : loginPath(pathname));
  }, [isAuthorized, isLoading, pathname, router, user]);

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[var(--color-canvas)]">
        <LoadingSpinner label="Checking access" />
      </div>
    );
  }

  return isAuthorized ? children : null;
}

function allowedRolesFor(requiredRole: UserRole): readonly UserRole[] {
  return requiredRole === 'lawyer' ? ['lawyer', 'admin'] : ['admin'];
}

function workspaceFor(role: UserRole): string {
  return role === 'admin' ? '/admin' : '/professional';
}

function loginPath(pathname: string | null): string {
  if (!pathname || pathname === '/' || pathname.startsWith('/login')) {
    return '/login';
  }
  return `/login?next=${encodeURIComponent(pathname)}`;
}
