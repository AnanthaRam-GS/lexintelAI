'use client';

import { useEffect, useState } from 'react';

import { ErrorMessage } from '../../../components/shared/ErrorMessage';
import { LoadingSpinner } from '../../../components/shared/LoadingSpinner';
import { adminLawyerVerificationApi } from '../../../lib/api';
import type { AdminLawyerApplication } from '../../../lib/types/api';

export default function AdminLawyerVerificationPage() {
  const [applications, setApplications] = useState<AdminLawyerApplication[]>([]);
  const [selected, setSelected] = useState<AdminLawyerApplication | null>(null);
  const [reason, setReason] = useState('');
  const [pending, setPending] = useState(true);
  const [error, setError] = useState('');

  const load = async () => {
    try {
      const data = await adminLawyerVerificationApi.list();
      setApplications(data.applications);
      setSelected(data.applications[0] ?? null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load applications.');
    } finally {
      setPending(false);
    }
  };

  useEffect(() => {
    queueMicrotask(() => void load());
  }, []);

  const review = async (action: 'approve' | 'reject' | 'resubmission') => {
    if (!selected) return;
    setError('');
    try {
      const updated =
        action === 'approve'
          ? await adminLawyerVerificationApi.approve(selected.id)
          : action === 'reject'
            ? await adminLawyerVerificationApi.reject(selected.id, reason)
            : await adminLawyerVerificationApi.requestResubmission(selected.id, reason);
      setSelected(updated);
      setApplications((rows) => rows.map((row) => (row.id === updated.id ? updated : row)));
      setReason('');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Review action failed.');
    }
  };

  if (pending) {
    return <LoadingSpinner label="Loading lawyer verification queue" />;
  }

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      <div className="border-b border-[var(--color-border)] pb-6">
        <p className="text-type-label font-semibold uppercase tracking-wide text-[var(--color-brass-hover)]">
          Admin Review
        </p>
        <h1 className="font-display text-2xl font-bold text-[var(--color-ink)]">
          Lawyer verification queue
        </h1>
      </div>
      {error ? (
        <div className="mt-5">
          <ErrorMessage title="Review error" message={error} variant="inline" />
        </div>
      ) : null}
      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(22rem,0.8fr)]">
        <section className="overflow-hidden rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)]">
          <table className="w-full text-left text-sm">
            <thead className="bg-[var(--color-canvas)] text-[var(--color-muted)]">
              <tr>
                <th className="px-4 py-3">Applicant</th>
                <th className="px-4 py-3">Enrollment</th>
                <th className="px-4 py-3">Status</th>
              </tr>
            </thead>
            <tbody>
              {applications.map((application) => (
                <tr
                  className="cursor-pointer border-t border-[var(--color-border)] hover:bg-[var(--color-canvas)]"
                  key={application.id}
                  onClick={() => setSelected(application)}
                >
                  <td className="px-4 py-3">
                    <p className="font-semibold text-[var(--color-ink)]">
                      {application.applicant_name ?? 'Unnamed applicant'}
                    </p>
                    <p className="text-[var(--color-muted)]">{application.applicant_email}</p>
                  </td>
                  <td className="px-4 py-3">{application.enrollment_number}</td>
                  <td className="px-4 py-3">{application.status}</td>
                </tr>
              ))}
              {applications.length === 0 ? (
                <tr>
                  <td className="px-4 py-6 text-[var(--color-muted)]" colSpan={3}>
                    No lawyer verification applications are waiting.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </section>
        <aside className="rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
          {selected ? (
            <div className="space-y-4">
              <div>
                <p className="text-type-label font-semibold uppercase text-[var(--color-brass-hover)]">
                  {selected.status}
                </p>
                <h2 className="font-display text-xl font-semibold text-[var(--color-ink)]">
                  {selected.applicant_name ?? selected.applicant_email}
                </h2>
                <p className="text-type-body-sm text-[var(--color-muted)]">
                  {selected.applicant_email}
                </p>
              </div>
              <dl className="grid gap-3 text-sm">
                <Row label="Bar Council" value={selected.bar_council} />
                <Row
                  label="Enrollment"
                  value={`${selected.enrollment_number} (${selected.enrollment_year})`}
                />
                <Row label="Jurisdiction" value={selected.jurisdiction} />
                <Row label="Organization" value={selected.organization ?? 'Not provided'} />
                <Row
                  label="Proof"
                  value={`${selected.proof_file_name} (${selected.proof_content_type})`}
                />
              </dl>
              <textarea
                className="text-type-body min-h-24 w-full rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-canvas)] p-3"
                onChange={(event) => setReason(event.target.value)}
                placeholder="Review reason for rejection or resubmission"
                value={reason}
              />
              <div className="flex flex-wrap gap-3">
                <button
                  className="rounded-[var(--radius-compact)] bg-[var(--color-success)] px-4 py-2 font-semibold text-white"
                  onClick={() => void review('approve')}
                  type="button"
                >
                  Approve
                </button>
                <button
                  className="rounded-[var(--radius-compact)] bg-[var(--color-error)] px-4 py-2 font-semibold text-white"
                  onClick={() => void review('reject')}
                  type="button"
                >
                  Reject
                </button>
                <button
                  className="rounded-[var(--radius-compact)] border border-[var(--color-border)] px-4 py-2 font-semibold text-[var(--color-ink)]"
                  onClick={() => void review('resubmission')}
                  type="button"
                >
                  Request resubmission
                </button>
              </div>
            </div>
          ) : (
            <p className="text-[var(--color-muted)]">Select an application to review.</p>
          )}
        </aside>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="font-semibold text-[var(--color-ink)]">{label}</dt>
      <dd className="text-[var(--color-muted)]">{value}</dd>
    </div>
  );
}
