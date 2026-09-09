import { describe, expect, it } from 'vitest';

import { formatFileSize, validateFiles } from './file-validation';

describe('file validation', () => {
  it('rejects a non-PDF and an oversized PDF with actionable messages', () => {
    const wrong = new File(['x'], 'notes.txt', { type: 'text/plain' });
    const large = new File([new Uint8Array(2_000_000)], 'large.pdf', {
      type: 'application/pdf',
    });

    const result = validateFiles([wrong, large], {
      accept: 'application/pdf,.pdf',
      maxSizeMB: 1,
      multiple: true,
    });

    expect(result.valid).toHaveLength(0);
    expect(result.errors).toEqual([
      'notes.txt cannot be added. Choose a PDF file.',
      'large.pdf is too large. Choose a file that is 1 MB or smaller.',
    ]);
  });

  it('accepts a PDF extension when the browser supplies no MIME type', () => {
    const pdfWithoutMime = new File(['judgment'], 'judgment.PDF', { type: '' });

    const result = validateFiles([pdfWithoutMime], {
      accept: 'application/pdf,.pdf',
      maxSizeMB: 10,
      multiple: false,
    });

    expect(result).toEqual({ errors: [], valid: [pdfWithoutMime] });
  });

  it('deduplicates matching file identities and retains only one file in single mode', () => {
    const first = new File(['a'], 'first.pdf', {
      lastModified: 1,
      type: 'application/pdf',
    });
    const duplicate = new File(['a'], 'first.pdf', {
      lastModified: 1,
      type: 'application/pdf',
    });
    const second = new File(['b'], 'second.pdf', {
      lastModified: 2,
      type: 'application/pdf',
    });

    const result = validateFiles([first, duplicate, second], {
      accept: 'application/pdf,.pdf',
      maxSizeMB: 10,
      multiple: false,
    });

    expect(result).toEqual({ errors: [], valid: [first] });
  });

  it('formats bytes into compact user-facing units', () => {
    expect(formatFileSize(0)).toBe('0 B');
    expect(formatFileSize(1_536)).toBe('1.5 KB');
    expect(formatFileSize(1_048_576)).toBe('1 MB');
  });
});
