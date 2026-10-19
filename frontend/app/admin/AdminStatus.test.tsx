import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { getCorpusStatsMock } = vi.hoisted(() => ({
  getCorpusStatsMock: vi.fn(),
}));

vi.mock('../../lib/api', () => ({
  adminIngestionApi: {
    getCorpusStats: getCorpusStatsMock,
  },
}));

import type { CorpusStats } from '../../lib/types/api';

import { AdminStatus } from './AdminStatus';

const healthyStats: CorpusStats = {
  totalDocuments: 42,
  lastUpdatedTimestamp: '2026-09-08T09:00:00.000Z',
  lastIngestionDate: '2026-09-07T09:00:00.000Z',
  breakdown: { judgment: 20, statute: 12, other: 10 },
  chromaDb: { status: 'healthy', detail: 'Available' },
  postgresql: { status: 'healthy', detail: 'Available' },
  keywordIndex: { status: 'healthy' },
  chromaRecordCount: 1356,
  keywordRecordCount: 1356,
  postgresChunkCount: 1356,
  reconciliationJobCount: 0,
  reconciliationJobs: [],
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe('AdminStatus', () => {
  beforeEach(() => {
    getCorpusStatsMock.mockReset();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('renders four status regions with corpus detail and icon-and-text service health', async () => {
    getCorpusStatsMock.mockResolvedValue(healthyStats);
    render(<AdminStatus />);

    expect(screen.getByLabelText('Loading system status')).toBeInTheDocument();
    expect(screen.getByLabelText('Loading Corpus status')).toBeInTheDocument();
    expect(screen.getByLabelText('Loading ChromaDB status')).toBeInTheDocument();
    expect(screen.getByLabelText('Loading Keyword index status')).toBeInTheDocument();
    expect(screen.getByLabelText('Loading PostgreSQL status')).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Corpus' })).toBeInTheDocument();
    expect(screen.getByText('42 documents')).toBeInTheDocument();
    expect(screen.getByText('Judgments: 20')).toBeInTheDocument();
    expect(screen.getByText('Statutes: 12')).toBeInTheDocument();
    expect(screen.getByText('Other: 10')).toBeInTheDocument();
    const lastIngestion = screen.getByText('7 Sept 2026, 09:00 UTC');
    expect(lastIngestion).toHaveAttribute('datetime', '2026-09-07T09:00:00.000Z');
    const lastUpdated = screen.getByText('8 Sept 2026, 09:00 UTC');
    expect(lastUpdated).toHaveAttribute('datetime', '2026-09-08T09:00:00.000Z');
    expect(screen.queryByText('2026-09-08T09:00:00.000Z')).not.toBeInTheDocument();

    const chroma = screen.getByRole('region', { name: 'ChromaDB status' });
    expect(chroma).toHaveTextContent('Healthy');
    expect(chroma.querySelector('svg')).not.toBeNull();
    const postgres = screen.getByRole('region', { name: 'PostgreSQL status' });
    expect(postgres).toHaveTextContent('Healthy');
    expect(postgres.querySelector('svg')).not.toBeNull();

    expect(screen.getByRole('region', { name: 'Ingest documents' })).toContainElement(
      screen.getByRole('link', { name: 'Ingest documents' }),
    );
    expect(screen.getByRole('link', { name: 'Ingest documents' })).toHaveAttribute(
      'href',
      '/admin/ingest',
    );
  });

  it('shows each store count, the keyword index and an empty reconciliation list when healthy', async () => {
    getCorpusStatsMock.mockResolvedValue(healthyStats);
    render(<AdminStatus />);

    const chroma = await screen.findByRole('region', { name: 'ChromaDB status' });
    expect(chroma).toHaveTextContent('1,356 vectors');
    expect(chroma).toHaveTextContent('1,356 chunks in PostgreSQL');
    expect(chroma).not.toHaveTextContent('Reason:');
    const keyword = screen.getByRole('region', { name: 'Keyword index status' });
    expect(keyword).toHaveTextContent('Healthy');
    expect(keyword).toHaveTextContent('1,356 records');
    expect(screen.getByRole('region', { name: 'PostgreSQL status' })).toHaveTextContent(
      '1,356 chunks',
    );
    expect(
      screen.getByRole('region', { name: 'Ingestions needing reconciliation' }),
    ).toHaveTextContent('No failed ingestion has left data behind in the indexes.');
  });

  it('explains a degraded or down index with the reason and the mismatched counts', async () => {
    getCorpusStatsMock.mockResolvedValue({
      ...healthyStats,
      chromaDb: { status: 'degraded', detail: '1358 vectors but 1356 PostgreSQL chunks.' },
      chromaRecordCount: 1358,
      keywordIndex: { status: 'down', detail: 'The keyword index does not exist.' },
      keywordRecordCount: null,
    });
    render(<AdminStatus />);

    const chroma = await screen.findByRole('region', { name: 'ChromaDB status' });
    expect(chroma).toHaveTextContent('Degraded');
    expect(chroma).toHaveTextContent('Reason: 1358 vectors but 1356 PostgreSQL chunks.');
    expect(chroma).toHaveTextContent('1,358 vectors');
    const keyword = screen.getByRole('region', { name: 'Keyword index status' });
    expect(within(keyword).getByText('Down')).toBeInTheDocument();
    expect(keyword).toHaveTextContent('Reason: The keyword index does not exist.');
    expect(keyword).toHaveTextContent('records: unavailable');
  });

  it('lists ingestions that need reconciliation with their error code and message', async () => {
    getCorpusStatsMock.mockResolvedValue({
      ...healthyStats,
      reconciliationJobCount: 21,
      reconciliationJobs: [
        {
          jobId: 'job-7',
          errorCode: 'LEXICAL_INDEX_FAILED',
          message:
            'The keyword index could not be updated. Cleanup did not complete; the stores need reconciliation.',
          completedAt: '2026-10-19T08:30:00.000Z',
        },
      ],
    });
    render(<AdminStatus />);

    const region = await screen.findByRole('region', { name: 'Ingestions needing reconciliation' });
    expect(region).toHaveTextContent('21 failed ingestions could not be fully cleaned up.');
    expect(region).toHaveTextContent('Showing the 1 most recent.');
    const job = within(region).getByRole('listitem');
    expect(job).toHaveTextContent('Job job-7');
    expect(job).toHaveTextContent('The keyword index could not be updated.');
    expect(job).toHaveTextContent('(Error code: LEXICAL_INDEX_FAILED)');
    expect(within(job).getByText('19 Oct 2026, 08:30 UTC')).toHaveAttribute(
      'datetime',
      '2026-10-19T08:30:00.000Z',
    );
  });

  it('uses written labels and icons for degraded and down services', async () => {
    getCorpusStatsMock.mockResolvedValue({
      ...healthyStats,
      chromaDb: { status: 'degraded', detail: 'Reduced availability' },
      postgresql: { status: 'down', detail: 'postgresql://private-host/internal-stack' },
    });
    render(<AdminStatus />);

    const chroma = await screen.findByRole('region', { name: 'ChromaDB status' });
    expect(within(chroma).getByText('Degraded')).toBeInTheDocument();
    expect(chroma.querySelector('svg')).not.toBeNull();
    const postgres = screen.getByRole('region', { name: 'PostgreSQL status' });
    expect(within(postgres).getByText('Down')).toBeInTheDocument();
    expect(within(postgres).getByText('Currently unavailable')).toBeInTheDocument();
    expect(postgres).not.toHaveTextContent('private-host');
    expect(postgres.querySelector('svg')).not.toBeNull();
  });

  it('retries with fixed safe copy and never renders a rejection or technical detail', async () => {
    const user = userEvent.setup();
    const error = Object.assign(new Error('postgresql://private-host secret-stack'), {
      technicalDetail: 'private schema, credentials, and stack trace',
    });
    getCorpusStatsMock.mockRejectedValueOnce(error).mockResolvedValueOnce(healthyStats);
    render(<AdminStatus />);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('System status is currently unavailable');
    expect(alert).toHaveTextContent('The status service could not be reached.');
    expect(alert).not.toHaveTextContent('private-host');
    expect(alert).not.toHaveTextContent('private schema');
    expect(screen.queryByText('Technical details')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByRole('heading', { name: 'Corpus' })).toBeInTheDocument();
  });

  it('removes previously healthy cards when a later refresh cannot establish current status', async () => {
    const user = userEvent.setup();
    getCorpusStatsMock
      .mockResolvedValueOnce(healthyStats)
      .mockRejectedValueOnce(new Error('status unavailable'));
    render(<AdminStatus />);

    await screen.findByRole('heading', { name: 'Corpus' });
    await user.click(screen.getByRole('button', { name: 'Refresh status' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'System status is currently unavailable',
    );
    expect(screen.queryByRole('region', { name: 'Corpus' })).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'ChromaDB status' })).not.toBeInTheDocument();
  });

  it('does not overlap refresh requests', async () => {
    const user = userEvent.setup();
    const refresh = deferred<CorpusStats>();
    getCorpusStatsMock.mockResolvedValueOnce(healthyStats).mockReturnValueOnce(refresh.promise);
    render(<AdminStatus />);

    await screen.findByRole('heading', { name: 'Corpus' });
    const button = screen.getByRole('button', { name: 'Refresh status' });
    await user.click(button);
    expect(button).toBeDisabled();
    await user.click(button);
    expect(getCorpusStatsMock).toHaveBeenCalledTimes(2);
    refresh.resolve(healthyStats);
    await waitFor(() => expect(button).toBeEnabled());
  });

  it('distinguishes an offline failure from service failure with safe copy', async () => {
    getCorpusStatsMock.mockRejectedValueOnce(
      new TypeError('Failed to fetch https://private-host/status'),
    );
    render(<AdminStatus />);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Check your connection');
    expect(alert).toHaveTextContent('Reconnect, then try again.');
    expect(alert).not.toHaveTextContent('private-host');
  });

  it('ends an unbounded initial load with a distinct timeout and Retry', async () => {
    vi.useFakeTimers();
    getCorpusStatsMock.mockReturnValue(new Promise(() => undefined));
    render(<AdminStatus />);
    await act(async () => Promise.resolve());

    const signal = getCorpusStatsMock.mock.calls[0]?.[0]?.signal as AbortSignal | undefined;
    expect(signal).toBeInstanceOf(AbortSignal);
    expect(signal?.aborted).toBe(false);

    await act(async () => vi.advanceTimersByTimeAsync(10_000));

    expect(signal?.aborted).toBe(true);
    expect(screen.getByRole('alert')).toHaveTextContent('System status is taking too long');
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    expect(screen.queryByLabelText('Loading system status')).not.toBeInTheDocument();
  });
});
