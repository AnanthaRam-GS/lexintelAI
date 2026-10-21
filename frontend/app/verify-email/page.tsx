'use client';

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useEffect, useState, type FormEvent } from 'react';

import { ErrorMessage } from '../../components/shared/ErrorMessage';
import { authApi } from '../../lib/api';

const RESEND_SECONDS = 60;

export default function VerifyEmailPage() {
  // useSearchParams() needs a Suspense boundary for the page to prerender in `next build`.
  return (
    <Suspense>
      <VerifyEmailForm />
    </Suspense>
  );
}

function VerifyEmailForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const email = searchParams.get('email') ?? '';
  const next = searchParams.get('next') ?? '/login';
  const [otp, setOtp] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [cooldown, setCooldown] = useState(0);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setTimeout(() => setCooldown((value) => Math.max(0, value - 1)), 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!/^\d{6}$/.test(otp)) {
      setError('Enter the 6-digit verification code.');
      return;
    }
    setIsSubmitting(true);
    setError('');
    try {
      await authApi.verifyEmail(email, otp);
      setMessage('Email verified.');
      router.replace(next === '/lawyer/apply' ? '/lawyer/apply' : '/login');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Verification failed.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const resend = async () => {
    if (cooldown > 0) return;
    setError('');
    setMessage('');
    try {
      const response = await authApi.resendVerification(email);
      // The same message for every email address, so it never reveals whether an account exists.
      setMessage(response.message);
      setCooldown(RESEND_SECONDS);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not resend the code.');
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-[var(--color-canvas)] px-4 py-10">
      <div className="w-full max-w-md">
        <p className="text-type-label font-semibold uppercase tracking-wide text-[var(--color-brass-hover)]">
          LegalAI
        </p>
        <h1 className="font-display text-type-heading-xl mt-1 font-semibold text-[var(--color-ink)]">
          Verify email
        </h1>
        <p className="text-type-body-sm mt-2 text-[var(--color-muted)]">
          Enter the 6-digit code sent to {email || 'your email'}. Codes expire after 10 minutes.
        </p>
        <p className="text-type-body-sm mt-2 text-[var(--color-muted)]">
          Already have an account with this email? We have emailed you instead of sending a code.{' '}
          <Link className="font-semibold text-[var(--color-ink)] underline" href="/login">
            Sign in
          </Link>
          .
        </p>

        <form
          className="mt-6 space-y-5 rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-6 shadow-[var(--shadow-component)]"
          onSubmit={(event) => void submit(event)}
        >
          {error ? (
            <ErrorMessage message={error} title="Verification failed" variant="inline" />
          ) : null}
          {message ? (
            <p className="rounded-[var(--radius-compact)] border border-[var(--color-success)] p-3 text-type-body-sm text-[var(--color-success)]">
              {message}
            </p>
          ) : null}
          <div>
            <label
              className="text-type-control font-semibold text-[var(--color-ink)]"
              htmlFor="otp"
            >
              Verification code
            </label>
            <input
              autoComplete="one-time-code"
              className="text-type-body mt-2 min-h-11 w-full rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-canvas)] px-3 text-center tracking-[0.4em] text-[var(--color-ink)]"
              id="otp"
              inputMode="numeric"
              maxLength={6}
              onChange={(event) => setOtp(event.target.value.replace(/\D/g, '').slice(0, 6))}
              pattern="\d{6}"
              required
              value={otp}
            />
          </div>
          <button
            className="text-type-control min-h-11 w-full rounded-[var(--radius-compact)] bg-[var(--color-brass)] px-4 font-semibold text-[var(--color-inverse)] disabled:opacity-60"
            disabled={isSubmitting || !email}
            type="submit"
          >
            {isSubmitting ? 'Verifying…' : 'Verify email'}
          </button>
          <button
            className="text-type-control min-h-11 w-full rounded-[var(--radius-compact)] border border-[var(--color-border)] font-semibold text-[var(--color-ink)] disabled:opacity-60"
            disabled={!email || cooldown > 0}
            onClick={() => void resend()}
            type="button"
          >
            {cooldown > 0 ? `Resend in ${cooldown}s` : 'Resend code'}
          </button>
          <p className="text-type-body-sm text-center text-[var(--color-muted)]">
            Already verified?{' '}
            <Link
              className="font-semibold text-[var(--color-brass-hover)] underline-offset-4 hover:underline"
              href="/login"
            >
              Sign in
            </Link>
          </p>
        </form>
      </div>
    </main>
  );
}
