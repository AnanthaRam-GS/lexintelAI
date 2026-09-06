import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { UploadDropzone } from './UploadDropzone';

describe('UploadDropzone', () => {
  afterEach(cleanup);

  it('reports the current valid list after browse upload and remove', async () => {
    const onFilesSelected = vi.fn();
    const user = userEvent.setup();
    const pdf = new File(['judgment'], 'judgment.pdf', { type: 'application/pdf' });

    render(<UploadDropzone multiple onFilesSelected={onFilesSelected} />);

    await user.upload(screen.getByLabelText('Choose PDF files'), pdf);

    expect(onFilesSelected).toHaveBeenLastCalledWith([pdf]);
    expect(screen.getByText('judgment.pdf')).toBeVisible();

    await user.click(screen.getByRole('button', { name: 'Remove judgment.pdf' }));

    expect(onFilesSelected).toHaveBeenLastCalledWith([]);
    expect(screen.queryByText('judgment.pdf')).not.toBeInTheDocument();
  });

  it('adds a dropped PDF to the existing list in multiple-file mode', () => {
    const onFilesSelected = vi.fn();
    const first = new File(['one'], 'first.pdf', { type: 'application/pdf' });
    const second = new File(['two'], 'second.pdf', { type: 'application/pdf' });

    render(<UploadDropzone multiple onFilesSelected={onFilesSelected} />);

    fireEvent.drop(screen.getByTestId('upload-dropzone'), { dataTransfer: { files: [first] } });
    fireEvent.drop(screen.getByTestId('upload-dropzone'), { dataTransfer: { files: [second] } });

    expect(onFilesSelected).toHaveBeenLastCalledWith([first, second]);
    expect(screen.getByText('first.pdf')).toBeVisible();
    expect(screen.getByText('second.pdf')).toBeVisible();
  });

  it('replaces the selected file in single-file mode', async () => {
    const onFilesSelected = vi.fn();
    const user = userEvent.setup();
    const first = new File(['one'], 'first.pdf', { type: 'application/pdf' });
    const second = new File(['two'], 'second.pdf', { type: 'application/pdf' });

    render(<UploadDropzone onFilesSelected={onFilesSelected} />);

    await user.upload(screen.getByLabelText('Choose PDF files'), first);
    await user.upload(screen.getByLabelText('Choose PDF files'), second);

    expect(onFilesSelected).toHaveBeenLastCalledWith([second]);
    expect(screen.queryByText('first.pdf')).not.toBeInTheDocument();
    expect(screen.getByText('second.pdf')).toBeVisible();
  });

  it('gives browse and remove controls a tokenized visible-focus treatment', async () => {
    const user = userEvent.setup();
    const pdf = new File(['judgment'], 'judgment.pdf', { type: 'application/pdf' });

    render(<UploadDropzone onFilesSelected={() => undefined} />);

    await user.upload(screen.getByLabelText('Choose PDF files'), pdf);

    [
      screen.getByRole('button', { name: 'Browse files' }),
      screen.getByRole('button', { name: 'Remove judgment.pdf' }),
    ].forEach((control) => {
      expect(control).toHaveClass(
        'focus-visible:outline-[0.1875rem]',
        'focus-visible:outline-[var(--color-focus)]',
        'focus-visible:outline-offset-[0.1875rem]',
      );
    });
  });

  it('uses drag depth to keep the drop state visible until the final leave', () => {
    render(<UploadDropzone onFilesSelected={vi.fn()} />);

    const dropzone = screen.getByTestId('upload-dropzone');
    fireEvent.dragEnter(dropzone);
    fireEvent.dragEnter(dropzone);
    fireEvent.dragLeave(dropzone);

    expect(dropzone).toHaveTextContent('Drop PDF files here');

    fireEvent.dragLeave(dropzone);

    expect(dropzone).toHaveTextContent('Drag & drop PDF files here');
  });

  it('does not add files or enable controls when disabled', async () => {
    const onFilesSelected = vi.fn();
    const user = userEvent.setup();
    const pdf = new File(['judgment'], 'judgment.pdf', { type: 'application/pdf' });

    render(<UploadDropzone disabled onFilesSelected={onFilesSelected} />);

    const input = screen.getByLabelText('Choose PDF files');
    expect(input).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Browse files' })).toBeDisabled();

    await user.upload(input, pdf);
    fireEvent.drop(screen.getByTestId('upload-dropzone'), { dataTransfer: { files: [pdf] } });

    expect(onFilesSelected).not.toHaveBeenCalled();
    expect(screen.queryByText('judgment.pdf')).not.toBeInTheDocument();
  });

  it('reports invalid dropped type and size feedback through an alert', () => {
    const wrong = new File(['x'], 'notes.txt', { type: 'text/plain' });
    const large = new File([new Uint8Array(2_000_000)], 'large.pdf', {
      type: 'application/pdf',
    });

    render(<UploadDropzone maxSizeMB={1} multiple onFilesSelected={vi.fn()} />);

    fireEvent.drop(screen.getByTestId('upload-dropzone'), {
      dataTransfer: { files: [wrong, large] },
    });

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('Unable to add files');
    expect(alert).toHaveTextContent('notes.txt');
    expect(alert).toHaveTextContent('large.pdf');
  });
});
