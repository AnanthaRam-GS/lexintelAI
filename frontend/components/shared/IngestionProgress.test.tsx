import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { IngestionProgress, type IngestionJob } from './IngestionProgress';

describe('IngestionProgress', () => {
  afterEach(cleanup);

  it('renders every frozen stage label exactly', () => {
    const stages: IngestionJob[] = [
      { id: 'queued', filename: 'queued.pdf', stage: 'QUEUED', progress: 0 },
      { id: 'extracting', filename: 'extracting.pdf', stage: 'EXTRACTING', progress: 12 },
      { id: 'chunking', filename: 'chunking.pdf', stage: 'CHUNKING', progress: 28 },
      { id: 'embedding', filename: 'embedding.pdf', stage: 'EMBEDDING', progress: 44 },
      { id: 'indexing', filename: 'indexing.pdf', stage: 'INDEXING', progress: 72 },
      { id: 'completed', filename: 'completed.pdf', stage: 'COMPLETED', progress: 100 },
      { id: 'failed', filename: 'failed.pdf', stage: 'FAILED', progress: 38 },
    ];

    render(<IngestionProgress jobs={stages} />);

    stages.forEach(({ stage }) => {
      expect(screen.getByText(stage, { exact: true })).toBeInTheDocument();
    });
  });

  it('clamps progress to 0 through 100 in the bar and its accessible value', () => {
    const jobs: IngestionJob[] = [
      { id: 'below', filename: 'below.pdf', stage: 'EXTRACTING', progress: -25 },
      { id: 'above', filename: 'above.pdf', stage: 'COMPLETED', progress: 120 },
    ];

    render(<IngestionProgress jobs={jobs} />);

    expect(screen.getByRole('progressbar', { name: 'below.pdf progress' })).toHaveAttribute(
      'aria-valuenow',
      '0',
    );
    expect(screen.getByRole('progressbar', { name: 'above.pdf progress' })).toHaveAttribute(
      'aria-valuenow',
      '100',
    );
  });

  it('keeps generic stage and progress wrappers free from unsupported accessible names', () => {
    render(
      <IngestionProgress
        jobs={[{ id: 'named', filename: 'named.pdf', stage: 'EXTRACTING', progress: 42 }]}
      />,
    );

    const stage = screen.getByText('EXTRACTING', { exact: true });
    const progress = screen.getByRole('progressbar', { name: 'named.pdf progress' });

    expect(stage).not.toHaveAttribute('aria-label');
    expect(progress.parentElement).not.toHaveAttribute('aria-label');
  });

  it('renders failed-job errors through a safe shared alert', () => {
    render(
      <IngestionProgress
        jobs={[
          {
            id: 'failed',
            filename: 'failed.pdf',
            stage: 'FAILED',
            progress: 72,
            error: 'Indexing could not be completed.',
          },
        ]}
      />,
    );

    expect(screen.getByRole('alert')).toHaveTextContent(
      'Ingestion could not be completed. Retry this document.',
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Unable to ingest failed.pdf');
    expect(screen.queryByText('Indexing could not be completed.')).not.toBeInTheDocument();
  });

  it('does not expose stack or exception details from a failed job', () => {
    render(
      <IngestionProgress
        jobs={[
          {
            id: 'unsafe-failure',
            filename: 'unsafe.pdf',
            stage: 'FAILED',
            progress: 72,
            error: 'RuntimeError: database unavailable\n    at /srv/indexer.py:42',
          },
        ]}
      />,
    );

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('Ingestion could not be completed. Retry this document.');
    expect(alert).not.toHaveTextContent('RuntimeError');
    expect(alert).not.toHaveTextContent('/srv/indexer.py:42');
  });

  it('replaces every untrusted backend failure with fixed safe copy', () => {
    const unsafeErrors = [
      'TypeError: unable to read /srv/customer-data.json',
      'psql: ERROR: relation clients does not exist',
      'token=super-secret-value-123',
    ];

    render(
      <IngestionProgress
        jobs={unsafeErrors.map((error, index) => ({
          id: `unsafe-${index}`,
          filename: `unsafe-${index}.pdf`,
          stage: 'FAILED' as const,
          progress: 72,
          error,
        }))}
      />,
    );

    const alerts = screen.getAllByRole('alert');
    expect(alerts).toHaveLength(unsafeErrors.length);
    alerts.forEach((alert) => {
      expect(alert).toHaveTextContent('Ingestion could not be completed. Retry this document.');
    });
    unsafeErrors.forEach((error) => {
      expect(document.body.textContent).not.toContain(error);
    });
  });

  it('renders a quiet empty state when there are no jobs', () => {
    render(<IngestionProgress jobs={[]} />);

    expect(screen.getByText('No ingestion jobs yet.')).toBeInTheDocument();
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  });

  it('keeps one filename row while polling updates stage and progress', () => {
    const { rerender } = render(
      <IngestionProgress
        jobs={[{ id: 'polling', filename: 'polling.pdf', stage: 'EXTRACTING', progress: 20 }]}
      />,
    );

    expect(screen.getAllByText('polling.pdf')).toHaveLength(1);
    expect(screen.getByRole('progressbar', { name: 'polling.pdf progress' })).toHaveAttribute(
      'aria-valuenow',
      '20',
    );

    rerender(
      <IngestionProgress
        jobs={[{ id: 'polling', filename: 'polling.pdf', stage: 'CHUNKING', progress: 48 }]}
      />,
    );

    expect(screen.getAllByText('polling.pdf')).toHaveLength(1);
    expect(screen.getByText('CHUNKING', { exact: true })).toBeInTheDocument();
    expect(screen.queryByText('EXTRACTING', { exact: true })).not.toBeInTheDocument();
    expect(screen.getByRole('progressbar', { name: 'polling.pdf progress' })).toHaveAttribute(
      'aria-valuenow',
      '48',
    );
  });
});
