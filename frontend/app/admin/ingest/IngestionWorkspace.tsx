'use client';

import { useState } from 'react';

import { UploadDropzone } from '../../../components/shared/UploadDropzone';
import type { DocumentType } from '../../../lib/mocks/adminIngestion';
import { canSubmitBatch, reconcileDrafts, type IngestionDraft } from './ingestion-model';

// TODO(contract): confirm doc_type values with Ananthu/Roshinee before treating
// judgment | statute | other as the live documents-table contract.
const documentTypeOptions: ReadonlyArray<{ value: DocumentType; label: string }> = [
  { value: 'judgment', label: 'Judgment' },
  { value: 'statute', label: 'Statute' },
  { value: 'other', label: 'Other' },
];

const createDraftId = () => crypto.randomUUID();

export function IngestionWorkspace() {
  const [drafts, setDrafts] = useState<IngestionDraft[]>([]);
  const [isConfirmed, setIsConfirmed] = useState(false);
  const isSubmitting = false;
  const incompleteNames = drafts
    .filter((draft) => draft.documentType === '')
    .map((draft) => draft.file.name);
  const canSubmit = canSubmitBatch(drafts, isConfirmed, isSubmitting);

  const handleFilesSelected = (files: File[]) => {
    setDrafts((previous) => {
      const addsOrReplacesAFile = files.some(
        (file) => !previous.some((draft) => draft.file === file),
      );

      if (addsOrReplacesAFile) {
        setIsConfirmed(false);
      }

      return reconcileDrafts(previous, files, createDraftId);
    });
  };

  const updateDraft = (
    id: string,
    updates: Partial<Pick<IngestionDraft, 'documentType' | 'note'>>,
  ) => {
    setDrafts((previous) =>
      previous.map((draft) => (draft.id === id ? { ...draft, ...updates } : draft)),
    );
  };

  return (
    <main className="min-h-screen bg-[var(--color-canvas)] px-4 py-8 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-6xl">
        <header className="border-b border-[var(--color-border)] pb-6">
          <p className="text-type-label font-semibold uppercase tracking-wide text-[var(--color-brass)]">
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

        <section aria-labelledby="batch-heading" className="mt-6 max-w-3xl space-y-6">
          <div>
            <p className="text-type-label font-semibold uppercase tracking-wide text-[var(--color-brass)]">
              Prepare batch
            </p>
            <h2
              className="font-display text-type-heading-lg mt-1 font-semibold text-[var(--color-ink)]"
              id="batch-heading"
            >
              Select documents and metadata
            </h2>
          </div>

          <UploadDropzone accept="application/pdf" multiple onFilesSelected={handleFilesSelected} />

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
                          onChange={(event) => updateDraft(draft.id, { note: event.target.value })}
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
              {drafts.length} {drafts.length === 1 ? 'file' : 'files'} will be permanently added to
              the shared corpus.
            </p>
            <label className="text-type-body mt-4 flex min-h-11 items-center gap-3 text-[var(--color-ink)]">
              <input
                checked={isConfirmed}
                className="size-5 accent-[var(--color-brass)] focus-visible:outline-[0.1875rem] focus-visible:outline-[var(--color-focus)] focus-visible:outline-offset-[0.1875rem]"
                onChange={(event) => setIsConfirmed(event.target.checked)}
                type="checkbox"
              />
              I understand this is a permanent corpus update
            </label>
            <button
              className="text-type-control mt-4 inline-flex min-h-11 items-center justify-center rounded-[var(--radius-compact)] bg-[var(--color-brass)] px-4 font-semibold text-[var(--color-inverse)] transition-colors duration-[var(--motion-fast)] hover:bg-[var(--color-brass-hover)] focus-visible:outline-[0.1875rem] focus-visible:outline-[var(--color-focus)] focus-visible:outline-offset-[0.1875rem] disabled:cursor-not-allowed disabled:opacity-60"
              disabled={!canSubmit}
              type="button"
            >
              Start ingestion
            </button>
          </section>
        </section>
      </div>
    </main>
  );
}
