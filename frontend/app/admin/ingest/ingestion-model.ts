import type { IngestionJob, IngestionStage } from '../../../components/shared';
import type { DocumentType, IngestionMetadata } from '../../../lib/adminIngestion';

export interface IngestionDraft extends Omit<IngestionMetadata, 'documentType'> {
  id: string;
  file: File;
  documentType: DocumentType | '';
  note: string;
}

export function reconcileDrafts(
  previous: IngestionDraft[],
  files: File[],
  createId: () => string,
): IngestionDraft[] {
  const draftsByFile = new Map<File, IngestionDraft[]>();

  for (const draft of previous) {
    const matchingDrafts = draftsByFile.get(draft.file) ?? [];
    matchingDrafts.push(draft);
    draftsByFile.set(draft.file, matchingDrafts);
  }

  return files.map((file) => {
    const matchingDraft = draftsByFile.get(file)?.shift();
    if (matchingDraft) return matchingDraft;

    return { id: createId(), file, documentType: '', note: '' };
  });
}

export function isBatchValid(drafts: IngestionDraft[]): boolean {
  return drafts.length > 0 && drafts.every((draft) => draft.documentType !== '');
}

export function canSubmitBatch(
  drafts: IngestionDraft[],
  isConfirmed: boolean,
  isSubmitting: boolean,
): boolean {
  return isBatchValid(drafts) && isConfirmed && !isSubmitting;
}

export function isTerminal(stage: IngestionStage): boolean {
  return stage === 'COMPLETED' || stage === 'FAILED';
}

export function replaceJobById(jobs: IngestionJob[], replacement: IngestionJob): IngestionJob[] {
  return jobs.map((job) => (job.id === replacement.id ? replacement : job));
}

export function markJobFailedSafely(jobs: IngestionJob[], jobId: string): IngestionJob[] {
  return jobs.map((job) =>
    job.id === jobId
      ? {
          id: job.id,
          filename: job.filename,
          stage: 'FAILED',
          progress: job.progress,
        }
      : job,
  );
}
