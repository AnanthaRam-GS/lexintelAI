'use client';

import { CheckCircle2, LoaderCircle } from 'lucide-react';

import { ErrorIcon } from './shared-icons';
import { ErrorMessage } from './ErrorMessage';

export type IngestionStage =
  'QUEUED' | 'EXTRACTING' | 'CHUNKING' | 'EMBEDDING' | 'INDEXING' | 'COMPLETED' | 'FAILED';

export interface IngestionJob {
  id: string;
  filename: string;
  stage: IngestionStage;
  progress: number;
  error?: string;
}

export interface IngestionProgressProps {
  jobs: IngestionJob[];
}

const clampProgress = (progress: number) =>
  Number.isNaN(progress) ? 0 : Math.min(100, Math.max(0, progress));

const fallbackFailureMessage = 'Ingestion could not be completed. Retry this document.';

function StageIcon({ stage }: { stage: IngestionStage }) {
  if (stage === 'COMPLETED') {
    return (
      <CheckCircle2
        aria-hidden="true"
        className="shrink-0 text-[var(--color-success-foreground)]"
        size={20}
        strokeWidth={1.8}
      />
    );
  }

  if (stage === 'FAILED') {
    return (
      <ErrorIcon
        className="shrink-0 text-[var(--color-error-foreground)]"
        size={20}
        strokeWidth={1.8}
      />
    );
  }

  return (
    <LoaderCircle
      aria-hidden="true"
      className="shrink-0 text-[var(--color-info-foreground)]"
      size={20}
      strokeWidth={1.8}
    />
  );
}

function stageLabelClass(stage: IngestionStage) {
  if (stage === 'COMPLETED') {
    return 'text-[var(--color-success-foreground)]';
  }

  if (stage === 'FAILED') {
    return 'text-[var(--color-error-foreground)]';
  }

  return 'text-[var(--color-ink)]';
}

function progressClass(stage: IngestionStage) {
  if (stage === 'COMPLETED') {
    return 'bg-[var(--color-success)]';
  }

  if (stage === 'FAILED') {
    return 'bg-[var(--color-error)]';
  }

  return 'bg-[var(--color-info)]';
}

export function IngestionProgress({ jobs }: IngestionProgressProps) {
  if (jobs.length === 0) {
    return (
      <p className="rounded-[var(--radius-standard)] bg-[var(--color-surface-subtle)] p-4 text-sm text-[var(--color-muted)]">
        No ingestion jobs yet.
      </p>
    );
  }

  return (
    <ul aria-label="Ingestion jobs" className="space-y-3" data-testid="ingestion-jobs">
      {jobs.map((job) => {
        const progress = clampProgress(job.progress);
        const isFailed = job.stage === 'FAILED';
        const rowBorder = isFailed
          ? 'border-[var(--color-error-border)]'
          : job.stage === 'COMPLETED'
            ? 'border-[var(--color-success-border)]'
            : 'border-[var(--color-border)]';
        const rowSurface = isFailed
          ? 'bg-[var(--color-error-surface)]'
          : job.stage === 'COMPLETED'
            ? 'bg-[var(--color-success-surface)]'
            : 'bg-[var(--color-surface)]';

        return (
          <li
            className={`min-w-0 rounded-[var(--radius-standard)] border p-4 ${rowBorder} ${rowSurface}`}
            key={job.id}
          >
            <div className="flex min-w-0 items-start gap-3">
              <StageIcon stage={job.stage} />
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium text-[var(--color-ink)]" title={job.filename}>
                  {job.filename}
                </p>
                <p
                  className={`mt-1 flex min-h-6 items-center gap-2 text-sm font-semibold ${stageLabelClass(job.stage)}`}
                >
                  <span>Stage</span>
                  <span aria-label={`${job.filename} stage`}>{job.stage}</span>
                </p>
              </div>
            </div>

            <div className="mt-3 min-h-8" aria-label={`${job.filename} progress region`}>
              <div
                aria-label={`${job.filename} progress`}
                aria-valuemax={100}
                aria-valuemin={0}
                aria-valuenow={progress}
                className="h-2 w-full overflow-hidden rounded-full bg-[var(--color-surface-subtle)]"
                role="progressbar"
              >
                <div
                  aria-hidden="true"
                  className={`h-full rounded-full transition-[width] duration-[var(--motion-standard)] ${progressClass(job.stage)}`}
                  style={{ width: `${progress}%` }}
                />
              </div>
              <p className="mt-1 text-right text-xs text-[var(--color-muted)]">{progress}%</p>
            </div>

            <div className="mt-3 min-h-24">
              {isFailed ? (
                <ErrorMessage
                  message={fallbackFailureMessage}
                  title={`Unable to ingest ${job.filename}`}
                  variant="inline"
                />
              ) : null}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
