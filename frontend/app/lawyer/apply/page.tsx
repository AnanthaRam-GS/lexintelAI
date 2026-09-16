'use client';

import Link from 'next/link';
import { useEffect, useState, type FormEvent } from 'react';

import { AuthProvider, useAuth } from '../../../lib/auth/AuthContext';
import { lawyerApplicationApi } from '../../../lib/api';
import type { LawyerApplication } from '../../../lib/types/api';
import { ErrorMessage } from '../../../components/shared/ErrorMessage';
import { LoadingSpinner } from '../../../components/shared/LoadingSpinner';

export default function LawyerApplyPage() {
  return (
    <AuthProvider>
      <LawyerApplyContent />
    </AuthProvider>
  );
}

function LawyerApplyContent() {
  const { user, isLoading, refreshSession } = useAuth();
  const [application, setApplication] = useState<LawyerApplication | null>(null);
  const [pending, setPending] = useState(true);
  const [error, setError] = useState('');
  const [form, setForm] = useState({
    barCouncil: '',
    enrollmentNumber: '',
    enrollmentYear: String(new Date().getFullYear()),
    jurisdiction: '',
    organization: '',
  });
  const [proof, setProof] = useState<File | null>(null);

  useEffect(() => {
    if (isLoading) return;
    if (!user) {
      queueMicrotask(() => setPending(false));
      return;
    }
    void lawyerApplicationApi
      .getMine()
      .then((data) => setApplication(data.application))
      .catch(() => setApplication(null))
      .finally(() => setPending(false));
  }, [isLoading, user]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!proof) {
      setError('Upload proof of enrollment.');
      return;
    }
    setError('');
    setPending(true);
    try {
      const result = await lawyerApplicationApi.submit({
        ...form,
        enrollmentYear: Number(form.enrollmentYear),
        proof,
      });
      setApplication(result);
      await refreshSession();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Application submission failed.');
    } finally {
      setPending(false);
    }
  };

  if (isLoading || pending) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[var(--color-canvas)]">
        <LoadingSpinner label="Checking verification status" />
      </main>
    );
  }

  if (!user) {
    return (
      <main className="min-h-screen bg-[var(--color-canvas)] px-4 py-10">
        <Panel title="Sign in required">
          <p className="text-type-body text-[var(--color-body)]">
            Create or sign in to a public account before applying for lawyer verification.
          </p>
          <Link
            className="mt-5 inline-flex rounded-[var(--radius-compact)] bg-[var(--color-brass)] px-4 py-3 font-semibold text-[var(--color-inverse)]"
            href="/login?next=%2Flawyer%2Fapply"
          >
            Sign in
          </Link>
        </Panel>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-[var(--color-canvas)] px-4 py-10">
      <Panel title="Lawyer verification">
        <p className="text-type-body-sm text-[var(--color-muted)]">
          Current account: {user.email}. Email verification is required before submission.
        </p>
        {!user.email_verified ? (
          <ErrorMessage
            message="Verify your email before applying. Local development may expose a test token only when explicitly enabled."
            title="Email verification required"
            variant="inline"
          />
        ) : null}
        {application ? <StatusBlock application={application} /> : null}
        {!application ||
        application.status === 'REJECTED' ||
        application.status === 'RESUBMISSION_REQUIRED' ? (
          <form className="mt-6 grid gap-4" onSubmit={(event) => void submit(event)}>
            {error ? (
              <ErrorMessage message={error} title="Application failed" variant="inline" />
            ) : null}
            <Input
              label="Bar Council"
              value={form.barCouncil}
              onChange={(barCouncil) => setForm({ ...form, barCouncil })}
            />
            <Input
              label="Enrollment number"
              value={form.enrollmentNumber}
              onChange={(enrollmentNumber) => setForm({ ...form, enrollmentNumber })}
            />
            <Input
              label="Enrollment year"
              type="number"
              value={form.enrollmentYear}
              onChange={(enrollmentYear) => setForm({ ...form, enrollmentYear })}
            />
            <Input
              label="State / jurisdiction"
              value={form.jurisdiction}
              onChange={(jurisdiction) => setForm({ ...form, jurisdiction })}
            />
            <Input
              label="Organization (optional)"
              required={false}
              value={form.organization}
              onChange={(organization) => setForm({ ...form, organization })}
            />
            <div>
              <label
                className="text-type-control font-semibold text-[var(--color-ink)]"
                htmlFor="proof"
              >
                Proof document
              </label>
              <input
                accept="application/pdf,image/png,image/jpeg"
                className="text-type-body mt-2 w-full rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-canvas)] p-3"
                id="proof"
                onChange={(event) => setProof(event.target.files?.[0] ?? null)}
                required
                type="file"
              />
            </div>
            <button
              className="text-type-control min-h-11 rounded-[var(--radius-compact)] bg-[var(--color-brass)] px-4 font-semibold text-[var(--color-inverse)] disabled:opacity-60"
              disabled={!user.email_verified}
              type="submit"
            >
              Submit verification application
            </button>
          </form>
        ) : null}
      </Panel>
    </main>
  );
}

function StatusBlock({ application }: { application: LawyerApplication }) {
  return (
    <div className="mt-5 rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-canvas)] p-4">
      <p className="text-type-label font-semibold uppercase text-[var(--color-brass-hover)]">
        {application.status}
      </p>
      <p className="text-type-body mt-2 text-[var(--color-body)]">
        Enrollment {application.enrollment_number} submitted to {application.bar_council}.
      </p>
      {application.review_note ? (
        <p className="text-type-body-sm mt-2 text-[var(--color-muted)]">
          {application.review_note}
        </p>
      ) : null}
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mx-auto max-w-2xl rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-6 shadow-[var(--shadow-component)]">
      <p className="text-type-label font-semibold uppercase tracking-wide text-[var(--color-brass-hover)]">
        LegalAI
      </p>
      <h1 className="font-display text-type-heading-xl mt-1 font-semibold text-[var(--color-ink)]">
        {title}
      </h1>
      <div className="mt-5 space-y-4">{children}</div>
    </section>
  );
}

function Input({
  label,
  value,
  onChange,
  type = 'text',
  required = true,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  required?: boolean;
}) {
  const id = label.toLowerCase().replaceAll(' ', '-');
  return (
    <div>
      <label className="text-type-control font-semibold text-[var(--color-ink)]" htmlFor={id}>
        {label}
      </label>
      <input
        className="text-type-body mt-2 min-h-11 w-full rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-canvas)] px-3 text-[var(--color-ink)]"
        id={id}
        onChange={(event) => onChange(event.target.value)}
        required={required}
        type={type}
        value={value}
      />
    </div>
  );
}
