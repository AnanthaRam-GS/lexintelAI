import type { IngestionJob as SharedIngestionJob, IngestionStage } from '../../components/shared';

export type IngestionJob = SharedIngestionJob;
export type ServiceHealth = 'healthy' | 'degraded' | 'down';
export type DocumentType = 'judgment' | 'statute' | 'other';

export interface ServiceStatus {
  status: ServiceHealth;
  detail?: string;
}

export interface CorpusStats {
  totalDocuments: number;
  lastUpdatedTimestamp: string;
  lastIngestionDate: string;
  breakdown: Record<DocumentType, number>;
  chromaDb: ServiceStatus;
  postgresql: ServiceStatus;
}

export interface IngestionMetadata {
  documentType: DocumentType;
  note?: string;
}

export interface PersistedIngestionJob {
  id: string;
  filename: string;
  stage: IngestionStage;
}

export interface AdminIngestionMockTestConfig {
  delayMs?: number;
  failCorpusRequests?: number;
  failSubmitRequests?: number;
  failFilenames?: string[];
}

export const STORAGE_KEY = 'legalai-admin-ingestion-jobs';

const SAFE_FAILURE_TEXT = 'This file could not be processed. Review the file and try again.';
const SAFE_SUBMIT_FAILURE_TEXT = 'Unable to start ingestion.';
const STAGES: readonly IngestionStage[] = [
  'QUEUED',
  'EXTRACTING',
  'CHUNKING',
  'EMBEDDING',
  'INDEXING',
  'COMPLETED',
  'FAILED',
];
const ACTIVE_STAGES: readonly IngestionStage[] = [
  'EXTRACTING',
  'CHUNKING',
  'EMBEDDING',
  'INDEXING',
  'COMPLETED',
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

const corpusStats: CorpusStats = {
  totalDocuments: 42,
  lastUpdatedTimestamp: '2026-09-08T09:00:00.000Z',
  lastIngestionDate: '2026-09-07T09:00:00.000Z',
  breakdown: { judgment: 20, statute: 12, other: 10 },
  chromaDb: { status: 'healthy', detail: 'Available' },
  postgresql: { status: 'healthy', detail: 'Available' },
};

interface JobState {
  filename: string;
  pollCount: number;
}

let config: Required<AdminIngestionMockTestConfig> = {
  delayMs: 0,
  failCorpusRequests: 0,
  failSubmitRequests: 0,
  failFilenames: [],
};
let corpusFailureCount = 0;
let submitFailureCount = 0;
let nextJobNumber = 1;
const jobs = new Map<string, JobState>();

const wait = async (delayMs: number) => {
  if (delayMs <= 0) return;
  await new Promise<void>((resolve) => setTimeout(resolve, delayMs));
};

const isIngestionStage = (value: unknown): value is IngestionStage =>
  typeof value === 'string' && STAGES.includes(value as IngestionStage);

const isTerminalStage = (stage: IngestionStage) => stage === 'COMPLETED' || stage === 'FAILED';

const isPersistedRecord = (value: unknown): value is PersistedIngestionJob => {
  if (!value || typeof value !== 'object') return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.id === 'string' &&
    record.id.trim().length > 0 &&
    typeof record.filename === 'string' &&
    record.filename.trim().length > 0 &&
    isIngestionStage(record.stage)
  );
};

const normalizePersistedRecords = (value: unknown): PersistedIngestionJob[] => {
  if (!Array.isArray(value)) return [];

  const seen = new Set<string>();
  return value.filter(isPersistedRecord).flatMap((record) => {
    if (seen.has(record.id) || isTerminalStage(record.stage)) return [];
    seen.add(record.id);
    return [{ id: record.id, filename: record.filename, stage: record.stage }];
  });
};

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
    // Storage is best-effort in this mock boundary.
  }
};

export function progressForStage(stage: IngestionStage): number {
  return PROGRESS_BY_STAGE[stage];
}

