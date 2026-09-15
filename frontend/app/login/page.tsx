'use client';

import React, { Suspense, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { ErrorMessage, LoadingSpinner } from '../../components/shared';
import { AuthProvider, useAuth } from '../../lib/auth/AuthContext';
import type { UserRole } from '../../lib/types/api';
import type { Metadata } from 'next';

import { AuthProvider } from '../../lib/auth/AuthContext';
import { LoginForm } from './LoginForm';

export const metadata: Metadata = {
  title: 'Sign in | LegalAI',
  description: 'Sign in to a protected LegalAI workspace.',
};

export default function LoginPage() {
  return (
    <AuthProvider>
      <Suspense fallback={<LoginShell isLoading />}>
        <LoginForm />
      </Suspense>
    </AuthProvider>
  );
}

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!email.trim() || !password) {
      setError('Enter your email and password to continue.');
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      const user = await login(email.trim(), password);
      router.replace(destinationFor(user.role, searchParams.get('next')));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to sign in.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <LoginShell>
      <form onSubmit={handleSubmit} className="space-y-4">
        {error && <ErrorMessage variant="inline" title="Sign In Failed" message={error} />}

        <div>
          <label
            htmlFor="email"
            className="block text-xs font-bold uppercase tracking-wider text-[var(--color-body)]"
          >
            Email
          </label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            disabled={isSubmitting}
            className="mt-2 w-full rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-canvas)] px-3.5 py-2.5 text-sm text-[var(--color-ink)] focus:border-[var(--color-focus)] focus:bg-white focus:outline-none focus:ring-2 focus:ring-[var(--color-focus)]/20 disabled:opacity-60"
          />
        </div>

        <div>
          <label
            htmlFor="password"
            className="block text-xs font-bold uppercase tracking-wider text-[var(--color-body)]"
          >
            Password
          </label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            disabled={isSubmitting}
            className="mt-2 w-full rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-canvas)] px-3.5 py-2.5 text-sm text-[var(--color-ink)] focus:border-[var(--color-focus)] focus:bg-white focus:outline-none focus:ring-2 focus:ring-[var(--color-focus)]/20 disabled:opacity-60"
          />
        </div>

        <button
          type="submit"
          disabled={isSubmitting}
          className="inline-flex w-full cursor-pointer items-center justify-center gap-2 rounded-[var(--radius-compact)] bg-[var(--color-brass)] px-5 py-2.5 text-sm font-semibold text-white shadow-xs transition-colors hover:bg-[var(--color-brass-hover)] focus-visible:outline-2 focus-visible:outline-[var(--color-focus)] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isSubmitting ? (
            <>
              <LoadingSpinner size="sm" label="Signing in" />
              <span>Signing in...</span>
            </>
          ) : (
            'Sign in'
          )}
        </button>
      </form>
    </LoginShell>
  );
}

function LoginShell({
  children,
  isLoading = false,
}: {
  children?: React.ReactNode;
  isLoading?: boolean;
}) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-[var(--color-canvas)] px-4 py-12">
      <section className="w-full max-w-md rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-6 shadow-sm">
        <span className="text-xs font-bold uppercase tracking-wider text-[var(--color-brass)]">
          Secure Access
        </span>
        <h1 className="font-display mt-1 text-2xl font-bold text-[var(--color-ink)]">
          LegalAI Professional Sign In
        </h1>
        <p className="mt-2 text-sm text-[var(--color-muted)]">
          Use your assigned practitioner or administrator account. Access roles are verified by the
          backend session.
        </p>
        <div className="mt-6">
          {isLoading ? <LoadingSpinner size="lg" label="Preparing sign in" /> : children}
        </div>
      </section>
    </main>
  );
}

function destinationFor(role: UserRole, requestedPath: string | null): string {
  if (requestedPath && isAllowedDestination(role, requestedPath)) {
    return requestedPath;
  }
  return role === 'admin' ? '/admin' : '/professional';
}

function isAllowedDestination(role: UserRole, path: string): boolean {
  if (!path.startsWith('/') || path.startsWith('//') || path.startsWith('/login')) {
    return false;
  }
  if (path.startsWith('/admin')) {
    return role === 'admin';
  }
  if (path.startsWith('/professional')) {
    return role === 'lawyer' || role === 'admin';
  }
  return false;
}
      <LoginForm />
    </AuthProvider>
  );
}
