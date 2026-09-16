import type { IngestionStage } from '../components/shared';
import type { AdminDocumentType } from './types/api';

export type DocumentType = AdminDocumentType;

export interface IngestionMetadata {
  documentType: DocumentType;
  note?: string;
}

export interface PersistedIngestionJob {
  id: string;
  filename: string;
  stage: IngestionStage;
}

export const STORAGE_KEY = 'legalai-admin-ingestion-jobs';
export const MAX_ACTIVE_INGESTION_JOBS = 25;

const MAX_PERSISTED_JOB_ID_LENGTH = 128;
const MAX_PERSISTED_FILENAME_LENGTH = 255;

const STAGES: readonly IngestionStage[] = [
  'QUEUED',
  'EXTRACTING',
  'CHUNKING',
  'EMBEDDING',
  'INDEXING',
  'COMPLETED',
  'FAILED',
];

const PROGRESS_BY_STAGE: Record<IngestionStage, number> = {
  QUEUED: 0,
  EXTRACTING: 20,
  CHUNKING: 40,
  EMBEDDING: 60,
  INDEXING: 80,
  COMPLETED: 100,
  FAILED: 100,
};

export function progressForStage(stage: IngestionStage): number {
  return PROGRESS_BY_STAGE[stage];
}

export function readPersistedIngestionJobs(): PersistedIngestionJob[] {
  const storage = getSessionStorage();
  if (!storage) return [];

  let parsed: unknown;
  try {
    const serialized = storage.getItem(STORAGE_KEY);
    if (!serialized) return [];
    parsed = JSON.parse(serialized) as unknown;
  } catch {
    writeStorage([]);
    return [];
  }

  const records = normalizePersistedRecords(parsed);
  writeStorage(records);
  return records;
}

export function writePersistedIngestionJobs(records: PersistedIngestionJob[]): void {
  writeStorage(normalizePersistedRecords(records));
}

const getSessionStorage = (): Storage | null => {
  if (typeof window === 'undefined') return null;
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
};

const writeStorage = (records: PersistedIngestionJob[]) => {
  const storage = getSessionStorage();
  if (!storage) return;
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify(records));
  } catch {
    // Browser storage is best-effort; live polling remains authoritative.
  }
};

const isIngestionStage = (value: unknown): value is IngestionStage =>
  typeof value === 'string' && STAGES.includes(value as IngestionStage);

const isTerminalStage = (stage: IngestionStage) => stage === 'COMPLETED' || stage === 'FAILED';

const toPersistedRecord = (value: unknown): PersistedIngestionJob | null => {
  if (!value || typeof value !== 'object') return null;
  const record = value as Record<string, unknown>;
  if (typeof record.id !== 'string' || typeof record.filename !== 'string') return null;

  const id = record.id.trim();
  const filename = record.filename.trim();
  if (
    id.length === 0 ||
    id.length > MAX_PERSISTED_JOB_ID_LENGTH ||
    filename.length === 0 ||
    filename.length > MAX_PERSISTED_FILENAME_LENGTH ||
    !isIngestionStage(record.stage)
  ) {
    return null;
  }

  return { id, filename, stage: record.stage };
};

const normalizePersistedRecords = (value: unknown): PersistedIngestionJob[] => {
  if (!Array.isArray(value)) return [];

  const seen = new Set<string>();
  const records: PersistedIngestionJob[] = [];
  for (const valueRecord of value) {
    if (records.length >= MAX_ACTIVE_INGESTION_JOBS) break;
    const record = toPersistedRecord(valueRecord);
    if (!record || seen.has(record.id) || isTerminalStage(record.stage)) continue;
    seen.add(record.id);
    records.push(record);
  }
  return records;
};
