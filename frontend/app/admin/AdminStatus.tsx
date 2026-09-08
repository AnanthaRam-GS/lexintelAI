'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import {
  CheckCircle2,
  CircleX,
  FilePlus2,
  RefreshCw,
  TriangleAlert,
  type LucideIcon,
} from 'lucide-react';

import { ErrorMessage } from '../../components/shared/ErrorMessage';
import { LoadingSpinner } from '../../components/shared/LoadingSpinner';
import {
  fetchCorpusStatsMock,
  type CorpusStats,
  type ServiceHealth,
  type ServiceStatus,
} from '../../lib/mocks/adminIngestion';

const healthView: Record<ServiceHealth, { label: string; Icon: LucideIcon; className: string }> = {
  healthy: {
    label: 'Healthy',
    Icon: CheckCircle2,
    className: 'text-[var(--color-success-foreground)]',
  },
  degraded: {
    label: 'Degraded',
    Icon: TriangleAlert,
    className: 'text-[var(--color-warning-foreground)]',
  },
  down: {
    label: 'Down',
    Icon: CircleX,
    className: 'text-[var(--color-error-foreground)]',
  },
};

function ServiceHealthRegion({
  name,
  service,
}: {
  name: 'ChromaDB' | 'PostgreSQL';
  service: ServiceStatus;
}) {
  const { Icon, className, label } = healthView[service.status];

  return (
    <section
      aria-label={`${name} status`}
      className="rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-5 shadow-[var(--shadow-component)]"
    >
      <div className="flex items-start gap-3">
        <Icon
          aria-hidden="true"
          className={`mt-0.5 size-5 shrink-0 ${className}`}
          strokeWidth={1.8}
        />
        <div>
          <h2 className="font-display text-type-heading-sm font-semibold text-[var(--color-ink)]">
            {name}
          </h2>
          <p className={`text-type-body mt-1 font-semibold ${className}`}>{label}</p>
          {service.detail ? (
            <p className="text-type-body-sm mt-1 text-[var(--color-muted)]">{service.detail}</p>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function StatusRegions({ stats }: { stats: CorpusStats }) {
  return (
    <div className="grid gap-5 lg:grid-cols-12">
      <section
        aria-labelledby="corpus-heading"
        className="rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-5 shadow-[var(--shadow-component)] sm:p-6 lg:col-span-7"
      >
        <p className="text-type-label font-semibold uppercase tracking-wide text-[var(--color-brass-hover)]">
          Corpus overview
        </p>
        <h2
          className="font-display text-type-heading-lg mt-1 font-semibold text-[var(--color-ink)]"
          id="corpus-heading"
        >
          Corpus
        </h2>
        <p className="font-display text-type-heading-xl mt-5 font-semibold text-[var(--color-ink)]">
          {stats.totalDocuments} documents
        </p>
        <dl className="text-type-body-sm mt-5 grid gap-3 border-t border-[var(--color-border)] pt-4 text-[var(--color-body)] sm:grid-cols-3">
          <div>
            <dt className="text-[var(--color-muted)]">Judgments</dt>
            <dd className="mt-1 font-semibold text-[var(--color-ink)]">
              Judgments: {stats.breakdown.judgment}
            </dd>
          </div>
          <div>
            <dt className="text-[var(--color-muted)]">Statutes</dt>
            <dd className="mt-1 font-semibold text-[var(--color-ink)]">
              Statutes: {stats.breakdown.statute}
            </dd>
          </div>
          <div>
            <dt className="text-[var(--color-muted)]">Other</dt>
            <dd className="mt-1 font-semibold text-[var(--color-ink)]">
              Other: {stats.breakdown.other}
            </dd>
          </div>
        </dl>
        <div className="text-type-body-sm mt-5 space-y-1 border-t border-[var(--color-border)] pt-4 text-[var(--color-muted)]">
          <p>Last ingestion: {stats.lastIngestionDate}</p>
          <p>Last updated: {stats.lastUpdatedTimestamp}</p>
        </div>
      </section>

      <div className="grid gap-5 sm:grid-cols-2 lg:col-span-5 lg:grid-cols-1">
        <ServiceHealthRegion name="ChromaDB" service={stats.chromaDb} />
        <ServiceHealthRegion name="PostgreSQL" service={stats.postgresql} />
      </div>

      <section
        aria-labelledby="ingest-heading"
        className="rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:flex sm:items-center sm:justify-between lg:col-span-12"
      >
        <div className="flex items-start gap-3">
          <FilePlus2
            aria-hidden="true"
            className="mt-0.5 size-5 text-[var(--color-brass)]"
            strokeWidth={1.8}
          />
          <div>
            <h2
              className="font-display text-type-heading-sm font-semibold text-[var(--color-ink)]"
              id="ingest-heading"
            >
              Ingest documents
            </h2>
            <p className="text-type-body-sm mt-1 text-[var(--color-muted)]">
              Permanently add reviewed documents to the shared corpus.
            </p>
          </div>
        </div>
        <Link
          className="text-type-control mt-4 inline-flex min-h-11 items-center justify-center rounded-[var(--radius-compact)] bg-[var(--color-brass)] px-4 font-semibold text-[var(--color-inverse)] transition-colors duration-[var(--motion-fast)] hover:bg-[var(--color-brass-hover)] focus-visible:outline-[0.1875rem] focus-visible:outline-[var(--color-focus)] focus-visible:outline-offset-[0.1875rem] sm:mt-0"
          href="/admin/ingest"
        >
          Ingest documents
        </Link>
      </section>
    </div>
  );
}

export function AdminStatus() {
  const [stats, setStats] = useState<CorpusStats | null>(null);
  const [pending, setPending] = useState(true);
  const [error, setError] = useState(false);
  const isLoadingRef = useRef(false);

  const loadStatus = useCallback(async () => {
    if (isLoadingRef.current) return;

    isLoadingRef.current = true;
    setPending(true);
    setError(false);

    try {
      setStats(await fetchCorpusStatsMock());
    } catch {
      setError(true);
    } finally {
      isLoadingRef.current = false;
      setPending(false);
    }
  }, []);

  useEffect(() => {
    void Promise.resolve().then(loadStatus);
  }, [loadStatus]);

  if (pending && !stats) {
    return <LoadingSpinner fullScreen label="Loading system status" />;
  }

  return (
    <main className="min-h-screen bg-[var(--color-canvas)] px-4 py-8 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-6xl">
        <header className="flex flex-col gap-5 border-b border-[var(--color-border)] pb-6 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-type-label font-semibold uppercase tracking-wide text-[var(--color-brass-hover)]">
              Admin
            </p>
            <h1 className="font-display text-type-heading-xl mt-1 font-semibold tracking-tight text-[var(--color-ink)] sm:text-type-heading-2xl">
              System status
            </h1>
          </div>
          <button
            className="text-type-control inline-flex min-h-11 items-center justify-center gap-2 self-start rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-surface)] px-4 font-semibold text-[var(--color-body)] transition-colors duration-[var(--motion-fast)] hover:bg-[var(--color-surface-subtle)] focus-visible:outline-[0.1875rem] focus-visible:outline-[var(--color-focus)] focus-visible:outline-offset-[0.1875rem] disabled:cursor-not-allowed disabled:opacity-60 sm:self-auto"
            disabled={pending}
            onClick={() => void loadStatus()}
            type="button"
          >
            <RefreshCw
              aria-hidden="true"
              className={pending ? 'size-4 animate-spin motion-reduce:animate-none' : 'size-4'}
              strokeWidth={1.8}
            />
            Refresh status
          </button>
        </header>

        <div className="mt-6 space-y-6">
          {error ? (
            <ErrorMessage
              message="System status could not be loaded. Try again."
              onRetry={() => void loadStatus()}
              title="Unable to load system status"
              variant="banner"
            />
          ) : null}
          {stats ? <StatusRegions stats={stats} /> : null}
        </div>
      </div>
    </main>
  );
}
