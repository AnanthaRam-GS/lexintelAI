import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { fetchCorpusStatsMock } = vi.hoisted(() => ({
  fetchCorpusStatsMock: vi.fn(),
}));

vi.mock('../../lib/mocks/adminIngestion', () => ({ fetchCorpusStatsMock }));

import type { CorpusStats } from '../../lib/mocks/adminIngestion';

import { AdminStatus } from './AdminStatus';

const healthyStats: CorpusStats = {
  totalDocuments: 42,
  lastUpdatedTimestamp: '2026-09-08T09:00:00.000Z',
  lastIngestionDate: '2026-09-07T09:00:00.000Z',
  breakdown: { judgment: 20, statute: 12, other: 10 },
  chromaDb: { status: 'healthy', detail: 'Available' },
  postgresql: { status: 'healthy', detail: 'Available' },
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
    fetchCorpusStatsMock.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it('renders four status regions with corpus detail and icon-and-text service health', async () => {
    fetchCorpusStatsMock.mockResolvedValue(healthyStats);
    render(<AdminStatus />);

    expect(screen.getByLabelText('Loading system status')).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Corpus' })).toBeInTheDocument();
    expect(screen.getByText('42 documents')).toBeInTheDocument();
    expect(screen.getByText('Judgments: 20')).toBeInTheDocument();
    expect(screen.getByText('Statutes: 12')).toBeInTheDocument();
    expect(screen.getByText('Other: 10')).toBeInTheDocument();
    expect(screen.getByText('Last ingestion: 2026-09-07T09:00:00.000Z')).toBeInTheDocument();
    expect(screen.getByText('Last updated: 2026-09-08T09:00:00.000Z')).toBeInTheDocument();

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

  it('uses written labels and icons for degraded and down services', async () => {
    fetchCorpusStatsMock.mockResolvedValue({
      ...healthyStats,
      chromaDb: { status: 'degraded', detail: 'Reduced availability' },
      postgresql: { status: 'down', detail: 'Unavailable' },
    });
    render(<AdminStatus />);

    const chroma = await screen.findByRole('region', { name: 'ChromaDB status' });
    expect(within(chroma).getByText('Degraded')).toBeInTheDocument();
    expect(chroma.querySelector('svg')).not.toBeNull();
    const postgres = screen.getByRole('region', { name: 'PostgreSQL status' });
    expect(within(postgres).getByText('Down')).toBeInTheDocument();
    expect(postgres.querySelector('svg')).not.toBeNull();
  });

  it('retries with fixed safe copy and never renders a rejection or technical detail', async () => {
    const user = userEvent.setup();
    const error = Object.assign(new Error('postgresql://private-host secret-stack'), {
      technicalDetail: 'private schema, credentials, and stack trace',
    });
    fetchCorpusStatsMock.mockRejectedValueOnce(error).mockResolvedValueOnce(healthyStats);
    render(<AdminStatus />);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('System status could not be loaded. Try again.');
    expect(alert).not.toHaveTextContent('private-host');
    expect(alert).not.toHaveTextContent('private schema');
    expect(screen.queryByText('Technical details')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByRole('heading', { name: 'Corpus' })).toBeInTheDocument();
  });

  it('does not overlap refresh requests', async () => {
    const user = userEvent.setup();
    const refresh = deferred<CorpusStats>();
    fetchCorpusStatsMock.mockResolvedValueOnce(healthyStats).mockReturnValueOnce(refresh.promise);
    render(<AdminStatus />);

    await screen.findByRole('heading', { name: 'Corpus' });
    const button = screen.getByRole('button', { name: 'Refresh status' });
    await user.click(button);
    expect(button).toBeDisabled();
    await user.click(button);
    expect(fetchCorpusStatsMock).toHaveBeenCalledTimes(2);
    refresh.resolve(healthyStats);
    await waitFor(() => expect(button).toBeEnabled());
  });
});
