'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { IngestionProgress, type IngestionJob } from '../../../components/shared/IngestionProgress';
import { UploadDropzone } from '../../../components/shared/UploadDropzone';
import {
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
  const [hasSubmitError, setHasSubmitError] = useState(false);
  const [jobs, setJobs] = useState<IngestionJob[]>([]);
  const [uploadKey, setUploadKey] = useState(0);
  const timersRef = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const pollingRef = useRef(new Map<string, symbol>());
  const aliveRef = useRef(true);
  const incompleteNames = drafts
    .filter((draft) => draft.documentType === '')
    .map((draft) => draft.file.name);
  const canSubmit = canSubmitBatch(drafts, isConfirmed, isSubmitting);
  const orderedJobs = jobs;

  const stopPolling = useCallback((jobId: string) => {
    const timer = timersRef.current.get(jobId);
    if (timer) clearTimeout(timer);
    timersRef.current.delete(jobId);
    pollingRef.current.delete(jobId);
  }, []);

  const startPolling = useCallback(
    (jobId: string) => {
      if (pollingRef.current.has(jobId)) return;
      const generation = Symbol(jobId);
      pollingRef.current.set(jobId, generation);

      const isCurrentPoll = () => aliveRef.current && pollingRef.current.get(jobId) === generation;

      const poll = async (): Promise<void> => {
        if (!isCurrentPoll()) return;
        try {
          const live = await pollIngestionStatusMock(jobId);
          if (!isCurrentPoll()) return;
          setJobs((current) => replaceJobById(current, live));
          if (isTerminal(live.stage)) {
            removePersistedJob(jobId);
            stopPolling(jobId);
            return;
          }
          persistActiveJob(live);
        } catch {
          if (!isCurrentPoll()) return;
          setJobs((current) => markJobFailedSafely(current, jobId));
          removePersistedJob(jobId);
          stopPolling(jobId);
          return;
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
    const polling = pollingRef.current;
    aliveRef.current = true;
    const restored = readPersistedIngestionJobs().map((record): IngestionJob => ({
      ...record,
      progress: progressForStage(record.stage),
    }));
    // Rehydration is an intentional client-only external-store synchronization.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setJobs(restored);
    restored.filter((job) => !isTerminal(job.stage)).forEach(({ id }) => startPolling(id));

    return () => {
      aliveRef.current = false;
      timers.forEach(clearTimeout);
      timers.clear();
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
    if (!canSubmitBatch(drafts, isConfirmed, isSubmitting)) return;
    setIsSubmitting(true);
    setHasSubmitError(false);

    try {
      const files = drafts.map(({ file }) => file);
      const metadata = drafts.map(({ documentType, note }) => ({
        documentType: documentType as DocumentType,
        note: note.trim() || undefined,
      }));
      const { jobIds } = await submitIngestionMock(files, metadata);
      if (jobIds.length !== drafts.length) throw new Error('Unexpected ingestion response');

      const queued = jobIds.map((id, index): IngestionJob => ({
        id,
        filename: drafts[index].file.name,
        stage: 'QUEUED',
        progress: progressForStage('QUEUED'),
      }));
      setJobs((current) => [...[...queued].reverse(), ...current]);
      queued.forEach(persistActiveJob);
      setDrafts([]);
      setIsConfirmed(false);
      setUploadKey((current) => current + 1);
      queued.forEach(({ id }) => startPolling(id));
    } catch {
      setHasSubmitError(true);
    } finally {
      setIsSubmitting(false);
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
              <section aria-label="Document metadata" className="space-y-3">
                {drafts.map((draft) => {
                  const typeId = `document-type-${draft.id}`;
                  const noteId = `document-note-${draft.id}`;
                  const errorId = `document-type-error-${draft.id}`;
                  const isIncomplete = draft.documentType === '';

                  return (
                    <article
                      className="rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-4 shadow-[var(--shadow-component)] sm:p-5"
                      key={draft.id}
                    >
                      <h3 className="text-type-body font-semibold text-[var(--color-ink)]">
                        {draft.file.name}
                      </h3>
                      <div className="mt-4 grid gap-4 sm:grid-cols-2">
                        <div>
                          <label
                            className="text-type-label font-semibold text-[var(--color-body)]"
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
                              className="text-type-body-sm mt-2 text-[var(--color-error-foreground)]"
                              id={errorId}
                            >
                              Choose a document type for {draft.file.name}.
                            </p>
                          ) : null}
                        </div>
                        <div>
                          <label
                            className="text-type-label font-semibold text-[var(--color-body)]"
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
              <p className="text-type-body-sm text-[var(--color-error-foreground)]" role="alert">
                Complete document types for: {incompleteNames.join(', ')}
              </p>
            ) : null}

            {hasSubmitError ? (
              <p className="text-type-body-sm text-[var(--color-error-foreground)]" role="alert">
                This ingestion batch could not be started. Review the files and try again.
              </p>
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
            <div
              aria-atomic="false"
              aria-label="Ingestion job updates"
              aria-live="polite"
              aria-relevant="additions text"
              className="[&>p]:text-[var(--color-body)]"
              role="log"
            >
              <IngestionProgress jobs={orderedJobs} />
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}
