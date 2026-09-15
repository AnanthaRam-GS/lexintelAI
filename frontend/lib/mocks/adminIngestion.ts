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
  corpusServiceHealth?: Partial<Record<'chromaDb' | 'postgresql', ServiceHealth>>;
  fileFailureReasons?: Partial<
    Record<string, 'corrupted' | 'processing' | 'too-large' | 'unsupported'>
  >;
  failPollRequests?: number;
  pollFailureMode?: 'network' | 'service';
  failSubmitRequests?: number;
  failFilenames?: string[];
  stallFilenames?: string[];
}

export const STORAGE_KEY = 'legalai-admin-ingestion-jobs';

const SAFE_FAILURE_TEXT = 'This file could not be processed. Review the file and try again.';
const SAFE_SUBMIT_FAILURE_TEXT = 'Unable to start ingestion.';
// Keep mock-phase rehydration bounded: 25 active rows are enough for one admin
// session, while 128-character IDs and 255-character display names cover normal
// backend identifiers and filesystem names without trusting arbitrary storage.
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

interface NormalizedAdminIngestionMockConfig {
  delayMs: number;
  failCorpusRequests: number;
  corpusServiceHealth: Partial<Record<'chromaDb' | 'postgresql', ServiceHealth>>;
  fileFailureReasons: Partial<
    Record<string, 'corrupted' | 'processing' | 'too-large' | 'unsupported'>
  >;
  failPollRequests: number;
  pollFailureMode: 'network' | 'service';
  failSubmitRequests: number;
  failFilenames: string[];
  stallFilenames: string[];
}

const defaultConfig = (): NormalizedAdminIngestionMockConfig => ({
  delayMs: 0,
  failCorpusRequests: 0,
  corpusServiceHealth: {},
  fileFailureReasons: {},
  failPollRequests: 0,
  pollFailureMode: 'service',
  failSubmitRequests: 0,
  failFilenames: [],
  stallFilenames: [],
});

let config = defaultConfig();
let corpusFailureCount = 0;
let pollFailureCount = 0;
let submitFailureCount = 0;
let nextJobNumber = 1;
const jobs = new Map<string, JobState>();

const wait = async (delayMs: number) => {
  if (delayMs <= 0) return;
  await new Promise<void>((resolve) => setTimeout(resolve, delayMs));
};

/** Build-time-only browser audit switch; never used by live endpoint logic. */
function browserAuditScenario(): 'none' | 'partial-failure' | 'service-down' | 'stall' {
  const scenario = process.env.NEXT_PUBLIC_LEGALAI_ADMIN_MOCK_SCENARIO;
  return scenario === 'partial-failure' || scenario === 'service-down' || scenario === 'stall'
    ? scenario
    : 'none';
}

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
  const auditScenario = browserAuditScenario();
  return {
    ...corpusStats,
    breakdown: { ...corpusStats.breakdown },
    chromaDb: {
      ...corpusStats.chromaDb,
      status:
        config.corpusServiceHealth.chromaDb ??
        (auditScenario === 'service-down' ? 'down' : corpusStats.chromaDb.status),
    },
    postgresql: {
      ...corpusStats.postgresql,
      status:
        config.corpusServiceHealth.postgresql ??
        (auditScenario === 'service-down' ? 'down' : corpusStats.postgresql.status),
    },
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

  const reservedIds = new Set([
    ...jobs.keys(),
    ...readPersistedIngestionJobs().map(({ id }) => id),
  ]);

  return {
    jobIds: files.map((file) => {
      let id: string;
      do {
        id = `job-${nextJobNumber}`;
        nextJobNumber += 1;
      } while (reservedIds.has(id));
      reservedIds.add(id);
      jobs.set(id, { filename: file.name, pollCount: 0 });
      return id;
    }),
  };
}

export async function pollIngestionStatusMock(jobId: string): Promise<IngestionJob> {
  await wait(config.delayMs);
  if (pollFailureCount < config.failPollRequests) {
    pollFailureCount += 1;
    if (config.pollFailureMode === 'network') {
      throw new TypeError('Mock network request failed.');
    }
    throw new Error('Mock ingestion status request failed.');
  }
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

  const auditScenario = browserAuditScenario();
  const configuredFailure =
    config.fileFailureReasons[state.filename] ??
    (auditScenario === 'partial-failure' && state.filename.includes('damaged')
      ? 'corrupted'
      : undefined);
  if (configuredFailure || config.failFilenames.includes(state.filename)) {
    return {
      id: jobId,
      filename: state.filename,
      stage: 'FAILED',
      progress: progressForStage('FAILED'),
      error: configuredFailure ?? 'processing',
    };
  }

  if (config.stallFilenames.includes(state.filename) || auditScenario === 'stall') {
    return {
      id: jobId,
      filename: state.filename,
      stage: 'EXTRACTING',
      progress: progressForStage('EXTRACTING'),
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
    ...defaultConfig(),
    ...nextConfig,
    corpusServiceHealth: { ...nextConfig.corpusServiceHealth },
    fileFailureReasons: { ...nextConfig.fileFailureReasons },
    failFilenames: nextConfig.failFilenames ? [...nextConfig.failFilenames] : [],
    stallFilenames: nextConfig.stallFilenames ? [...nextConfig.stallFilenames] : [],
  };
  corpusFailureCount = 0;
  pollFailureCount = 0;
  submitFailureCount = 0;
}

export function resetAdminIngestionMockForTests(): void {
  config = defaultConfig();
  corpusFailureCount = 0;
  pollFailureCount = 0;
  submitFailureCount = 0;
  nextJobNumber = 1;
  jobs.clear();
}
