'use client';

import { useState } from 'react';

import {
  ErrorMessage,
  IngestionProgress,
  LoadingSpinner,
  ResponseCard,
  UploadDropzone,
  type IngestionJob,
} from '@/components/shared';

import {
  advancedIngestionJobs,
  initialIngestionJobs,
  professionalAnswer,
  publicAnswer,
  responseCitations,
  responseSections,
} from './fixtures';

type ResponseMode = 'professional' | 'public';

const panelClass =
  'rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-4 shadow-[var(--shadow-component)] sm:p-6';

const sectionHeadingClass =
  'font-[family-name:var(--font-display)] text-2xl font-semibold text-[var(--color-ink)]';

const modeButtonBaseClass =
  'inline-flex min-h-11 flex-1 items-center justify-center rounded-[var(--radius-compact)] px-4 text-sm font-semibold transition-colors duration-[var(--motion-fast)]';

function copyJobs(jobs: IngestionJob[]) {
  return jobs.map((job) => ({ ...job }));
}

export function PreviewGallery() {
  const [selectedFileCount, setSelectedFileCount] = useState(0);
  const [retryMessage, setRetryMessage] = useState('');
  const [jobs, setJobs] = useState<IngestionJob[]>(() => copyJobs(initialIngestionJobs));
  const [hasAdvanced, setHasAdvanced] = useState(false);
  const [responseMode, setResponseMode] = useState<ResponseMode>('professional');

  const acknowledgeRetry = (example: string) => {
    setRetryMessage(`Retry requested for the ${example} example.`);
  };

  const advanceProgress = () => {
    const nextJobs = hasAdvanced ? initialIngestionJobs : advancedIngestionJobs;

    setJobs(copyJobs(nextJobs));
    setHasAdvanced((current) => !current);
  };

  return (
    <div className="min-h-screen bg-[var(--color-canvas)]">
      <header className="border-b border-[var(--color-border)] bg-[var(--color-surface)]">
        <div className="mx-auto flex max-w-[90rem] items-center gap-3 px-4 py-4 sm:px-6 lg:px-8">
          <span
            aria-hidden="true"
            className="inline-flex size-10 items-center justify-center rounded-[var(--radius-compact)] bg-[var(--color-ink)] font-[family-name:var(--font-display)] text-lg font-semibold text-[var(--color-brass)]"
          >
            §
          </span>
          <div className="min-w-0">
            <p className="font-[family-name:var(--font-display)] text-xl font-semibold text-[var(--color-ink)]">
              LegalAI
            </p>
            <p className="truncate text-xs text-[var(--color-muted)]">
              Indian criminal law research assistant
            </p>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[90rem] space-y-8 px-4 py-8 sm:px-6 lg:px-8">
        <div>
          <h1 className="font-[family-name:var(--font-display)] text-3xl font-semibold tracking-tight text-[var(--color-ink)] sm:text-4xl">
            LegalAI Component Library
          </h1>
          <p className="mt-2 text-[var(--color-muted)]">
            Shared UX for Public, Professional, and Admin modes
          </p>
        </div>

        <div className="grid gap-8 [@media(min-width:1100px)]:grid-cols-2">
          <div className="space-y-8">
            <section aria-labelledby="loading-spinner-heading" className="space-y-4">
              <h2 className={sectionHeadingClass} id="loading-spinner-heading">
                1. LoadingSpinner
              </h2>
              <div className={panelClass}>
                <div className="grid grid-cols-3 gap-4 text-center">
                  {(['sm', 'md', 'lg'] as const).map((size) => (
                    <div
                      className="flex min-h-28 flex-col items-center justify-center gap-3"
                      key={size}
                    >
                      <span className="text-xs font-semibold uppercase tracking-wide text-[var(--color-muted)]">
                        {size}
                      </span>
                      <LoadingSpinner
                        label={`${size === 'sm' ? 'Small' : size === 'md' ? 'Medium' : 'Large'} loading spinner`}
                        size={size}
                      />
                    </div>
                  ))}
                </div>
              </div>
            </section>

            <section aria-labelledby="error-message-heading" className="space-y-4">
              <h2 className={sectionHeadingClass} id="error-message-heading">
                2. ErrorMessage
              </h2>
              <div className={`${panelClass} space-y-4`}>
                <div>
                  <p className="mb-2 text-sm font-semibold text-[var(--color-muted)]">Inline</p>
                  <ErrorMessage
                    message="The legal reference could not be loaded. Please try again."
                    onRetry={() => acknowledgeRetry('inline')}
                    title="Reference unavailable"
                    variant="inline"
                  />
                </div>
                <div>
                  <p className="mb-2 text-sm font-semibold text-[var(--color-muted)]">Banner</p>
                  <ErrorMessage
                    message="We could not process this document right now."
                    onRetry={() => acknowledgeRetry('banner')}
                    title="Document processing paused"
                    variant="banner"
                  />
                </div>
                <div>
                  <p className="mb-2 text-sm font-semibold text-[var(--color-muted)]">Full page</p>
                  <ErrorMessage
                    message="Your request is safe to retry. No document changes were made."
                    onRetry={() => acknowledgeRetry('full-page')}
                    technicalDetail="Reference service temporarily unavailable."
                    title="We could not complete this request"
                    variant="fullpage"
                  />
                </div>
                <p
                  aria-live="polite"
                  className="min-h-6 text-sm font-medium text-[var(--color-success-foreground)]"
                >
                  {retryMessage}
                </p>
              </div>
            </section>
          </div>

          <div className="space-y-8">
            <section aria-labelledby="upload-dropzone-heading" className="space-y-4">
              <h2 className={sectionHeadingClass} id="upload-dropzone-heading">
                3. UploadDropzone
              </h2>
              <div className={panelClass}>
                <UploadDropzone
                  maxSizeMB={50}
                  multiple
                  onFilesSelected={(files) => setSelectedFileCount(files.length)}
                />
                <p aria-live="polite" className="mt-4 min-h-6 text-sm text-[var(--color-muted)]">
                  {selectedFileCount > 0
                    ? `${selectedFileCount} PDF${selectedFileCount === 1 ? '' : 's'} selected for this local preview.`
                    : 'No PDFs selected.'}
                </p>
              </div>
            </section>

            <section aria-labelledby="ingestion-progress-heading" className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className={sectionHeadingClass} id="ingestion-progress-heading">
                  4. IngestionProgress
                </h2>
                <button
                  className="inline-flex min-h-11 items-center justify-center rounded-[var(--radius-compact)] border border-[var(--color-ink)] px-4 text-sm font-semibold text-[var(--color-ink)] transition-colors duration-[var(--motion-fast)] hover:bg-[var(--color-ink)] hover:text-[var(--color-inverse)]"
                  onClick={advanceProgress}
                  type="button"
                >
                  Advance progress
                </button>
              </div>
              <div className={panelClass}>
                <IngestionProgress jobs={jobs} />
              </div>
            </section>
          </div>
        </div>

        <section aria-labelledby="response-card-heading" className="space-y-4">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <h2 className={sectionHeadingClass} id="response-card-heading">
              5. ResponseCard
            </h2>
            <div
              aria-label="Response mode"
              className="flex min-w-64 rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-1"
              role="group"
            >
              {(['professional', 'public'] as const).map((mode) => {
                const selected = responseMode === mode;
                const label = mode === 'professional' ? 'Professional' : 'Public';

                return (
                  <button
                    aria-pressed={selected}
                    className={`${modeButtonBaseClass} ${
                      selected
                        ? 'bg-[var(--color-ink)] text-[var(--color-inverse)]'
                        : 'text-[var(--color-ink)] hover:bg-[var(--color-surface-subtle)]'
                    }`}
                    key={mode}
                    onClick={() => setResponseMode(mode)}
                    type="button"
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          </div>
          <ResponseCard
            citations={responseCitations}
            content={responseMode === 'professional' ? professionalAnswer : publicAnswer}
            mode={responseMode}
            sections={responseSections}
          />
        </section>
      </main>
    </div>
  );
}
