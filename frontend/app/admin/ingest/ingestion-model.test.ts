import { describe, expect, it } from 'vitest';

import {
  canSubmitBatch,
  isBatchValid,
  isTerminal,
  markJobFailedSafely,
  reconcileDrafts,
  replaceJobById,
  type IngestionDraft,
} from './ingestion-model';

const pdfFile = (name: string) =>
  new File(['pdf'], name, { type: 'application/pdf', lastModified: 1 });

const makeDraft = (overrides: Partial<IngestionDraft> = {}): IngestionDraft => ({
  id: 'draft-1',
  file: pdfFile('default.pdf'),
  documentType: '',
  note: '',
  ...overrides,
});

describe('ingestion draft model', () => {
  it('keeps same-named distinct File objects as independent drafts', () => {
    const first = pdfFile('duplicate.pdf');
    const second = pdfFile('duplicate.pdf');

    const drafts = reconcileDrafts([], [first, second], () => crypto.randomUUID());

    expect(drafts).toHaveLength(2);
    expect(drafts.map((draft) => draft.file)).toEqual([first, second]);
    expect(new Set(drafts.map((draft) => draft.id)).size).toBe(2);
  });

  it('retains metadata for an unchanged File object', () => {
    const file = pdfFile('kept.pdf');
    const prior = makeDraft({
      id: 'kept-draft',
      file,
      documentType: 'statute',
      note: 'Verified against the original.',
    });

    expect(reconcileDrafts([prior], [file], () => 'new-draft')).toEqual([prior]);
  });

  it('removes metadata for files no longer in the selected list', () => {
    const kept = pdfFile('kept.pdf');
    const removed = pdfFile('removed.pdf');
    const previous = [
      makeDraft({ id: 'kept-draft', file: kept, documentType: 'judgment' }),
      makeDraft({ id: 'removed-draft', file: removed, documentType: 'other', note: 'Remove me' }),
    ];

    expect(reconcileDrafts(previous, [kept], () => 'new-draft')).toEqual([previous[0]]);
  });

  it('requires at least one draft and a document type for every draft', () => {
    expect(isBatchValid([])).toBe(false);
    expect(isBatchValid([makeDraft()])).toBe(false);
    expect(isBatchValid([makeDraft({ documentType: 'judgment' })])).toBe(true);
  });

  it('blocks submission until a valid batch is confirmed and not pending', () => {
    const valid = makeDraft({ documentType: 'judgment' });

    expect(canSubmitBatch([valid], false, false)).toBe(false);
    expect(canSubmitBatch([valid], true, true)).toBe(false);
    expect(canSubmitBatch([valid], true, false)).toBe(true);
  });

  it('becomes eligible immediately after removing the only invalid draft', () => {
    const valid = makeDraft({ id: 'valid', documentType: 'judgment' });
    const invalid = makeDraft({ id: 'invalid', documentType: '' });

    expect(canSubmitBatch([valid, invalid], true, false)).toBe(false);
    const remaining = [valid, invalid].filter((draft) => draft.id !== invalid.id);
    expect(canSubmitBatch(remaining, true, false)).toBe(true);
  });

  it('replaces a polled job by ID without changing newest-first order', () => {
    const jobs = [
      { id: 'job-new', filename: 'new.pdf', stage: 'QUEUED' as const, progress: 0 },
      { id: 'job-old', filename: 'old.pdf', stage: 'EXTRACTING' as const, progress: 20 },
    ];

    expect(
      replaceJobById(jobs, {
        id: 'job-old',
        filename: 'old.pdf',
        stage: 'CHUNKING',
        progress: 40,
      }),
    ).toEqual([
      { id: 'job-new', filename: 'new.pdf', stage: 'QUEUED', progress: 0 },
      { id: 'job-old', filename: 'old.pdf', stage: 'CHUNKING', progress: 40 },
    ]);
  });

  it('marks only the rejected polling job failed without retaining a private error', () => {
    const jobs = [
      {
        id: 'job-a',
        filename: 'a.pdf',
        stage: 'CHUNKING' as const,
        progress: 40,
        error: 'PRIVATE_ERROR',
      },
      { id: 'job-b', filename: 'b.pdf', stage: 'EMBEDDING' as const, progress: 60 },
    ];

    expect(markJobFailedSafely(jobs, 'job-a')).toEqual([
      { id: 'job-a', filename: 'a.pdf', stage: 'FAILED', progress: 40 },
      { id: 'job-b', filename: 'b.pdf', stage: 'EMBEDDING', progress: 60 },
    ]);
  });

  it('recognizes only completed and failed stages as terminal', () => {
    expect(isTerminal('INDEXING')).toBe(false);
    expect(isTerminal('COMPLETED')).toBe(true);
    expect(isTerminal('FAILED')).toBe(true);
  });
});
