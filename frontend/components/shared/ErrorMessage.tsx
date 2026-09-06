'use client';

import { ErrorIcon, RetryIcon } from './shared-icons';

export interface ErrorMessageProps {
  title: string;
  message: string;
  variant: 'inline' | 'banner' | 'fullpage';
  onRetry?: () => void;
  technicalDetail?: string;
}

const variantClasses = {
  inline: 'max-w-prose p-3',
  banner: 'p-4 sm:flex sm:items-start sm:gap-3',
  fullpage: 'mx-auto flex min-h-64 max-w-2xl flex-col justify-center p-6 sm:p-8',
} as const;

export function ErrorMessage({
  title,
  message,
  variant,
  onRetry,
  technicalDetail,
}: ErrorMessageProps) {
  return (
    <section
      className={`rounded-[var(--radius-standard)] border border-[var(--color-error-border)] bg-[var(--color-error-surface)] text-[var(--color-error-foreground)] ${variantClasses[variant]}`}
      data-variant={variant}
      role="alert"
    >
      <div className="flex items-start gap-3">
        <ErrorIcon className="mt-0.5 shrink-0" size={20} strokeWidth={1.8} />
        <div className="min-w-0 flex-1">
          <h2 className="font-[family-name:var(--font-display)] text-lg font-semibold text-[var(--color-ink)]">
            {title}
          </h2>
          <p className="mt-1 text-sm leading-6">{message}</p>

          {technicalDetail ? (
            <details className="mt-3 text-sm">
              <summary className="inline-flex min-h-11 w-fit cursor-pointer items-center font-medium text-[var(--color-error-foreground)] sm:min-h-0">
                Technical details
              </summary>
              <p className="mt-2 rounded-[var(--radius-compact)] bg-[var(--color-surface-raised)] p-3 text-[var(--color-body)]">
                {technicalDetail}
              </p>
            </details>
          ) : null}
        </div>
      </div>

      {onRetry ? (
        <button
          className="mt-4 inline-flex min-h-11 items-center justify-center gap-2 self-start rounded-[var(--radius-compact)] border border-[var(--color-error-foreground)] px-4 text-sm font-semibold text-[var(--color-error-foreground)] transition-colors duration-[var(--motion-fast)] hover:bg-[var(--color-error-foreground)] hover:text-[var(--color-inverse)] sm:mt-0"
          onClick={onRetry}
          type="button"
        >
          <RetryIcon size={16} strokeWidth={1.8} />
          Retry
        </button>
      ) : null}
    </section>
  );
}