// TODO(contract): replace these three mock endpoint functions with
// frontend/lib/api.ts calls when the live 1.R.2 endpoints exist; keep route
// callers on this single boundary until then.
export async function fetchCorpusStatsMock(): Promise<CorpusStats> {
  await wait(config.delayMs);
  if (corpusFailureCount < config.failCorpusRequests) {
    corpusFailureCount += 1;
    throw new Error('Unable to load system status.');
  }
  return {
    ...corpusStats,
    breakdown: { ...corpusStats.breakdown },
    chromaDb: { ...corpusStats.chromaDb },
    postgresql: { ...corpusStats.postgresql },
  };
}

export async function submitIngestionMock(
  files: File[],
  metadata: IngestionMetadata[],
): Promise<{ jobIds: string[] }> {
  await wait(config.delayMs);
  if (submitFailureCount < config.failSubmitRequests) {
    submitFailureCount += 1;
    throw new Error(SAFE_SUBMIT_FAILURE_TEXT);
  }
  if (
    files.length === 0 ||
    files.length !== metadata.length ||
    metadata.some(({ documentType }) => !['judgment', 'statute', 'other'].includes(documentType))
  ) {
    throw new Error(SAFE_SUBMIT_FAILURE_TEXT);
  }

  return {
    jobIds: files.map((file) => {
      const id = `job-${nextJobNumber}`;
      nextJobNumber += 1;
      jobs.set(id, { filename: file.name, pollCount: 0 });
      return id;
    }),
  };
}

export async function pollIngestionStatusMock(jobId: string): Promise<IngestionJob> {
  await wait(config.delayMs);
  let state = jobs.get(jobId);
  if (!state) {
    const restored = readPersistedIngestionJobs().find((record) => record.id === jobId);
    if (restored) {
      state = {
        filename: restored.filename,
        pollCount: 0,
      };
      jobs.set(jobId, state);
    }
  }
  if (!state) {
    return {
      id: jobId,
      filename: 'Unknown document',
      stage: 'FAILED',
      progress: progressForStage('FAILED'),
      error: SAFE_FAILURE_TEXT,
    };
  }

  if (config.failFilenames.includes(state.filename)) {
    return {
      id: jobId,
      filename: state.filename,
      stage: 'FAILED',
      progress: progressForStage('FAILED'),
      error: SAFE_FAILURE_TEXT,
    };
  }

  const stage = ACTIVE_STAGES[Math.min(state.pollCount, ACTIVE_STAGES.length - 1)];
  state.pollCount += 1;
  return {
    id: jobId,
    filename: state.filename,
    stage,
    progress: progressForStage(stage),
  };
}

// TODO(contract): mock-phase sessionStorage rehydration stand-in. Delete this
// mechanism when the backend job-listing endpoint exists; do not leave it as
// dead fallback code.
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

// TODO(contract): mock-phase sessionStorage rehydration stand-in. Delete this
// mechanism when the backend job-listing endpoint exists; do not leave it as
// dead fallback code.
export function writePersistedIngestionJobs(records: PersistedIngestionJob[]): void {
  writeStorage(normalizePersistedRecords(records));
}

export function configureAdminIngestionMockForTests(
  nextConfig: AdminIngestionMockTestConfig,
): void {
  config = {
    delayMs: 0,
    failCorpusRequests: 0,
    failSubmitRequests: 0,
    ...nextConfig,
    failFilenames: nextConfig.failFilenames ? [...nextConfig.failFilenames] : [],
  };
  corpusFailureCount = 0;
  submitFailureCount = 0;
}

export function resetAdminIngestionMockForTests(): void {
  config = { delayMs: 0, failCorpusRequests: 0, failSubmitRequests: 0, failFilenames: [] };
  corpusFailureCount = 0;
  submitFailureCount = 0;
  nextJobNumber = 1;
  jobs.clear();
}
