'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { ErrorMessage } from '../../../components/shared/ErrorMessage';
import { IngestionProgress, type IngestionJob } from '../../../components/shared/IngestionProgress';
import { UploadDropzone } from '../../../components/shared/UploadDropzone';
import {
  cancelIngestionJobMock,
  MAX_ACTIVE_INGESTION_JOBS,
  pollIngestionStatusMock,
  progressForStage,
  readPersistedIngestionJobs,
  submitIngestionMock,
  writePersistedIngestionJobs,
  type DocumentType,
  type PersistedIngestionJob,
} from '../../../lib/mocks/adminIngestion';
import {
  canSubmitBatch,
  isTerminal,
  markJobFailedSafely,
  reconcileDrafts,
  replaceJobById,
  type IngestionDraft,
} from './ingestion-model';
import {
  classifyRequestFailure,
  errorCopy,
  toAdminFileFailure,
  type AdminFileFailure,
  type AdminRequestFailure,
} from '../../public/error-copy';

const ADMIN_JOB_TIMEOUT_MS = 15_000;
const ADMIN_SUBMIT_TIMEOUT_MS = 10_000;

class AdminSubmitTimeoutError extends Error {}
class AdminJobTimeoutError extends Error {}

// TODO(contract): confirm doc_type values with Ananthu/Roshinee before treating
// judgment | statute | other as the live documents-table contract.
const documentTypeOptions: ReadonlyArray<{ value: DocumentType; label: string }> = [
  { value: 'judgment', label: 'Judgment' },
  { value: 'statute', label: 'Statute' },
  { value: 'other', label: 'Other' },
];

const createDraftId = () => crypto.randomUUID();

function persistActiveJob(job: IngestionJob) {
  const record: PersistedIngestionJob = {
    id: job.id,
    filename: job.filename,
    stage: job.stage,
  };
  const current = readPersistedIngestionJobs();
  const index = current.findIndex(({ id }) => id === job.id);
  writePersistedIngestionJobs(
    index === -1
      ? [record, ...current]
      : current.map((item) => (item.id === job.id ? record : item)),
  );
}

function removePersistedJob(jobId: string) {
  writePersistedIngestionJobs(readPersistedIngestionJobs().filter(({ id }) => id !== jobId));
}

