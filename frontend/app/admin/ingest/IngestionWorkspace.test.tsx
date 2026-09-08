import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';

import { IngestionWorkspace } from './IngestionWorkspace';

const pdfFile = (name: string) =>
  new File(['pdf'], name, { type: 'application/pdf', lastModified: 1 });

describe('IngestionWorkspace', () => {
  afterEach(cleanup);

  it('configures the shared dropzone for multiple PDF files', () => {
    render(<IngestionWorkspace />);

    const input = screen.getByLabelText('Choose PDF files');
    expect(input).toHaveAttribute('accept', 'application/pdf');
    expect(input).toHaveAttribute('multiple');
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
});
