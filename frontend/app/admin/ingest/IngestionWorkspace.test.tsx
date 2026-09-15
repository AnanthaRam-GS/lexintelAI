import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { IngestionJob } from '../../../components/shared';
import {
  cancelIngestionJobMock,
  pollIngestionStatusMock,
  readPersistedIngestionJobs,
  submitIngestionMock,
  writePersistedIngestionJobs,
} from '../../../lib/mocks/adminIngestion';
import { IngestionWorkspace } from './IngestionWorkspace';

vi.mock('../../../lib/mocks/adminIngestion', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../lib/mocks/adminIngestion')>();
  return {
    ...actual,
    cancelIngestionJobMock: vi.fn(),
    pollIngestionStatusMock: vi.fn(),
    submitIngestionMock: vi.fn(),
  };
});

const pdfFile = (name: string) =>
  new File(['pdf'], name, { type: 'application/pdf', lastModified: 1 });

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

async function configureValidBatch(user: ReturnType<typeof userEvent.setup>, file: File) {
  await user.upload(screen.getByLabelText('Choose PDF files'), file);
  await user.selectOptions(screen.getByLabelText(`Document type for ${file.name}`), 'judgment');
  await user.click(
    screen.getByRole('checkbox', { name: 'I understand this is a permanent corpus update' }),
  );
}

