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
  /**
   * Optional caller-owned, pre-sanitized copy. Raw job.error values remain
   * deliberately unrendered so existing consumers keep the safe default.
   */
  failureContentByJobId?: Readonly<Record<string, { title: string; message: string }>>;
}

const clampProgress = (progress: number) =>
  Number.isNaN(progress) ? 0 : Math.min(100, Math.max(0, progress));

const fallbackFailureTitle = 'Ingestion failed';
const fallbackFailureMessage = 'Retry this document.';

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

export function IngestionProgress({ failureContentByJobId, jobs }: IngestionProgressProps) {
  if (jobs.length === 0) {
    return (
      <p className="text-type-body-sm rounded-[var(--radius-standard)] bg-[var(--color-surface-subtle)] p-4 text-[var(--color-muted)]">
        No ingestion jobs yet.
      </p>
    );
  }

  return (
    <ul aria-label="Ingestion jobs" className="space-y-2" data-testid="ingestion-jobs">
      {jobs.map((job) => {
        const progress = clampProgress(job.progress);
        const isFailed = job.stage === 'FAILED';
        const failureContent = failureContentByJobId?.[job.id] ?? {
          title: fallbackFailureTitle,
          message: fallbackFailureMessage,
        };
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
            className={`min-w-0 rounded-[var(--radius-standard)] border p-3 sm:p-4 ${rowBorder} ${rowSurface}`}
            key={job.id}
          >
            <div className="flex min-w-0 items-center gap-3">
              <StageIcon stage={job.stage} />
              <div className="min-w-0 flex-1 sm:flex sm:items-center sm:justify-between sm:gap-3">
                <p
                  className="text-type-body truncate font-medium text-[var(--color-ink)]"
                  title={job.filename}
                >
                  {job.filename}
                </p>
                <p
                  className={`text-type-caption mt-1 flex shrink-0 items-center gap-2 font-semibold sm:mt-0 ${stageLabelClass(job.stage)}`}
                >
                  <span>Stage</span>
                  <span>{job.stage}</span>
                </p>
              </div>
            </div>

            <div
              className="mt-2 flex h-[var(--size-ingestion-status)] items-center overflow-hidden"
              data-ingestion-error-region
            >
              {isFailed ? (
                <div className="w-full">
                  <ErrorMessage
                    message={failureContent.message}
                    title={failureContent.title}
                    variant="inline"
                  />
                </div>
              ) : (
                <div className="flex w-full items-center gap-3" data-ingestion-progress-region>
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
                  <p className="text-type-caption w-10 shrink-0 text-right text-[var(--color-muted)]">
                    {progress}%
                  </p>
                </div>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
