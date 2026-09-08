import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { IngestionStage } from '../../components/shared';
import {
  STORAGE_KEY,
  configureAdminIngestionMockForTests,
  fetchCorpusStatsMock,
  pollIngestionStatusMock,
  progressForStage,
  readPersistedIngestionJobs,
  resetAdminIngestionMockForTests,
  submitIngestionMock,
  writePersistedIngestionJobs,
} from '../../lib/mocks/adminIngestion';

const stages: IngestionStage[] = [
  'QUEUED',
  'EXTRACTING',
  'CHUNKING',
  'EMBEDDING',
  'INDEXING',
  'COMPLETED',
  'FAILED',
];

const pdf = (name: string) =>
  new File([`${name}-private-content`], name, { type: 'application/pdf' });

describe('admin ingestion mock boundary', () => {
  beforeEach(() => {
    sessionStorage.clear();
    resetAdminIngestionMockForTests();
  });

  afterEach(() => {
    sessionStorage.clear();
    resetAdminIngestionMockForTests();
  });

  it('returns the complete corpus and service-health contract', async () => {
    const stats = await fetchCorpusStatsMock();

    expect(stats).toMatchObject({
      totalDocuments: expect.any(Number),
      lastUpdatedTimestamp: expect.any(String),
      lastIngestionDate: expect.any(String),
      breakdown: {
        judgment: expect.any(Number),
        statute: expect.any(Number),
        other: expect.any(Number),
      },
      chromaDb: { status: expect.stringMatching(/^(healthy|degraded|down)$/) },
      postgresql: { status: expect.stringMatching(/^(healthy|degraded|down)$/) },
    });
    expect(Number.isNaN(Date.parse(stats.lastUpdatedTimestamp))).toBe(false);
    expect(Number.isNaN(Date.parse(stats.lastIngestionDate))).toBe(false);
  });

  it('maps all shared stages to deterministic progress without redefining the stage contract', () => {
    const progress = stages.map(progressForStage);

    expect(progress).toEqual([0, 20, 40, 60, 80, 100, 100]);
    expect(progress.every((value) => value >= 0 && value <= 100)).toBe(true);
  });

  it('creates one aligned job ID for every file and metadata entry', async () => {
    const files = [pdf('lease.pdf'), pdf('statute.pdf')];
    const metadata = [
      { documentType: 'judgment' as const },
      { documentType: 'statute' as const, note: 'Second item' },
    ];

    await expect(submitIngestionMock(files, metadata)).resolves.toEqual({
      jobIds: ['job-1', 'job-2'],
    });
    expect(await pollIngestionStatusMock('job-1')).toMatchObject({
      id: 'job-1',
      filename: 'lease.pdf',
      stage: 'EXTRACTING',
      progress: 20,
    });
    expect(await pollIngestionStatusMock('job-2')).toMatchObject({
      id: 'job-2',
      filename: 'statute.pdf',
      stage: 'EXTRACTING',
      progress: 20,
    });
  });

  it('rejects files and metadata that are not aligned', async () => {
    await expect(
      submitIngestionMock(
        [pdf('lease.pdf')],
        [{ documentType: 'judgment' }, { documentType: 'statute' }],
      ),
    ).rejects.toThrow('Unable to start ingestion.');
  });

  it('progresses a job through every active stage and then completion', async () => {
    await submitIngestionMock([pdf('lease.pdf')], [{ documentType: 'judgment' }]);

    const progression = [];
    for (let index = 0; index < 5; index += 1) {
      progression.push((await pollIngestionStatusMock('job-1')).stage);
    }

    expect(progression).toEqual(['EXTRACTING', 'CHUNKING', 'EMBEDDING', 'INDEXING', 'COMPLETED']);
    expect(await pollIngestionStatusMock('job-1')).toMatchObject({
      stage: 'COMPLETED',
      progress: 100,
    });
  });

  it('returns fixed safe failure text and never private mock details', async () => {
    await submitIngestionMock([pdf('secret.pdf')], [{ documentType: 'other' }]);
    configureAdminIngestionMockForTests({ failFilenames: ['secret.pdf'] });

    const failed = await pollIngestionStatusMock('job-1');

    expect(failed).toMatchObject({
      id: 'job-1',
      filename: 'secret.pdf',
      stage: 'FAILED',
      progress: 100,
      error: 'This file could not be processed. Review the file and try again.',
    });
    expect(JSON.stringify(failed)).not.toContain('private');
    expect(JSON.stringify(failed)).not.toContain('secret.pdf-private-content');
  });

  it('normalizes malformed storage to minimal active records and removes terminal records', () => {
    sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify([
        {
          id: 'job-1',
          filename: 'lease.pdf',
          stage: 'CHUNKING',
          progress: 42,
          note: 'private note',
          documentType: 'judgment',
          error: 'private error',
        },
        { id: '', filename: 'missing-id.pdf', stage: 'CHUNKING' },
        { id: 'job-2', filename: 'done.pdf', stage: 'COMPLETED' },
        { id: 'job-3', filename: 'unknown.pdf', stage: 'NOT_A_STAGE' },
        'not-an-object',
      ]),
    );

    expect(readPersistedIngestionJobs()).toEqual([
      { id: 'job-1', filename: 'lease.pdf', stage: 'CHUNKING' },
    ]);
    expect(JSON.parse(sessionStorage.getItem(STORAGE_KEY)!)).toEqual([
      { id: 'job-1', filename: 'lease.pdf', stage: 'CHUNKING' },
    ]);
    expect(sessionStorage.getItem(STORAGE_KEY)).not.toContain('progress');
    expect(sessionStorage.getItem(STORAGE_KEY)).not.toContain('note');
    expect(sessionStorage.getItem(STORAGE_KEY)).not.toContain('documentType');
    expect(sessionStorage.getItem(STORAGE_KEY)).not.toContain('error');
  });

  it('handles malformed JSON safely and writes only non-terminal records', () => {
    sessionStorage.setItem(STORAGE_KEY, '{not-json');
    expect(readPersistedIngestionJobs()).toEqual([]);

    writePersistedIngestionJobs([
      { id: 'job-1', filename: 'lease.pdf', stage: 'CHUNKING' },
      { id: 'job-2', filename: 'done.pdf', stage: 'FAILED' },
    ]);

    expect(readPersistedIngestionJobs()).toEqual([
      { id: 'job-1', filename: 'lease.pdf', stage: 'CHUNKING' },
    ]);
    expect(sessionStorage.getItem(STORAGE_KEY)).toBe(
      JSON.stringify([{ id: 'job-1', filename: 'lease.pdf', stage: 'CHUNKING' }]),
    );
  });

  it('removes terminal records while preserving active records and their order', () => {
    writePersistedIngestionJobs([
      { id: 'job-1', filename: 'lease.pdf', stage: 'CHUNKING' },
      { id: 'job-2', filename: 'motion.pdf', stage: 'EMBEDDING' },
    ]);
    writePersistedIngestionJobs([
      { id: 'job-1', filename: 'lease.pdf', stage: 'COMPLETED' },
      { id: 'job-2', filename: 'motion.pdf', stage: 'INDEXING' },
    ]);

    expect(readPersistedIngestionJobs()).toEqual([
      { id: 'job-2', filename: 'motion.pdf', stage: 'INDEXING' },
    ]);
  });
});
