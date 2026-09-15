'use client';

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { authApi } from '../api';
import type { AuthenticatedUser, UserRole } from '../types/api';

type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated';

interface AuthContextValue {
  user: AuthenticatedUser | null;
  role: UserRole | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  status: AuthStatus;
  login: (email: string, password: string) => Promise<AuthenticatedUser>;
  logout: () => Promise<void>;
  refreshSession: () => Promise<AuthenticatedUser | null>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [status, setStatus] = useState<AuthStatus>('loading');

  const refreshSession = useCallback(async () => {
    try {
      const currentUser = await authApi.me();
      setUser(currentUser);
      setStatus('authenticated');
      return currentUser;
    } catch {
      setUser(null);
      setStatus('unauthenticated');
      return null;
    }
  }, []);

  useEffect(() => {
    const task = window.setTimeout(() => {
      void refreshSession();
    }, 0);
    return () => window.clearTimeout(task);
  }, [refreshSession]);

  const login = useCallback(
    async (email: string, password: string) => {
      await authApi.login(email, password);
      const currentUser = await refreshSession();
      if (!currentUser) {
        throw new Error('Login succeeded, but the session could not be verified.');
      }
      return currentUser;
    },
    [refreshSession],
  );

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } finally {
      setUser(null);
      setStatus('unauthenticated');
    }
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      role: user?.role ?? null,
      isAuthenticated: status === 'authenticated',
      isLoading: status === 'loading',
      status,
      login,
      logout,
      refreshSession,
    }),
    [login, logout, refreshSession, status, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error('useAuth must be used inside AuthProvider');
  }
  return value;
}

export function useOptionalAuth(): AuthContextValue | null {
  return useContext(AuthContext);
}
