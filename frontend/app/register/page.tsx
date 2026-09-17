'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState, type FormEvent } from 'react';

import { ErrorMessage } from '../../components/shared/ErrorMessage';
import { authApi } from '../../lib/api';

export default function RegisterPage() {
  const router = useRouter();
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [applyAsLawyer, setApplyAsLawyer] = useState(false);
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isSubmitting) return;
    if (password !== confirmPassword) {
      setError('Passwords must match.');
      return;
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }
    setIsSubmitting(true);
    setError('');
    try {
      const response = await authApi.register(fullName.trim(), email.trim(), password);
      const params = new URLSearchParams({ email: response.user.email });
      if (applyAsLawyer) {
        params.set('next', '/lawyer/apply');
      }
      router.replace(`/verify-email?${params.toString()}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Registration failed.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-[var(--color-canvas)] px-4 py-10">
      <div className="w-full max-w-lg">
        <p className="text-type-label font-semibold uppercase tracking-wide text-[var(--color-brass-hover)]">
          LegalAI
        </p>
        <h1 className="font-display text-type-heading-xl mt-1 font-semibold text-[var(--color-ink)]">
          Create account
        </h1>
        <p className="text-type-body-sm mt-2 text-[var(--color-muted)]">
          Register as a public user. Lawyer access is granted only after admin verification.
        </p>

        <form
          className="mt-6 space-y-5 rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-6 shadow-[var(--shadow-component)]"
          onSubmit={(event) => void submit(event)}
        >
          {error ? (
            <ErrorMessage message={error} title="Registration failed" variant="inline" />
          ) : null}

          <Field label="Full name" name="full-name" value={fullName} onChange={setFullName} />
          <Field label="Email" name="email" type="email" value={email} onChange={setEmail} />
          <Field
            label="Password"
            name="password"
            type="password"
            value={password}
            onChange={setPassword}
          />
          <Field
            label="Confirm password"
            name="confirm-password"
            type="password"
            value={confirmPassword}
            onChange={setConfirmPassword}
          />

          <label className="flex items-start gap-3 text-type-body-sm text-[var(--color-body)]">
            <input
              checked={applyAsLawyer}
              className="mt-1"
              onChange={(event) => setApplyAsLawyer(event.target.checked)}
              type="checkbox"
            />
            <span>After creating my public account, take me to lawyer verification.</span>
          </label>

          <button
            className="text-type-control min-h-11 w-full rounded-[var(--radius-compact)] bg-[var(--color-brass)] px-4 font-semibold text-[var(--color-inverse)] hover:bg-[var(--color-brass-hover)] disabled:cursor-not-allowed disabled:opacity-60"
            disabled={isSubmitting}
            type="submit"
          >
            {isSubmitting ? 'Creating account…' : 'Create public account'}
          </button>

          <p className="text-type-body-sm text-center text-[var(--color-muted)]">
            Already registered?{' '}
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

function Field({
  label,
  name,
  value,
  onChange,
  type = 'text',
}: {
  label: string;
  name: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
}) {
  return (
    <div>
      <label className="text-type-control font-semibold text-[var(--color-ink)]" htmlFor={name}>
        {label}
      </label>
      <input
        className="text-type-body mt-2 min-h-11 w-full rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-canvas)] px-3 text-[var(--color-ink)] focus-visible:outline-[0.1875rem] focus-visible:outline-[var(--color-focus)] focus-visible:outline-offset-2"
        id={name}
        onChange={(event) => onChange(event.target.value)}
        required
        type={type}
        value={value}
      />
    </div>
  );
}
