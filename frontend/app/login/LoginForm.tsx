'use client';

import { useState, type FormEvent } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';

import { ErrorMessage } from '../../components/shared/ErrorMessage';
import { useAuth } from '../../lib/auth/AuthContext';
import type { UserRole } from '../../lib/types/api';

const LOGIN_ERROR_MESSAGE = 'We could not sign you in. Check your details and try again.';

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [hasError, setHasError] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isSubmitting) return;

    setIsSubmitting(true);
    setHasError(false);
    try {
      const user = await login(email.trim(), password);
      if (!user.email_verified) {
        router.replace(`/verify-email?email=${encodeURIComponent(user.email)}`);
        return;
      }
      router.replace(destinationFor(user.role, searchParams.get('next')));
    } catch {
      setHasError(true);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-[var(--color-canvas)] px-4 py-10">
      <div className="w-full max-w-md">
        <p className="text-type-label font-semibold uppercase tracking-wide text-[var(--color-brass-hover)]">
          LegalAI
        </p>
        <h1 className="font-display text-type-heading-xl mt-1 font-semibold text-[var(--color-ink)]">
          Sign in
        </h1>
        <p className="text-type-body-sm mt-2 text-[var(--color-muted)]">
          Continue to your professional or administrative workspace.
        </p>

        <form
          className="mt-6 space-y-5 rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-6 shadow-[var(--shadow-component)]"
          onSubmit={(event) => void submit(event)}
        >
          {hasError ? (
            <ErrorMessage message={LOGIN_ERROR_MESSAGE} title="Sign-in failed" variant="inline" />
          ) : null}

          <div>
            <label
              className="text-type-control font-semibold text-[var(--color-ink)]"
              htmlFor="email"
            >
              Email
            </label>
            <input
              autoComplete="email"
              className="text-type-body mt-2 min-h-11 w-full rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-canvas)] px-3 text-[var(--color-ink)] focus-visible:outline-[0.1875rem] focus-visible:outline-[var(--color-focus)] focus-visible:outline-offset-2"
              id="email"
              onChange={(event) => setEmail(event.target.value)}
              required
              type="email"
              value={email}
            />
          </div>

          <div>
            <label
              className="text-type-control font-semibold text-[var(--color-ink)]"
              htmlFor="password"
            >
              Password
            </label>
            <input
              autoComplete="current-password"
              className="text-type-body mt-2 min-h-11 w-full rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-canvas)] px-3 text-[var(--color-ink)] focus-visible:outline-[0.1875rem] focus-visible:outline-[var(--color-focus)] focus-visible:outline-offset-2"
              id="password"
              onChange={(event) => setPassword(event.target.value)}
              required
              type="password"
              value={password}
            />
          </div>

          <button
            className="text-type-control min-h-11 w-full rounded-[var(--radius-compact)] bg-[var(--color-brass)] px-4 font-semibold text-[var(--color-inverse)] hover:bg-[var(--color-brass-hover)] focus-visible:outline-[0.1875rem] focus-visible:outline-[var(--color-focus)] focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={isSubmitting}
            type="submit"
          >
            {isSubmitting ? 'Signing in…' : 'Sign in'}
          </button>
          <p className="text-type-body-sm text-center text-[var(--color-muted)]">
            Don&apos;t have an account?{' '}
            <Link
              className="font-semibold text-[var(--color-brass-hover)] underline-offset-4 hover:underline"
              href="/register"
            >
              Register
            </Link>
          </p>
          <Link
            className="text-type-control flex min-h-11 items-center justify-center rounded-[var(--radius-compact)] border border-[var(--color-border)] font-semibold text-[var(--color-ink)] hover:bg-[var(--color-surface-subtle)]"
            href="/public"
          >
            Continue as guest
          </Link>
        </form>
      </div>
    </main>
  );
}

function destinationFor(role: UserRole, requestedPath: string | null): string {
  if (requestedPath && isAllowedDestination(role, requestedPath)) {
    return requestedPath;
  }
  if (role === 'admin') return '/admin';
  if (role === 'lawyer') return '/professional';
  return '/lawyer/apply';
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
  if (path.startsWith('/lawyer/apply')) {
    return true;
  }
  return false;
}