describe('IngestionWorkspace', () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.mocked(pollIngestionStatusMock).mockReset();
    vi.mocked(cancelIngestionJobMock).mockReset();
    vi.mocked(cancelIngestionJobMock).mockResolvedValue(undefined);
    vi.mocked(submitIngestionMock).mockReset();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    sessionStorage.clear();
  });

  it('configures the shared dropzone for multiple PDF files', () => {
    render(<IngestionWorkspace />);

    const input = screen.getByLabelText('Choose PDF files');
    expect(input).toHaveAttribute('accept', 'application/pdf');
    expect(input).toHaveAttribute('multiple');
  });

  it('announces changed job rows through a polite non-atomic log', () => {
    render(<IngestionWorkspace />);

    const updates = screen.getByRole('log', { name: 'Ingestion job updates' });
    expect(updates).toHaveAttribute('aria-live', 'polite');
    expect(updates).toHaveAttribute('aria-atomic', 'false');
    expect(updates).toHaveAttribute('aria-relevant', 'additions text');
  });

  it('renders independent required types and optional notes for every file', async () => {
    const user = userEvent.setup();
    render(<IngestionWorkspace />);

    await user.upload(screen.getByLabelText('Choose PDF files'), [
      pdfFile('first.pdf'),
      pdfFile('second.pdf'),
    ]);

    expect(screen.getByLabelText('Document type for first.pdf')).toBeRequired();
    expect(screen.getByLabelText('Document type for second.pdf')).toBeRequired();
    expect(screen.getByLabelText('Note for first.pdf')).not.toBeRequired();
    expect(screen.getAllByText('first.pdf')).toHaveLength(2);
    expect(screen.getAllByText('second.pdf')).toHaveLength(2);
  });

  it('keeps a long unbroken metadata filename within the narrow card and exposes its full value', async () => {
    const user = userEvent.setup();
    const longFilename = `${'a'.repeat(240)}.pdf`;
    render(<IngestionWorkspace />);

    await user.upload(screen.getByLabelText('Choose PDF files'), pdfFile(longFilename));

    const heading = screen.getByRole('heading', { name: longFilename });
    expect(heading).toHaveAttribute('title', longFilename);
    expect(heading).toHaveClass('truncate');
    expect(heading.closest('article')).toHaveClass('min-w-0');
  });

  it('identifies the exact incomplete filename and prevents the permanent action', async () => {
    const user = userEvent.setup();
    render(<IngestionWorkspace />);
    const complete = pdfFile('complete.pdf');
    const incomplete = pdfFile('incomplete.pdf');

    await user.upload(screen.getByLabelText('Choose PDF files'), [complete, incomplete]);
    await user.selectOptions(screen.getByLabelText('Document type for complete.pdf'), 'judgment');
    await user.click(
      screen.getByRole('checkbox', {
        name: 'I understand this is a permanent corpus update',
      }),
    );

    expect(screen.getByText('Complete document types for: incomplete.pdf')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Start ingestion' })).toBeDisabled();
  });

  it('states the current permanent corpus count and clears confirmation when files are added', async () => {
    const user = userEvent.setup();
    render(<IngestionWorkspace />);

    await user.upload(screen.getByLabelText('Choose PDF files'), pdfFile('first.pdf'));
    expect(
      screen.getByText('1 file will be permanently added to the shared corpus.'),
    ).toBeVisible();

    const confirmation = screen.getByRole('checkbox', {
      name: 'I understand this is a permanent corpus update',
    });
    await user.click(confirmation);
    expect(confirmation).toBeChecked();

    await user.upload(screen.getByLabelText('Choose PDF files'), pdfFile('second.pdf'));

    expect(
      screen.getByText('2 files will be permanently added to the shared corpus.'),
    ).toBeVisible();
    expect(confirmation).not.toBeChecked();
    expect(screen.getByRole('button', { name: 'Start ingestion' })).toBeDisabled();
  });

  it('preserves confirmation and updates the visible count when a file is removed', async () => {
    const user = userEvent.setup();
    render(<IngestionWorkspace />);
    const first = pdfFile('first.pdf');
    const second = pdfFile('second.pdf');

    await user.upload(screen.getByLabelText('Choose PDF files'), [first, second]);
    await user.click(
      screen.getByRole('checkbox', {
        name: 'I understand this is a permanent corpus update',
      }),
    );
    await user.click(screen.getByRole('button', { name: 'Remove second.pdf' }));

    expect(
      screen.getByText('1 file will be permanently added to the shared corpus.'),
    ).toBeVisible();
    expect(
      screen.getByRole('checkbox', { name: 'I understand this is a permanent corpus update' }),
    ).toBeChecked();
  });

  it('enables Start ingestion in the removal render when the only invalid file is removed', async () => {
    const user = userEvent.setup();
    render(<IngestionWorkspace />);
    const complete = pdfFile('complete.pdf');
    const incomplete = pdfFile('incomplete.pdf');

    await user.upload(screen.getByLabelText('Choose PDF files'), [complete, incomplete]);
    await user.selectOptions(screen.getByLabelText('Document type for complete.pdf'), 'judgment');
    await user.click(
      screen.getByRole('checkbox', {
        name: 'I understand this is a permanent corpus update',
      }),
    );

    const start = screen.getByRole('button', { name: 'Start ingestion' });
    expect(start).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Remove incomplete.pdf' }));
    expect(start).toBeEnabled();
  });

  it('submits aligned files and metadata, inserts newest first, and clears only after success', async () => {
    const user = userEvent.setup();
    vi.mocked(submitIngestionMock).mockResolvedValue({ jobIds: ['job-a', 'job-b'] });
    vi.mocked(pollIngestionStatusMock).mockImplementation(async (id) => ({
      id,
      filename: id === 'job-a' ? 'a.pdf' : 'b.pdf',
      stage: 'QUEUED',
      progress: 0,
    }));
    render(<IngestionWorkspace />);
    const files = [
      new File(['PRIVATE_FILE_CONTENT'], 'a.pdf', { type: 'application/pdf' }),
      pdfFile('b.pdf'),
    ];

    await user.upload(screen.getByLabelText('Choose PDF files'), files);
    await user.selectOptions(screen.getByLabelText('Document type for a.pdf'), 'judgment');
    await user.selectOptions(screen.getByLabelText('Document type for b.pdf'), 'statute');
    await user.type(screen.getByLabelText('Note for b.pdf'), 'Second item');
    await user.click(
      screen.getByRole('checkbox', { name: 'I understand this is a permanent corpus update' }),
    );
    await user.click(screen.getByRole('button', { name: 'Start ingestion' }));

    expect(submitIngestionMock).toHaveBeenCalledWith(
      files,
      [
        { documentType: 'judgment', note: undefined },
        { documentType: 'statute', note: 'Second item' },
      ],
      { signal: expect.any(AbortSignal) },
    );
    expect(await screen.findByText('a.pdf')).toBeInTheDocument();
    expect(screen.queryByLabelText('Document type for a.pdf')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Remove a.pdf' })).not.toBeInTheDocument();
    const rows = within(screen.getByTestId('ingestion-jobs')).getAllByRole('listitem');
    expect(rows[0]).toHaveTextContent('b.pdf');
    expect(rows[1]).toHaveTextContent('a.pdf');
    expect(pollIngestionStatusMock).toHaveBeenCalledWith('job-a', {
      signal: expect.any(AbortSignal),
    });
    expect(pollIngestionStatusMock).toHaveBeenCalledWith('job-b', {
      signal: expect.any(AbortSignal),
    });

    const storageKey = sessionStorage.key(0);
    expect(storageKey).not.toBeNull();
    const serialized = sessionStorage.getItem(storageKey!);
    expect(serialized).not.toContain('PRIVATE_FILE_CONTENT');
    expect(serialized).not.toContain('Second item');
    expect(serialized).not.toContain('documentType');
  });

  it('disables batch controls while a submission is pending', async () => {
    const user = userEvent.setup();
    const pending = deferred<{ jobIds: string[] }>();
    vi.mocked(submitIngestionMock).mockReturnValue(pending.promise);
    render(<IngestionWorkspace />);
    await configureValidBatch(user, pdfFile('pending.pdf'));

    await user.click(screen.getByRole('button', { name: 'Start ingestion' }));

    await waitFor(() => expect(screen.getByLabelText('Choose PDF files')).toBeDisabled());
    expect(screen.getByLabelText('Document type for pending.pdf')).toBeDisabled();
    expect(screen.getByLabelText('Note for pending.pdf')).toBeDisabled();
    expect(
      screen.getByRole('checkbox', { name: 'I understand this is a permanent corpus update' }),
    ).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Start ingestion' })).toBeDisabled();

    pending.reject(new Error('end pending request'));
    expect(await screen.findByRole('alert')).toHaveTextContent('was not started');
  });

  it('aborts a submission that exceeds the start deadline and retains the batch', async () => {
    const user = userEvent.setup();
    vi.mocked(submitIngestionMock).mockReturnValue(new Promise(() => undefined));
    render(<IngestionWorkspace />);
    await configureValidBatch(user, pdfFile('slow-submit.pdf'));

    vi.useFakeTimers();
    screen.getByRole('button', { name: 'Start ingestion' }).click();
    await act(async () => Promise.resolve());

    const signal = vi.mocked(submitIngestionMock).mock.calls[0]?.[2]?.signal;
    expect(signal).toBeInstanceOf(AbortSignal);
    expect(signal?.aborted).toBe(false);

    await act(async () => vi.advanceTimersByTimeAsync(10_000));

    expect(signal?.aborted).toBe(true);
    expect(screen.getByRole('alert')).toHaveTextContent('taking too long to start');
    expect(screen.getByLabelText('Document type for slow-submit.pdf')).toBeInTheDocument();
    expect(screen.queryByTestId('ingestion-jobs')).not.toBeInTheDocument();
  });

  it('retains the batch and hides private rejection details after submit failure', async () => {
    const user = userEvent.setup();
    vi.mocked(submitIngestionMock).mockRejectedValue(
      new Error('s3://private-bucket/backend-stack'),
    );
    render(<IngestionWorkspace />);
    await configureValidBatch(user, pdfFile('retry.pdf'));

    await user.click(screen.getByRole('button', { name: 'Start ingestion' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('was not started');
    expect(screen.getByLabelText('Document type for retry.pdf')).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('private-bucket');
  });

  it('retains the batch when the submission response is not aligned', async () => {
    const user = userEvent.setup();
    vi.mocked(submitIngestionMock).mockResolvedValue({ jobIds: [] });
    render(<IngestionWorkspace />);
    await configureValidBatch(user, pdfFile('unaligned.pdf'));

    await user.click(screen.getByRole('button', { name: 'Start ingestion' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('was not started');
    expect(screen.getByLabelText('Document type for unaligned.pdf')).toBeInTheDocument();
    expect(screen.queryByTestId('ingestion-jobs')).not.toBeInTheDocument();
  });

  it('disables a batch larger than the active-job capacity and explains the remaining slots', async () => {
    const user = userEvent.setup();
    const files = Array.from({ length: 26 }, (_, index) => pdfFile(`batch-${index + 1}.pdf`));
    render(<IngestionWorkspace />);

    await user.upload(screen.getByLabelText('Choose PDF files'), files);

    expect(
      screen.getByText(
        'This batch exceeds the active ingestion capacity. Remove 1 file; 25 job slots remain.',
      ),
    ).toBeVisible();
    expect(screen.getByRole('button', { name: 'Start ingestion' })).toBeDisabled();
    expect(submitIngestionMock).not.toHaveBeenCalled();
  });

  it('counts restored active jobs when deciding whether a complete batch can start', async () => {
    const user = userEvent.setup();
    writePersistedIngestionJobs(
      Array.from({ length: 24 }, (_, index) => ({
        id: `job-${index + 1}`,
        filename: `active-${index + 1}.pdf`,
        stage: 'CHUNKING' as const,
      })),
    );
    vi.mocked(pollIngestionStatusMock).mockReturnValue(new Promise(() => undefined));
    render(<IngestionWorkspace />);
    const files = [pdfFile('new-a.pdf'), pdfFile('new-b.pdf')];

    await user.upload(screen.getByLabelText('Choose PDF files'), files);
    await user.selectOptions(screen.getByLabelText('Document type for new-a.pdf'), 'judgment');
    await user.selectOptions(screen.getByLabelText('Document type for new-b.pdf'), 'statute');
    await user.click(
      screen.getByRole('checkbox', { name: 'I understand this is a permanent corpus update' }),
    );

    expect(
      screen.getByText(
        'This batch exceeds the active ingestion capacity. Remove 1 file; 1 job slot remains.',
      ),
    ).toBeVisible();
    expect(screen.getByRole('button', { name: 'Start ingestion' })).toBeDisabled();
    expect(submitIngestionMock).not.toHaveBeenCalled();
  });

  it('persists every accepted job when a batch exactly fills the remaining capacity', async () => {
    const user = userEvent.setup();
    writePersistedIngestionJobs(
      Array.from({ length: 24 }, (_, index) => ({
        id: `job-${index + 1}`,
        filename: `active-${index + 1}.pdf`,
        stage: 'CHUNKING' as const,
      })),
    );
    vi.mocked(pollIngestionStatusMock).mockReturnValue(new Promise(() => undefined));
    vi.mocked(submitIngestionMock).mockResolvedValue({ jobIds: ['job-25'] });
    render(<IngestionWorkspace />);
    await configureValidBatch(user, pdfFile('new.pdf'));

    const start = screen.getByRole('button', { name: 'Start ingestion' });
    expect(start).toBeEnabled();
    await user.click(start);

    await waitFor(() => expect(readPersistedIngestionJobs()).toHaveLength(25));
    expect(readPersistedIngestionJobs().map(({ id }) => id)).toEqual([
      'job-25',
      ...Array.from({ length: 24 }, (_, index) => `job-${index + 1}`),
    ]);
  });

  it('does not count terminal jobs retained on the mounted screen against active capacity', async () => {
    const user = userEvent.setup();
    writePersistedIngestionJobs(
      Array.from({ length: 25 }, (_, index) => ({
        id: `job-${index + 1}`,
        filename: `finished-${index + 1}.pdf`,
        stage: 'INDEXING' as const,
      })),
    );
    vi.mocked(pollIngestionStatusMock).mockImplementation(async (id) => ({
      id,
      filename: `finished-${id.slice(4)}.pdf`,
      stage: 'COMPLETED',
      progress: 100,
    }));
    render(<IngestionWorkspace />);
    await waitFor(() => expect(readPersistedIngestionJobs()).toEqual([]));

    await configureValidBatch(user, pdfFile('new.pdf'));

    expect(screen.queryByText(/exceeds the active ingestion capacity/i)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start ingestion' })).toBeEnabled();
  });

  it('rejects a submission response whose job ID collides with a restored job', async () => {
    const user = userEvent.setup();
    writePersistedIngestionJobs([{ id: 'job-1', filename: 'restored.pdf', stage: 'CHUNKING' }]);
    vi.mocked(pollIngestionStatusMock).mockReturnValue(new Promise(() => undefined));
    vi.mocked(submitIngestionMock).mockResolvedValue({ jobIds: ['job-1'] });
    render(<IngestionWorkspace />);
    await configureValidBatch(user, pdfFile('new.pdf'));

    await user.click(screen.getByRole('button', { name: 'Start ingestion' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('was not started');
    expect(screen.getByLabelText('Document type for new.pdf')).toBeInTheDocument();
    const rows = within(screen.getByTestId('ingestion-jobs')).getAllByRole('listitem');
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent('restored.pdf');
  });

  it('keeps restored and newly submitted jobs unique, independently polled, and stably ordered', async () => {
    const user = userEvent.setup();
    const restoredPoll = deferred<IngestionJob>();
    const newPoll = deferred<IngestionJob>();
    writePersistedIngestionJobs([{ id: 'job-1', filename: 'restored.pdf', stage: 'CHUNKING' }]);
    vi.mocked(submitIngestionMock).mockResolvedValue({ jobIds: ['job-2'] });
    vi.mocked(pollIngestionStatusMock).mockImplementation((id) =>
      id === 'job-1' ? restoredPoll.promise : newPoll.promise,
    );
    render(<IngestionWorkspace />);
    await configureValidBatch(user, pdfFile('new.pdf'));

    await user.click(screen.getByRole('button', { name: 'Start ingestion' }));

    expect(pollIngestionStatusMock).toHaveBeenCalledWith('job-1', {
      signal: expect.any(AbortSignal),
    });
    expect(pollIngestionStatusMock).toHaveBeenCalledWith('job-2', {
      signal: expect.any(AbortSignal),
    });
    const rows = within(screen.getByTestId('ingestion-jobs')).getAllByRole('listitem');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('new.pdf');
    expect(rows[1]).toHaveTextContent('restored.pdf');

    restoredPoll.resolve({
      id: 'job-1',
      filename: 'restored.pdf',
      stage: 'EXTRACTING',
      progress: 20,
    });
    newPoll.resolve({
      id: 'job-2',
      filename: 'new.pdf',
      stage: 'EXTRACTING',
      progress: 20,
    });
    await act(async () => Promise.resolve());
    const updatedRows = within(screen.getByTestId('ingestion-jobs')).getAllByRole('listitem');
    expect(updatedRows[0]).toHaveTextContent('new.pdf');
    expect(updatedRows[1]).toHaveTextContent('restored.pdf');
  });

  it('polls jobs independently every 2.5 seconds and stops each terminal job', async () => {
    vi.useFakeTimers();
    writePersistedIngestionJobs([
      { id: 'job-a', filename: 'a.pdf', stage: 'QUEUED' },
      { id: 'job-b', filename: 'b.pdf', stage: 'EXTRACTING' },
    ]);
    vi.mocked(pollIngestionStatusMock)
      .mockResolvedValueOnce({
        id: 'job-a',
        filename: 'a.pdf',
        stage: 'COMPLETED',
        progress: 100,
      })
      .mockResolvedValueOnce({
        id: 'job-b',
        filename: 'b.pdf',
        stage: 'CHUNKING',
        progress: 40,
      })
      .mockResolvedValueOnce({
        id: 'job-b',
        filename: 'b.pdf',
        stage: 'FAILED',
        progress: 40,
      });

    render(<IngestionWorkspace />);
    await act(async () => Promise.resolve());
    expect(pollIngestionStatusMock).toHaveBeenCalledTimes(2);

    await act(async () => vi.advanceTimersByTimeAsync(2_500));
    expect(pollIngestionStatusMock).toHaveBeenCalledTimes(3);
    expect(vi.mocked(pollIngestionStatusMock).mock.calls[2]?.[0]).toBe('job-b');
    expect(vi.mocked(pollIngestionStatusMock).mock.calls[2]?.[1]?.signal).toBeInstanceOf(
      AbortSignal,
    );
    await act(async () => vi.advanceTimersByTimeAsync(5_000));
    expect(pollIngestionStatusMock).toHaveBeenCalledTimes(3);
    expect(readPersistedIngestionJobs()).toEqual([]);
  });

  it('caps adversarial session rehydration before it can fan out polling', async () => {
    sessionStorage.setItem(
      'legalai-admin-ingestion-jobs',
      JSON.stringify([
        ...Array.from({ length: 40 }, (_, index) => ({
          id: `job-${index + 1}`,
          filename: `document-${index + 1}.pdf`,
          stage: 'QUEUED',
        })),
        { id: `job-${'x'.repeat(200)}`, filename: 'oversized-id.pdf', stage: 'QUEUED' },
        { id: 'job-oversized-name', filename: `${'x'.repeat(300)}.pdf`, stage: 'QUEUED' },
      ]),
    );
    vi.mocked(pollIngestionStatusMock).mockReturnValue(new Promise(() => undefined));

    render(<IngestionWorkspace />);

    await waitFor(() => expect(pollIngestionStatusMock).toHaveBeenCalledTimes(25));
    expect(vi.mocked(pollIngestionStatusMock).mock.calls.map(([id]) => id)).toEqual(
      Array.from({ length: 25 }, (_, index) => `job-${index + 1}`),
    );
    expect(JSON.parse(sessionStorage.getItem('legalai-admin-ingestion-jobs')!)).toHaveLength(25);
  });

  it('waits for an in-flight poll to settle before scheduling the next poll', async () => {
    vi.useFakeTimers();
    writePersistedIngestionJobs([{ id: 'job-1', filename: 'lease.pdf', stage: 'QUEUED' }]);
    const firstPoll = deferred<IngestionJob>();
    vi.mocked(pollIngestionStatusMock)
      .mockReturnValueOnce(firstPoll.promise)
      .mockResolvedValueOnce({
        id: 'job-1',
        filename: 'lease.pdf',
        stage: 'CHUNKING',
        progress: 40,
      });
    render(<IngestionWorkspace />);

    await act(async () => vi.advanceTimersByTimeAsync(10_000));
    expect(pollIngestionStatusMock).toHaveBeenCalledTimes(1);

    firstPoll.resolve({
      id: 'job-1',
      filename: 'lease.pdf',
      stage: 'EXTRACTING',
      progress: 20,
    });
    await act(async () => Promise.resolve());
    await act(async () => vi.advanceTimersByTimeAsync(2_499));
    expect(pollIngestionStatusMock).toHaveBeenCalledTimes(1);
    await act(async () => vi.advanceTimersByTimeAsync(1));
    expect(pollIngestionStatusMock).toHaveBeenCalledTimes(2);
  });

  it('clears a scheduled poll timer on unmount', async () => {
    vi.useFakeTimers();
    writePersistedIngestionJobs([{ id: 'job-1', filename: 'lease.pdf', stage: 'QUEUED' }]);
    vi.mocked(pollIngestionStatusMock).mockResolvedValue({
      id: 'job-1',
      filename: 'lease.pdf',
      stage: 'EXTRACTING',
      progress: 20,
    });
    const view = render(<IngestionWorkspace />);
    await act(async () => Promise.resolve());
    expect(vi.getTimerCount()).toBe(2);

    view.unmount();
    expect(vi.getTimerCount()).toBe(0);
    await act(async () => vi.advanceTimersByTimeAsync(5_000));
    expect(pollIngestionStatusMock).toHaveBeenCalledTimes(1);
  });

  it('does not apply or reschedule a poll that settles after unmount', async () => {
    vi.useFakeTimers();
    writePersistedIngestionJobs([{ id: 'job-1', filename: 'lease.pdf', stage: 'CHUNKING' }]);
    const live = deferred<IngestionJob>();
    vi.mocked(pollIngestionStatusMock).mockReturnValue(live.promise);
    const view = render(<IngestionWorkspace />);
    expect(pollIngestionStatusMock).toHaveBeenCalledWith('job-1', {
      signal: expect.any(AbortSignal),
    });

    view.unmount();
    live.resolve({
      id: 'job-1',
      filename: 'changed.pdf',
      stage: 'EMBEDDING',
      progress: 60,
    });
    await act(async () => Promise.resolve());
    await act(async () => vi.advanceTimersByTimeAsync(5_000));

    expect(pollIngestionStatusMock).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
    expect(readPersistedIngestionJobs()).toEqual([
      { id: 'job-1', filename: 'lease.pdf', stage: 'CHUNKING' },
    ]);
  });

  it('keeps job order stable when independent poll responses settle out of order', async () => {
    writePersistedIngestionJobs([
      { id: 'job-new', filename: 'new.pdf', stage: 'QUEUED' },
      { id: 'job-old', filename: 'old.pdf', stage: 'EXTRACTING' },
    ]);
    const newest = deferred<IngestionJob>();
    const oldest = deferred<IngestionJob>();
    vi.mocked(pollIngestionStatusMock).mockImplementation((id) =>
      id === 'job-new' ? newest.promise : oldest.promise,
    );
    render(<IngestionWorkspace />);

    oldest.resolve({
      id: 'job-old',
      filename: 'old.pdf',
      stage: 'CHUNKING',
      progress: 40,
    });
    await act(async () => Promise.resolve());
    newest.resolve({
      id: 'job-new',
      filename: 'new.pdf',
      stage: 'EXTRACTING',
      progress: 20,
    });
    await act(async () => Promise.resolve());

    const rows = within(screen.getByTestId('ingestion-jobs')).getAllByRole('listitem');
    expect(rows[0]).toHaveTextContent('new.pdf');
    expect(rows[1]).toHaveTextContent('old.pdf');
  });

  it('renders a minimal placeholder, immediately refreshes truth, and forgets terminal storage', async () => {
    writePersistedIngestionJobs([{ id: 'job-1', filename: 'lease.pdf', stage: 'CHUNKING' }]);
    const live = deferred<IngestionJob>();
    vi.mocked(pollIngestionStatusMock).mockReturnValue(live.promise);

    const view = render(<IngestionWorkspace />);
    expect(screen.getByText('lease.pdf')).toBeInTheDocument();
    expect(screen.getByRole('progressbar', { name: 'lease.pdf progress' })).toHaveAttribute(
      'aria-valuenow',
      '40',
    );
    expect(pollIngestionStatusMock).toHaveBeenCalledWith('job-1', {
      signal: expect.any(AbortSignal),
    });
    const storageKey = sessionStorage.key(0);
    expect(storageKey).not.toBeNull();
    const serialized = sessionStorage.getItem(storageKey!);
    expect(serialized).not.toContain('progress');
    expect(serialized).not.toContain('error');
    expect(serialized).not.toContain('note');
    expect(serialized).not.toContain('documentType');
    expect(serialized).not.toContain('PRIVATE_FILE_CONTENT');

    live.resolve({ id: 'job-1', filename: 'lease.pdf', stage: 'COMPLETED', progress: 100 });
    expect(await screen.findByText('COMPLETED')).toBeInTheDocument();
    expect(readPersistedIngestionJobs()).toEqual([]);
    expect(screen.getByText('lease.pdf')).toBeInTheDocument();

    view.unmount();
    vi.mocked(pollIngestionStatusMock).mockReset();
    render(<IngestionWorkspace />);
    expect(screen.queryByText('lease.pdf')).not.toBeInTheDocument();
  });

  it('keeps an active job visible and retries after network loss without leaking details', async () => {
    vi.useFakeTimers();
    writePersistedIngestionJobs([{ id: 'job-1', filename: 'lease.pdf', stage: 'INDEXING' }]);
    vi.mocked(pollIngestionStatusMock)
      .mockRejectedValueOnce(new TypeError('s3://private-bucket/internal-stack'))
      .mockResolvedValueOnce({
        id: 'job-1',
        filename: 'lease.pdf',
        stage: 'COMPLETED',
        progress: 100,
      });
    render(<IngestionWorkspace />);
    await act(async () => Promise.resolve());

    expect(screen.getByRole('alert')).toHaveTextContent('Check your connection');
    expect(screen.getByText('INDEXING')).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('private-bucket');
    expect(readPersistedIngestionJobs()).toEqual([
      { id: 'job-1', filename: 'lease.pdf', stage: 'INDEXING' },
    ]);

    await act(async () => vi.advanceTimersByTimeAsync(2_500));
    expect(screen.getByText('COMPLETED')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(readPersistedIngestionJobs()).toEqual([]);
  });

  it('fails only a stalled job at the bounded deadline with actionable timeout copy', async () => {
    vi.useFakeTimers();
    writePersistedIngestionJobs([{ id: 'job-1', filename: 'slow.pdf', stage: 'EXTRACTING' }]);
    vi.mocked(pollIngestionStatusMock).mockReturnValue(new Promise(() => undefined));

    render(<IngestionWorkspace />);
    const signal = vi.mocked(pollIngestionStatusMock).mock.calls[0]?.[1]?.signal;
    expect(signal).toBeInstanceOf(AbortSignal);
    expect(signal?.aborted).toBe(false);
    await act(async () => vi.advanceTimersByTimeAsync(15_000));

    expect(signal?.aborted).toBe(true);
    expect(cancelIngestionJobMock).toHaveBeenCalledWith('job-1');
    expect(screen.getByText('FAILED')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Processing took too long.');
    expect(screen.getByRole('alert')).toHaveTextContent('add it again in a new batch');
    expect(readPersistedIngestionJobs()).toEqual([]);
  });

  it('removes acknowledged cancellation persistence even when the route unmounts first', async () => {
    vi.useFakeTimers();
    const cancellation = deferred<void>();
    writePersistedIngestionJobs([{ id: 'job-1', filename: 'slow.pdf', stage: 'EXTRACTING' }]);
    vi.mocked(pollIngestionStatusMock).mockReturnValue(new Promise(() => undefined));
    vi.mocked(cancelIngestionJobMock).mockReturnValue(cancellation.promise);
    const view = render(<IngestionWorkspace />);

    await act(async () => vi.advanceTimersByTimeAsync(15_000));
    expect(cancelIngestionJobMock).toHaveBeenCalledWith('job-1');
    view.unmount();
    cancellation.resolve();
    await act(async () => Promise.resolve());

    expect(readPersistedIngestionJobs()).toEqual([]);
    vi.mocked(pollIngestionStatusMock).mockReset();
    vi.mocked(pollIngestionStatusMock).mockReturnValue(new Promise(() => undefined));
    render(<IngestionWorkspace />);
    expect(pollIngestionStatusMock).not.toHaveBeenCalled();
  });

  it('uses progress inactivity rather than total elapsed time as the job deadline', async () => {
    vi.useFakeTimers();
    const stages: IngestionJob[] = [
      { id: 'job-1', filename: 'slow.pdf', stage: 'EXTRACTING', progress: 20 },
      { id: 'job-1', filename: 'slow.pdf', stage: 'CHUNKING', progress: 40 },
      { id: 'job-1', filename: 'slow.pdf', stage: 'EMBEDDING', progress: 60 },
      { id: 'job-1', filename: 'slow.pdf', stage: 'INDEXING', progress: 80 },
      { id: 'job-1', filename: 'slow.pdf', stage: 'COMPLETED', progress: 100 },
    ];
    writePersistedIngestionJobs([{ id: 'job-1', filename: 'slow.pdf', stage: 'QUEUED' }]);
    vi.mocked(pollIngestionStatusMock).mockImplementation(async () => {
      await new Promise<void>((resolve) => setTimeout(resolve, 2_000));
      return stages.shift()!;
    });

    render(<IngestionWorkspace />);
    await act(async () => vi.advanceTimersByTimeAsync(21_000));

    expect(screen.getByText('COMPLETED')).toBeInTheDocument();
    expect(cancelIngestionJobMock).not.toHaveBeenCalled();
  });

  it('uses the first live poll as truth when restored placeholder progress is ahead', async () => {
    vi.useFakeTimers();
    const stages: IngestionJob[] = [
      { id: 'job-1', filename: 'restored.pdf', stage: 'EXTRACTING', progress: 20 },
      { id: 'job-1', filename: 'restored.pdf', stage: 'CHUNKING', progress: 40 },
      { id: 'job-1', filename: 'restored.pdf', stage: 'EMBEDDING', progress: 60 },
      { id: 'job-1', filename: 'restored.pdf', stage: 'INDEXING', progress: 80 },
      { id: 'job-1', filename: 'restored.pdf', stage: 'COMPLETED', progress: 100 },
    ];
    writePersistedIngestionJobs([{ id: 'job-1', filename: 'restored.pdf', stage: 'INDEXING' }]);
    vi.mocked(pollIngestionStatusMock).mockImplementation(async () => {
      await new Promise<void>((resolve) => setTimeout(resolve, 2_000));
      return stages.shift()!;
    });

    render(<IngestionWorkspace />);
    await act(async () => vi.advanceTimersByTimeAsync(21_000));

    expect(screen.getByText('COMPLETED')).toBeInTheDocument();
    expect(cancelIngestionJobMock).not.toHaveBeenCalled();
    expect(readPersistedIngestionJobs()).toEqual([]);
  });

  it('keeps two completed files clear when one file in a submitted batch of three fails', async () => {
    const user = userEvent.setup();
    const files = [pdfFile('first.pdf'), pdfFile('damaged.pdf'), pdfFile('third.pdf')];
    vi.mocked(submitIngestionMock).mockResolvedValue({
      jobIds: ['job-first', 'job-damaged', 'job-third'],
    });
    vi.mocked(pollIngestionStatusMock).mockImplementation(async (id) => {
      const filename =
        id === 'job-first' ? 'first.pdf' : id === 'job-third' ? 'third.pdf' : 'damaged.pdf';
      return id === 'job-damaged'
        ? { id, filename, stage: 'FAILED', progress: 100, error: 'corrupted' }
        : { id, filename, stage: 'COMPLETED', progress: 100 };
    });

    render(<IngestionWorkspace />);
    await user.upload(screen.getByLabelText('Choose PDF files'), files);
    for (const file of files) {
      await user.selectOptions(screen.getByLabelText(`Document type for ${file.name}`), 'judgment');
    }
    await user.click(
      screen.getByRole('checkbox', { name: 'I understand this is a permanent corpus update' }),
    );
    await user.click(screen.getByRole('button', { name: 'Start ingestion' }));

    expect(await screen.findAllByText('COMPLETED')).toHaveLength(2);
    expect(screen.getByText('FAILED')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('The PDF may be damaged.');
    expect(screen.getByRole('alert')).toHaveTextContent('add a working copy');
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(3);
    expect(screen.getByText('first.pdf')).toBeInTheDocument();
    expect(screen.getByText('third.pdf')).toBeInTheDocument();
  });
});