export function IngestionWorkspace() {
  const [drafts, setDrafts] = useState<IngestionDraft[]>([]);
  const [isConfirmed, setIsConfirmed] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitFailure, setSubmitFailure] = useState<AdminRequestFailure | null>(null);
  const [jobs, setJobs] = useState<IngestionJob[]>([]);
  const [fileFailures, setFileFailures] = useState<Record<string, AdminFileFailure>>({});
  const [pollingFailures, setPollingFailures] = useState<Record<string, AdminRequestFailure>>({});
  const [uploadKey, setUploadKey] = useState(0);
  const timersRef = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const deadlineTimersRef = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const lastProgressRef = useRef(new Map<string, number>());
  const pollingRef = useRef(new Map<string, symbol>());
  const pollControllersRef = useRef(new Map<string, AbortController>());
  const submitControllerRef = useRef<AbortController | null>(null);
  const aliveRef = useRef(true);
  const incompleteNames = drafts
    .filter((draft) => draft.documentType === '')
    .map((draft) => draft.file.name);
  const activeJobCount = jobs.filter((job) => !isTerminal(job.stage)).length;
  const remainingJobSlots = Math.max(0, MAX_ACTIVE_INGESTION_JOBS - activeJobCount);
  const excessFileCount = Math.max(0, drafts.length - remainingJobSlots);
  const exceedsActiveJobCapacity = excessFileCount > 0;
  const canSubmit = canSubmitBatch(drafts, isConfirmed, isSubmitting) && !exceedsActiveJobCapacity;
  const orderedJobs = jobs;
  const activePollingFailure = Object.values(pollingFailures).includes('network')
    ? 'network'
    : Object.keys(pollingFailures).length > 0
      ? 'service'
      : null;
  const failureContentByJobId = Object.fromEntries(
    Object.entries(fileFailures).map(([jobId, reason]) => [jobId, errorCopy.admin.file[reason]]),
  );

  const stopPolling = useCallback((jobId: string) => {
    const timer = timersRef.current.get(jobId);
    if (timer) clearTimeout(timer);
    const deadlineTimer = deadlineTimersRef.current.get(jobId);
    if (deadlineTimer) clearTimeout(deadlineTimer);
    pollControllersRef.current.get(jobId)?.abort();
    timersRef.current.delete(jobId);
    deadlineTimersRef.current.delete(jobId);
    lastProgressRef.current.delete(jobId);
    pollControllersRef.current.delete(jobId);
    pollingRef.current.delete(jobId);
  }, []);

  const startPolling = useCallback(
    (jobId: string) => {
      if (pollingRef.current.has(jobId)) return;
      const generation = Symbol(jobId);
      pollingRef.current.set(jobId, generation);

      const isCurrentPoll = () => aliveRef.current && pollingRef.current.get(jobId) === generation;

      const handleInactivityDeadline = () => {
        if (!isCurrentPoll()) return;
        pollingRef.current.delete(jobId);
        pollControllersRef.current.get(jobId)?.abort(new AdminJobTimeoutError());

        void cancelIngestionJobMock(jobId)
          .then(() => {
            removePersistedJob(jobId);
            if (!aliveRef.current) return;
            setJobs((current) => markJobFailedSafely(current, jobId));
            setFileFailures((current) => ({ ...current, [jobId]: 'timeout' }));
            setPollingFailures((current) => {
              const next = { ...current };
              delete next[jobId];
              return next;
            });
          })
          .catch((caught) => {
            if (!aliveRef.current) return;
            setPollingFailures((current) => ({
              ...current,
              [jobId]: classifyRequestFailure(caught),
            }));
          })
          .finally(() => stopPolling(jobId));
      };

      const resetInactivityDeadline = () => {
        const currentDeadline = deadlineTimersRef.current.get(jobId);
        if (currentDeadline) clearTimeout(currentDeadline);
        deadlineTimersRef.current.set(
          jobId,
          setTimeout(handleInactivityDeadline, ADMIN_JOB_TIMEOUT_MS),
        );
      };

      resetInactivityDeadline();

      const poll = async (): Promise<void> => {
        if (!isCurrentPoll()) return;
        const pollController = new AbortController();
        pollControllersRef.current.set(jobId, pollController);
        try {
          const live = await pollIngestionStatusMock(jobId, { signal: pollController.signal });
          if (!isCurrentPoll()) return;
          const previousProgress = lastProgressRef.current.get(jobId) ?? 0;
          const madeProgress = live.progress > previousProgress;
          lastProgressRef.current.set(jobId, Math.max(previousProgress, live.progress));
          const safeLive = { ...live, error: undefined };
          setJobs((current) => replaceJobById(current, safeLive));
          setPollingFailures((current) => {
            if (!(jobId in current)) return current;
            const next = { ...current };
            delete next[jobId];
            return next;
          });
          if (live.stage === 'FAILED') {
            setFileFailures((current) => ({
              ...current,
              [jobId]: toAdminFileFailure(live.error),
            }));
          }
          if (isTerminal(live.stage)) {
            removePersistedJob(jobId);
            stopPolling(jobId);
            return;
          }
          persistActiveJob(live);
          if (madeProgress) resetInactivityDeadline();
        } catch (caught) {
          if (!isCurrentPoll()) return;
          setPollingFailures((current) => ({
            ...current,
            [jobId]: classifyRequestFailure(caught),
          }));
        } finally {
          if (pollControllersRef.current.get(jobId) === pollController) {
            pollControllersRef.current.delete(jobId);
          }
        }

        const timer = setTimeout(() => void poll(), 2_500);
        timersRef.current.set(jobId, timer);
      };

      void poll();
    },
    [stopPolling],
  );

  useEffect(() => {
    const timers = timersRef.current;
    const deadlineTimers = deadlineTimersRef.current;
    const lastProgress = lastProgressRef.current;
    const polling = pollingRef.current;
    const pollControllers = pollControllersRef.current;
    aliveRef.current = true;
    const restored = readPersistedIngestionJobs().map((record): IngestionJob => ({
      ...record,
      progress: progressForStage(record.stage),
    }));
    // Rehydration is an intentional client-only external-store synchronization.
    setJobs(restored);
    restored.forEach((job) => lastProgress.set(job.id, job.progress));
    restored.filter((job) => !isTerminal(job.stage)).forEach(({ id }) => startPolling(id));

    return () => {
      aliveRef.current = false;
      submitControllerRef.current?.abort();
      submitControllerRef.current = null;
      pollControllers.forEach((controller) => controller.abort());
      timers.forEach(clearTimeout);
      deadlineTimers.forEach(clearTimeout);
      timers.clear();
      deadlineTimers.clear();
      lastProgress.clear();
      pollControllers.clear();
      polling.clear();
    };
  }, [startPolling]);

  const handleFilesSelected = (files: File[]) => {
    const addsOrReplacesAFile = files.some((file) => !drafts.some((draft) => draft.file === file));

    if (addsOrReplacesAFile) {
      setIsConfirmed(false);
    }

    setDrafts((previous) => reconcileDrafts(previous, files, createDraftId));
  };

  const updateDraft = (
    id: string,
    updates: Partial<Pick<IngestionDraft, 'documentType' | 'note'>>,
  ) => {
    setDrafts((previous) =>
      previous.map((draft) => (draft.id === id ? { ...draft, ...updates } : draft)),
    );
  };

  const submitBatch = async () => {
    if (!canSubmitBatch(drafts, isConfirmed, isSubmitting) || exceedsActiveJobCapacity) return;
    setIsSubmitting(true);
    setSubmitFailure(null);

    let timeout: ReturnType<typeof setTimeout> | undefined;
    const submitController = new AbortController();
    submitControllerRef.current = submitController;

    try {
      const files = drafts.map(({ file }) => file);
      const metadata = drafts.map(({ documentType, note }) => ({
        documentType: documentType as DocumentType,
        note: note.trim() || undefined,
      }));
      const { jobIds } = await Promise.race([
        submitIngestionMock(files, metadata, { signal: submitController.signal }),
        new Promise<never>((_, reject) => {
          timeout = setTimeout(() => {
            const timeoutError = new AdminSubmitTimeoutError();
            submitController.abort(timeoutError);
            reject(timeoutError);
          }, ADMIN_SUBMIT_TIMEOUT_MS);
        }),
      ]);
      const existingJobIds = new Set(jobs.map(({ id }) => id));
      const uniqueResponseIds = new Set(jobIds);
      if (
        jobIds.length !== drafts.length ||
        uniqueResponseIds.size !== jobIds.length ||
        jobIds.some((id) => id.trim().length === 0 || existingJobIds.has(id))
      ) {
        throw new Error('Unexpected ingestion response');
      }

      const queued = jobIds.map((id, index): IngestionJob => ({
        id,
        filename: drafts[index].file.name,
        stage: 'QUEUED',
        progress: progressForStage('QUEUED'),
      }));
      setJobs((current) => [...[...queued].reverse(), ...current]);
      queued.forEach(persistActiveJob);
      queued.forEach((job) => lastProgressRef.current.set(job.id, job.progress));
      setDrafts([]);
      setIsConfirmed(false);
      setUploadKey((current) => current + 1);
      queued.forEach(({ id }) => startPolling(id));
    } catch (caught) {
      if (aliveRef.current) {
        const timedOut =
          caught instanceof AdminSubmitTimeoutError ||
          submitController.signal.reason instanceof AdminSubmitTimeoutError;
        setSubmitFailure(timedOut ? 'timeout' : classifyRequestFailure(caught));
      }
    } finally {
      if (timeout) clearTimeout(timeout);
      if (submitControllerRef.current === submitController) {
        submitControllerRef.current = null;
      }
      if (aliveRef.current) setIsSubmitting(false);
    }
  };

  return (
    <main className="min-h-screen bg-[var(--color-canvas)] px-4 py-8 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-6xl">
        <header className="border-b border-[var(--color-border)] pb-6">
          <p className="text-type-label font-semibold uppercase tracking-wide text-[var(--color-brass-hover)]">
            Admin
          </p>
          <h1 className="font-display text-type-heading-xl mt-1 font-semibold tracking-tight text-[var(--color-ink)] sm:text-type-heading-2xl">
            Permanent corpus ingestion
          </h1>
          <p className="text-type-body mt-3 max-w-2xl text-[var(--color-body)]">
            Add reviewed PDF documents to the shared LegalAI corpus. This action permanently updates
            the corpus for all users.
          </p>
        </header>

        <div className="mt-6 grid items-start gap-8 lg:grid-cols-[minmax(0,3fr)_minmax(20rem,2fr)]">
          <section aria-labelledby="batch-heading" className="min-w-0 space-y-6">
            <div>
              <p className="text-type-label font-semibold uppercase tracking-wide text-[var(--color-brass-hover)]">
                Prepare batch
              </p>
              <h2
                className="font-display text-type-heading-lg mt-1 font-semibold text-[var(--color-ink)]"
                id="batch-heading"
              >
                Select documents and metadata
              </h2>
            </div>

            <UploadDropzone
              accept="application/pdf"
              disabled={isSubmitting}
              key={uploadKey}
              multiple
              onFilesSelected={handleFilesSelected}
            />

            {drafts.length > 0 ? (
              <section aria-label="Document metadata" className="min-w-0 space-y-3">
                {drafts.map((draft) => {
                  const typeId = `document-type-${draft.id}`;
                  const noteId = `document-note-${draft.id}`;
                  const errorId = `document-type-error-${draft.id}`;
                  const isIncomplete = draft.documentType === '';

                  return (
                    <article
                      className="min-w-0 rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-4 shadow-[var(--shadow-component)] sm:p-5"
                      key={draft.id}
                    >
                      <h3
                        className="text-type-body truncate font-semibold text-[var(--color-ink)]"
                        title={draft.file.name}
                      >
                        {draft.file.name}
                      </h3>
                      <div className="mt-4 grid gap-4 sm:grid-cols-2">
                        <div className="min-w-0">
                          <label
                            className="text-type-label break-all font-semibold text-[var(--color-body)]"
                            htmlFor={typeId}
                          >
                            Document type for {draft.file.name}
                          </label>
                          <select
                            aria-describedby={isIncomplete ? errorId : undefined}
                            className="text-type-control mt-2 min-h-11 w-full rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-[var(--color-ink)] focus-visible:outline-[0.1875rem] focus-visible:outline-[var(--color-focus)] focus-visible:outline-offset-[0.1875rem]"
                            id={typeId}
                            disabled={isSubmitting}
                            onChange={(event) =>
                              updateDraft(draft.id, {
                                documentType: event.target.value as DocumentType | '',
                              })
                            }
                            required
                            value={draft.documentType}
                          >
                            <option value="">Select document type</option>
                            {documentTypeOptions.map((option) => (
                              <option key={option.value} value={option.value}>
                                {option.label}
                              </option>
                            ))}
                          </select>
                          {isIncomplete ? (
                            <p
                              className="text-type-body-sm mt-2 break-all text-[var(--color-error-foreground)]"
                              id={errorId}
                            >
                              Choose a document type for {draft.file.name}.
                            </p>
                          ) : null}
                        </div>
                        <div className="min-w-0">
                          <label
                            className="text-type-label break-all font-semibold text-[var(--color-body)]"
                            htmlFor={noteId}
                          >
                            Note for {draft.file.name}
                          </label>
                          <textarea
                            className="text-type-control mt-2 min-h-24 w-full rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-[var(--color-ink)] focus-visible:outline-[0.1875rem] focus-visible:outline-[var(--color-focus)] focus-visible:outline-offset-[0.1875rem]"
                            id={noteId}
                            disabled={isSubmitting}
                            onChange={(event) =>
                              updateDraft(draft.id, { note: event.target.value })
                            }
                            value={draft.note}
                          />
                        </div>
                      </div>
                    </article>
                  );
                })}
              </section>
            ) : null}

            {incompleteNames.length > 0 ? (
              <p
                className="text-type-body-sm break-all text-[var(--color-error-foreground)]"
                role="alert"
              >
                Complete document types for: {incompleteNames.join(', ')}
              </p>
            ) : null}

            {exceedsActiveJobCapacity ? (
              <p className="text-type-body-sm text-[var(--color-error-foreground)]" role="alert">
                This batch exceeds the active ingestion capacity. Remove {excessFileCount}{' '}
                {excessFileCount === 1 ? 'file' : 'files'}; {remainingJobSlots}{' '}
                {remainingJobSlots === 1 ? 'job slot remains' : 'job slots remain'}.
              </p>
            ) : null}

            {submitFailure ? (
              <ErrorMessage
                message={errorCopy.admin.submit[submitFailure].message}
                title={errorCopy.admin.submit[submitFailure].title}
                variant="banner"
              />
            ) : null}

            <section
              aria-labelledby="confirmation-heading"
              className="rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4 sm:p-5"
            >
              <h2
                className="font-display text-type-heading-sm font-semibold text-[var(--color-ink)]"
                id="confirmation-heading"
              >
                Confirm permanent update
              </h2>
              <p className="text-type-body mt-2 text-[var(--color-body)]">
                {drafts.length} {drafts.length === 1 ? 'file' : 'files'} will be permanently added
                to the shared corpus.
              </p>
              <label className="text-type-body mt-4 flex min-h-11 items-center gap-3 text-[var(--color-ink)]">
                <input
                  checked={isConfirmed}
                  className="size-5 accent-[var(--color-brass)] focus-visible:outline-[0.1875rem] focus-visible:outline-[var(--color-focus)] focus-visible:outline-offset-[0.1875rem]"
                  onChange={(event) => setIsConfirmed(event.target.checked)}
                  disabled={isSubmitting}
                  type="checkbox"
                />
                I understand this is a permanent corpus update
              </label>
              <button
                className="text-type-control mt-4 inline-flex min-h-11 items-center justify-center rounded-[var(--radius-compact)] bg-[var(--color-brass)] px-4 font-semibold text-[var(--color-inverse)] transition-colors duration-[var(--motion-fast)] hover:bg-[var(--color-brass-hover)] focus-visible:outline-[0.1875rem] focus-visible:outline-[var(--color-focus)] focus-visible:outline-offset-[0.1875rem] disabled:cursor-not-allowed disabled:opacity-60"
                disabled={!canSubmit}
                onClick={() => void submitBatch()}
                type="button"
              >
                Start ingestion
              </button>
            </section>
          </section>

          <section
            aria-labelledby="jobs-heading"
            className="min-w-0 lg:border-l lg:border-[var(--color-border)] lg:pl-8"
          >
            <p className="text-type-label font-semibold uppercase tracking-wide text-[var(--color-brass-hover)]">
              Current session
            </p>
            <h2
              className="font-display text-type-heading-lg mt-1 mb-4 font-semibold text-[var(--color-ink)]"
              id="jobs-heading"
            >
              Ingestion jobs
            </h2>
            {activePollingFailure ? (
              <div className="mb-4">
                <ErrorMessage
                  message={errorCopy.admin.polling[activePollingFailure].message}
                  title={errorCopy.admin.polling[activePollingFailure].title}
                  variant="banner"
                />
              </div>
            ) : null}
            <div
              aria-atomic="false"
              aria-label="Ingestion job updates"
              aria-live="polite"
              aria-relevant="additions text"
              className="[&>p]:text-[var(--color-body)]"
              role="log"
            >
              <IngestionProgress failureContentByJobId={failureContentByJobId} jobs={orderedJobs} />
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}
