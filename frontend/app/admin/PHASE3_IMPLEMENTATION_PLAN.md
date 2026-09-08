# LegalAI Phase 3 Admin Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a safe, accessible `/admin` system-status page and `/admin/ingest` permanent-corpus batch workflow with independently polled, refresh-resumable mock ingestion jobs.

**Architecture:** Route-local client components import the one caller-facing boundary, `frontend/lib/mocks/adminIngestion.ts`. That file owns provisional endpoint contracts, deterministic progression, safe failures, and minimal mock-only session rehydration; it is the only import path replaced when live `1.R.2` calls exist. The ingestion page keeps files and metadata only in React memory and renders jobs through the existing shared `IngestionProgress`.

**Tech Stack:** Next.js 16.3.4 App Router, React 19.2.8, TypeScript 6.0.3, Tailwind CSS 4.3.3, Vitest 4.1.11, Testing Library, existing Phase 1 shared components.

**Spec:** `frontend/app/admin/PHASE3_DESIGN.md`

## Global Constraints

- Work only on `feat/phase3-admin-mode-gugan`, based on `origin/main` commit `4ea1c75968c99d46cb324380c694c3e174269fa1`.
- Modify only `frontend/app/admin/**`, `frontend/lib/mocks/adminIngestion.ts`, this plan, and requested Phase 3 evidence.
- Do not modify or copy `frontend/components/shared/**`; reuse its four required components exactly as merged.
- Do not create or modify `frontend/lib/api.ts` or touch backend, data, models, notebooks, authentication, Public Mode, Professional Mode, or dependencies/configuration.
- Import the shared seven-value `IngestionStage`; never redefine it.
- If the upstream `/admin/*` guard is absent, add `// TODO(auth): route guard pending 2.V.2` at the top of both page files; do not build a guard.
- Browser storage may contain only job `id`, display `filename`, and `stage`. Never store progress, errors, document type, notes, `File` objects, bytes, or contents.
- Treat restored records as placeholders, immediately poll every restored job, and remove terminal records from storage while retaining them in the mounted React session.
- Keep the required provisional document-type TODO and Ananthu/Roshinee warning in the PR.
- Never render raw errors, backend/provider/database details, stack traces, private paths, or file contents.
- Use only Phase 1 visual tokens; add no color or font.
- Use a fresh implementation subagent plus spec-compliance and code-quality review gates for each implementation task.
- Keep the final PR open and unmerged.

## File map

- `frontend/lib/mocks/adminIngestion.ts` — contracts, deterministic mocks, safe failures, and minimal session rehydration.
- `frontend/app/admin/AdminStatus.tsx` — status loading, retry, refresh, health, and ingestion action.
- `frontend/app/admin/page.tsx` — `/admin` route shell and auth-owner TODO if needed.
- `frontend/app/admin/ingest/ingestion-model.ts` — pure file identity, validation, eligibility, ordering, and progress helpers.
- `frontend/app/admin/ingest/IngestionWorkspace.tsx` — batch preparation, submission, polling, rehydration, and job rendering.
- `frontend/app/admin/ingest/page.tsx` — `/admin/ingest` shell and auth-owner TODO if needed.
- Co-located `*.test.ts` and `*.test.tsx` files — contract and behavior regressions.
- `frontend/app/admin/screenshots/**` — final requested browser evidence.

---

### Task 1: Admin contract, mock progression, and persistence boundary

**Files:**

- Create: `frontend/lib/mocks/adminIngestion.ts`
- Test: `frontend/app/admin/adminIngestion.test.ts`

**Interfaces:**

- Consumes: shared `IngestionStage` and `IngestionJob` without modifying them.
- Produces the exact types and functions in Step 4. Later tasks import them directly from `frontend/lib/mocks/adminIngestion.ts`.

- [ ] **Step 1: Re-read shared contracts and local Next.js docs**

Read `frontend/components/shared/IngestionProgress.tsx`, `UploadDropzone.tsx`, and relevant App Router/client-component files under `frontend/node_modules/next/dist/docs/`. Record the shared stage union in the task report.

- [ ] **Step 2: Write failing contract and persistence tests**

Cover the seven stages, corpus/service fields, one job ID per file, file/metadata alignment, deterministic progression, safe failure text, malformed storage, exact field normalization, and terminal cleanup.

```ts
expect(JSON.parse(sessionStorage.getItem(STORAGE_KEY)!)).toEqual([
  { id: 'job-1', filename: 'lease.pdf', stage: 'CHUNKING' },
]);
expect(sessionStorage.getItem(STORAGE_KEY)).not.toContain('progress');
expect(sessionStorage.getItem(STORAGE_KEY)).not.toContain('note');
expect(sessionStorage.getItem(STORAGE_KEY)).not.toContain('documentType');
expect(sessionStorage.getItem(STORAGE_KEY)).not.toContain('error');
```

- [ ] **Step 3: Run focused tests and confirm RED**

```bash
cd frontend
npm run test:run -- app/admin/adminIngestion.test.ts
```

Expected: FAIL because the contract and boundary do not exist.

- [ ] **Step 4: Implement the minimal contract and state machine**

```ts
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

export function fetchCorpusStatsMock(): Promise<CorpusStats>;
export function submitIngestionMock(
  files: File[],
  metadata: IngestionMetadata[],
): Promise<{ jobIds: string[] }>;
export function pollIngestionStatusMock(jobId: string): Promise<IngestionJob>;
export function progressForStage(stage: IngestionStage): number;
export function readPersistedIngestionJobs(): PersistedIngestionJob[];
export function writePersistedIngestionJobs(records: PersistedIngestionJob[]): void;

export interface AdminIngestionMockTestConfig {
  delayMs?: number;
  failCorpusRequests?: number;
  failSubmitRequests?: number;
  failFilenames?: string[];
}

export function configureAdminIngestionMockForTests(config: AdminIngestionMockTestConfig): void;
export function resetAdminIngestionMockForTests(): void;
```

Use one stage-to-progress map without persisting progress. Keep tests deterministic rather than depending on random failure.

Add the endpoint replacement TODO and this storage-site TODO:

```ts
// TODO(contract): mock-phase sessionStorage rehydration stand-in. Delete this
// mechanism when the backend job-listing endpoint exists; do not leave it as
// dead fallback code.
```

- [ ] **Step 5: Run focused tests and confirm GREEN**

```bash
cd frontend
npm run test:run -- app/admin/adminIngestion.test.ts
```

Expected: all tests pass and serialized storage has exactly three allowed fields.

- [ ] **Step 6: Run Task 1 review gates**

Give fresh spec-compliance and code-quality reviewers the spec, task, base commit, and head. Repair every blocker/important issue and repeat both reviews until clean.

- [ ] **Step 7: Commit Task 1**

```bash
git add frontend/lib/mocks/adminIngestion.ts frontend/app/admin/adminIngestion.test.ts
git commit -m "feat(admin): add ingestion mock contract boundary"
```

---

### Task 2: `/admin` system-status experience

**Files:**

- Create: `frontend/app/admin/AdminStatus.tsx`
- Create: `frontend/app/admin/AdminStatus.test.tsx`
- Create: `frontend/app/admin/page.tsx`

**Interfaces:**

- Consumes: `fetchCorpusStatsMock(): Promise<CorpusStats>` directly from `frontend/lib/mocks/adminIngestion.ts`; shared `LoadingSpinner` and `ErrorMessage`.
- Produces: accessible loading, error/Retry, health, refresh, and `/admin/ingest` navigation states.

- [ ] **Step 1: Write failing status-page tests**

Cover four separated regions—Corpus, ChromaDB, PostgreSQL, and Ingest documents—plus breakdown, last ingestion, icon-and-text health, shared loading, safe banner Retry, non-overlapping refresh, and exact navigation. Assert rejected private text and `technicalDetail` never enter the DOM.

```tsx
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

const healthyStats: CorpusStats = {
  totalDocuments: 42,
  lastUpdatedTimestamp: '2026-09-08T09:00:00.000Z',
  lastIngestionDate: '2026-09-07T09:00:00.000Z',
  breakdown: { judgment: 20, statute: 12, other: 10 },
  chromaDb: { status: 'healthy', detail: 'Available' },
  postgresql: { status: 'healthy', detail: 'Available' },
};

it('renders four status regions with icon-and-text service health', async () => {
  vi.mocked(fetchCorpusStatsMock).mockResolvedValue(healthyStats);
  render(<AdminStatus />);

  expect(screen.getByLabelText('Loading system status')).toBeInTheDocument();
  expect(await screen.findByRole('heading', { name: 'Corpus' })).toBeInTheDocument();
  expect(screen.getByRole('region', { name: 'ChromaDB status' })).toHaveTextContent('Healthy');
  expect(screen.getByRole('region', { name: 'PostgreSQL status' })).toHaveTextContent('Healthy');
  expect(screen.getByRole('link', { name: 'Ingest documents' })).toHaveAttribute(
    'href',
    '/admin/ingest',
  );
});

it('retries with fixed safe copy and never renders the rejection', async () => {
  const user = userEvent.setup();
  vi.mocked(fetchCorpusStatsMock)
    .mockRejectedValueOnce(new Error('postgresql://private-host secret-stack'))
    .mockResolvedValueOnce(healthyStats);
  render(<AdminStatus />);

  expect(await screen.findByRole('alert')).not.toHaveTextContent('private-host');
  await user.click(screen.getByRole('button', { name: 'Retry' }));
  expect(await screen.findByRole('heading', { name: 'Corpus' })).toBeInTheDocument();
});

it('does not overlap refresh requests', async () => {
  const user = userEvent.setup();
  const refresh = deferred<CorpusStats>();
  vi.mocked(fetchCorpusStatsMock)
    .mockResolvedValueOnce(healthyStats)
    .mockReturnValueOnce(refresh.promise);
  render(<AdminStatus />);

  await screen.findByRole('heading', { name: 'Corpus' });
  const button = screen.getByRole('button', { name: 'Refresh status' });
  await user.click(button);
  expect(button).toBeDisabled();
  await user.click(button);
  expect(fetchCorpusStatsMock).toHaveBeenCalledTimes(2);
  refresh.resolve(healthyStats);
  await waitFor(() => expect(button).toBeEnabled());
});
```

Define the small `deferred<T>()` promise helper in the test file so this remains an executable concurrency regression, not pseudocode.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
cd frontend
npm run test:run -- app/admin/AdminStatus.test.tsx
```

Expected: FAIL because the route component does not exist.

- [ ] **Step 3: Implement the route shell and auth-owner marker**

If no parent guard exists, begin `page.tsx` with `// TODO(auth): route guard pending 2.V.2`. Render the client component from a small server shell and add no auth logic.

- [ ] **Step 4: Implement Guided Editorial status states**

Use existing semantic tokens and Lucide icons. Map every service state to a written label and icon. Keep Corpus visually primary while preserving four semantic regions.

```tsx
const healthView: Record<ServiceHealth, { label: string; Icon: LucideIcon; className: string }> = {
  healthy: {
    label: 'Healthy',
    Icon: CheckCircle2,
    className: 'text-[var(--color-success-foreground)]',
  },
  degraded: {
    label: 'Degraded',
    Icon: TriangleAlert,
    className: 'text-[var(--color-warning-foreground)]',
  },
  down: { label: 'Down', Icon: CircleX, className: 'text-[var(--color-error-foreground)]' },
};

function StatusRegions({ stats }: { stats: CorpusStats }) {
  const ChromaIcon = healthView[stats.chromaDb.status].Icon;
  const PostgresIcon = healthView[stats.postgresql.status].Icon;

  return (
    <div>
      <section aria-labelledby="corpus-heading">
        <h2 id="corpus-heading">Corpus</h2>
        <p>{stats.totalDocuments} documents</p>
        <p>Last ingestion: {stats.lastIngestionDate}</p>
      </section>
      <section aria-label="ChromaDB status">
        <ChromaIcon aria-hidden="true" />
        <h2>ChromaDB</h2>
        <p>{healthView[stats.chromaDb.status].label}</p>
      </section>
      <section aria-label="PostgreSQL status">
        <PostgresIcon aria-hidden="true" />
        <h2>PostgreSQL</h2>
        <p>{healthView[stats.postgresql.status].label}</p>
      </section>
      <section aria-labelledby="ingest-heading">
        <h2 id="ingest-heading">Ingest documents</h2>
        <Link href="/admin/ingest">Ingest documents</Link>
      </section>
    </div>
  );
}

export function AdminStatus() {
  const [stats, setStats] = useState<CorpusStats | null>(null);
  const [pending, setPending] = useState(true);
  const [error, setError] = useState(false);
  const isLoadingRef = useRef(false);

  const loadStatus = useCallback(async () => {
    if (isLoadingRef.current) return;
    isLoadingRef.current = true;
    setPending(true);
    setError(false);
    try {
      setStats(await fetchCorpusStatsMock());
    } catch {
      setError(true);
    } finally {
      isLoadingRef.current = false;
      setPending(false);
    }
  }, []);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  if (pending && !stats) {
    return <LoadingSpinner label="Loading system status" />;
  }

  return (
    <main>
      {error ? (
        <ErrorMessage
          message="System status could not be loaded. Try again."
          onRetry={loadStatus}
          title="Unable to load system status"
          variant="banner"
        />
      ) : null}
      <button disabled={pending} onClick={() => void loadStatus()} type="button">
        Refresh status
      </button>
      {stats ? <StatusRegions stats={stats} /> : null}
    </main>
  );
}
```

Expand the route-local Corpus region with the tested document-type breakdown and updated timestamp. Do not pass `technicalDetail` to the shared error component.

- [ ] **Step 5: Run focused tests and confirm GREEN**

```bash
cd frontend
npm run test:run -- app/admin/AdminStatus.test.tsx app/admin/adminIngestion.test.ts
```

- [ ] **Step 6: Run Task 2 review gates**

Repair every blocker/important issue and repeat both fresh reviews until clean.

- [ ] **Step 7: Commit Task 2**

```bash
git add frontend/app/admin/AdminStatus.tsx frontend/app/admin/AdminStatus.test.tsx frontend/app/admin/page.tsx
git commit -m "feat(admin): build system status dashboard"
```

---

### Task 3: Batch selection, metadata, and permanent confirmation

**Files:**

- Create: `frontend/app/admin/ingest/ingestion-model.ts`
- Create: `frontend/app/admin/ingest/ingestion-model.test.ts`
- Create: `frontend/app/admin/ingest/IngestionWorkspace.tsx`
- Create: `frontend/app/admin/ingest/IngestionWorkspace.test.tsx`
- Create: `frontend/app/admin/ingest/page.tsx`

**Interfaces:**

- Consumes: shared `UploadDropzone`; `DocumentType` and `IngestionMetadata` directly from `frontend/lib/mocks/adminIngestion.ts`.
- Produces:

```ts
export interface IngestionDraft {
  id: string;
  file: File;
  documentType: DocumentType | '';
  note: string;
}

export function reconcileDrafts(
  previous: IngestionDraft[],
  files: File[],
  createId: () => string,
): IngestionDraft[];
export function isBatchValid(drafts: IngestionDraft[]): boolean;
export function canSubmitBatch(
  drafts: IngestionDraft[],
  isConfirmed: boolean,
  isSubmitting: boolean,
): boolean;
```

- [ ] **Step 1: Write failing pure-model tests**

Test same-named distinct files, metadata retention for unchanged files, removal cleanup, `isBatchValid`, and `canSubmitBatch`.

Create this executable pure regression rather than folding it into general validation:

```ts
const pdfFile = (name: string) =>
  new File(['pdf'], name, { type: 'application/pdf', lastModified: 1 });

const makeDraft = (overrides: Partial<IngestionDraft> = {}): IngestionDraft => ({
  id: 'draft-1',
  file: pdfFile('default.pdf'),
  documentType: '',
  note: '',
  ...overrides,
});

it('becomes eligible immediately after removing the only invalid draft', () => {
  const valid = makeDraft({ id: 'valid', documentType: 'judgment' });
  const invalid = makeDraft({ id: 'invalid', documentType: '' });

  expect(canSubmitBatch([valid, invalid], true, false)).toBe(false);
  const remaining = [valid, invalid].filter((draft) => draft.id !== invalid.id);
  expect(canSubmitBatch(remaining, true, false)).toBe(true);
});
```

Derive eligibility from current state during render. Do not mirror validity through an effect or timer.

- [ ] **Step 2: Write failing workspace-preparation tests**

Cover multiple-PDF configuration, per-file labels, required type, optional note, exact incomplete filename, file count, confirmation, pending controls, and deletion.

Add a separate rendered integration regression:

```tsx
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
```

Do not call `waitFor`, advance timers, or trigger another interaction between removal and the final assertion.

- [ ] **Step 3: Run focused tests and confirm RED**

```bash
cd frontend
npm run test:run -- app/admin/ingest/ingestion-model.test.ts app/admin/ingest/IngestionWorkspace.test.tsx
```

Expected: FAIL because the model and workspace do not exist.

- [ ] **Step 4: Implement stable drafts and synchronous eligibility**

Use `File` object identity or a stable route-local ID, never filename alone. Keep files and notes only in React state. Adding/replacing files clears confirmation; removing files preserves it while reducing the visibly confirmed count.

- [ ] **Step 5: Add the provisional dropdown and visible TODO**

At the option definition site, include exactly:

```ts
// TODO(contract): confirm doc_type values with Ananthu/Roshinee before treating
// judgment | statute | other as the live documents-table contract.
```

- [ ] **Step 6: Implement the route shell**

If no parent guard exists, begin `frontend/app/admin/ingest/page.tsx` with `// TODO(auth): route guard pending 2.V.2`. Add no auth logic.

- [ ] **Step 7: Run focused tests and confirm GREEN**

```bash
cd frontend
npm run test:run -- app/admin/ingest/ingestion-model.test.ts app/admin/ingest/IngestionWorkspace.test.tsx
```

Expected: the dedicated removal test proves same-render enablement with confirmation still active.

- [ ] **Step 8: Run Task 3 review gates**

Repair every blocker/important issue and repeat both fresh reviews until clean.

- [ ] **Step 9: Commit Task 3**

```bash
git add frontend/app/admin/ingest
git commit -m "feat(admin): build permanent corpus batch form"
```

---

### Task 4: Submission, independent polling, and refresh rehydration

**Files:**

- Modify: `frontend/app/admin/ingest/IngestionWorkspace.tsx`
- Modify: `frontend/app/admin/ingest/IngestionWorkspace.test.tsx`
- Modify: `frontend/app/admin/ingest/ingestion-model.ts`
- Modify: `frontend/app/admin/ingest/ingestion-model.test.ts`

**Interfaces:**

- Consumes: `submitIngestionMock`, `pollIngestionStatusMock`, `readPersistedIngestionJobs`, `writePersistedIngestionJobs`, and shared `IngestionProgress`.
- Produces: aligned jobs, 2.5-second polling, terminal cleanup, current-session history, and immediate rehydration polling.

- [ ] **Step 1: Write failing submission tests**

Assert file/metadata alignment, newest-first insertion, pending disablement, clearing success, preserving a rejected batch, and fixed safe submission copy.

```tsx
async function configureValidBatch(user: ReturnType<typeof userEvent.setup>, file: File) {
  await user.upload(screen.getByLabelText('Choose PDF files'), file);
  await user.selectOptions(screen.getByLabelText(`Document type for ${file.name}`), 'judgment');
  await user.click(
    screen.getByRole('checkbox', { name: 'I understand this is a permanent corpus update' }),
  );
}

it('submits files and metadata in the same order and clears only after success', async () => {
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

  expect(submitIngestionMock).toHaveBeenCalledWith(files, [
    { documentType: 'judgment', note: undefined },
    { documentType: 'statute', note: 'Second item' },
  ]);
  expect(await screen.findByText('a.pdf')).toBeInTheDocument();
  expect(screen.queryByLabelText('Document type for a.pdf')).not.toBeInTheDocument();
  const serialized = sessionStorage.getItem(sessionStorage.key(0)!);
  expect(serialized).not.toContain('PRIVATE_FILE_CONTENT');
  expect(serialized).not.toContain('Second item');
  expect(serialized).not.toContain('documentType');
});

it('retains the batch and hides private rejection details after submit failure', async () => {
  const user = userEvent.setup();
  vi.mocked(submitIngestionMock).mockRejectedValue(new Error('s3://private-bucket/backend-stack'));
  render(<IngestionWorkspace />);
  await configureValidBatch(user, pdfFile('retry.pdf'));
  await user.click(screen.getByRole('button', { name: 'Start ingestion' }));

  expect(await screen.findByRole('alert')).toHaveTextContent('could not be started');
  expect(screen.getByLabelText('Document type for retry.pdf')).toBeInTheDocument();
  expect(document.body).not.toHaveTextContent('private-bucket');
});
```

Keep all mock calls on the single `adminIngestion` boundary.

- [ ] **Step 2: Write failing fake-timer polling tests**

Cover immediate first poll for restored jobs, later 2.5-second polls, independent jobs, per-job terminal stopping, stale-result protection, timer cleanup, and stable newest-first ordering.

```tsx
it('polls jobs independently every 2.5 seconds and stops each terminal job', async () => {
  vi.useFakeTimers();
  writePersistedIngestionJobs([
    { id: 'job-a', filename: 'a.pdf', stage: 'QUEUED' },
    { id: 'job-b', filename: 'b.pdf', stage: 'EXTRACTING' },
  ]);
  vi.mocked(pollIngestionStatusMock)
    .mockResolvedValueOnce({ id: 'job-a', filename: 'a.pdf', stage: 'COMPLETED', progress: 100 })
    .mockResolvedValueOnce({ id: 'job-b', filename: 'b.pdf', stage: 'CHUNKING', progress: 40 })
    .mockResolvedValueOnce({ id: 'job-b', filename: 'b.pdf', stage: 'FAILED', progress: 40 });

  render(<IngestionWorkspace />);
  await act(async () => Promise.resolve());
  expect(pollIngestionStatusMock).toHaveBeenCalledTimes(2);

  await act(async () => vi.advanceTimersByTimeAsync(2_500));
  expect(pollIngestionStatusMock).toHaveBeenCalledTimes(3);
  expect(vi.mocked(pollIngestionStatusMock).mock.calls[2]).toEqual(['job-b']);
  await act(async () => vi.advanceTimersByTimeAsync(5_000));
  expect(pollIngestionStatusMock).toHaveBeenCalledTimes(3);
});
```

Restore real timers in `afterEach`; add a deferred-promise variant that unmounts before resolution and proves a stale result cannot update or reschedule.

- [ ] **Step 3: Write failing refresh/privacy tests**

Seed `{ id, filename, stage }` and assert synchronous placeholder render, derived progress, immediate poll, replacement by returned status, terminal storage removal with current-screen retention, absence after later remount, and zero serialization of disallowed runtime fields.

```tsx
it('renders a minimal placeholder, immediately refreshes truth, and forgets terminal storage', async () => {
  writePersistedIngestionJobs([{ id: 'job-1', filename: 'lease.pdf', stage: 'CHUNKING' }]);
  const live = deferred<IngestionJob>();
  vi.mocked(pollIngestionStatusMock).mockReturnValue(live.promise);

  const view = render(<IngestionWorkspace />);
  expect(screen.getByText('lease.pdf')).toBeInTheDocument();
  expect(pollIngestionStatusMock).toHaveBeenCalledWith('job-1');
  const storageKey = sessionStorage.key(0);
  expect(storageKey).not.toBeNull();
  const serialized = sessionStorage.getItem(storageKey!);
  expect(serialized).not.toContain('progress');
  expect(serialized).not.toContain('error');
  expect(serialized).not.toContain('note');
  expect(serialized).not.toContain('documentType');

  live.resolve({ id: 'job-1', filename: 'lease.pdf', stage: 'COMPLETED', progress: 100 });
  expect(await screen.findByText('COMPLETED')).toBeInTheDocument();
  expect(readPersistedIngestionJobs()).toEqual([]);
  expect(screen.getByText('lease.pdf')).toBeInTheDocument();

  view.unmount();
  render(<IngestionWorkspace />);
  expect(screen.queryByText('lease.pdf')).not.toBeInTheDocument();
});
```

Seed no unrelated storage keys in this test. Also use a distinctive file-content sentinel and assert it is absent from `serialized`. This inspects storage without expanding the exact Task 1 public interface.

- [ ] **Step 4: Run focused tests and confirm RED**

```bash
cd frontend
npm run test:run -- app/admin/ingest/IngestionWorkspace.test.tsx app/admin/ingest/ingestion-model.test.ts
```

- [ ] **Step 5: Implement submission and keyed updates**

Use functional state updates keyed by job ID. Match returned IDs by index only after validating equal lengths. Clear the batch only after initial jobs are safely constructed.

```tsx
const submitBatch = async () => {
  if (!canSubmitBatch(drafts, confirmed, submitting)) return;
  setSubmitting(true);
  setSubmitError(false);
  try {
    const files = drafts.map(({ file }) => file);
    const metadata = drafts.map(({ documentType, note }) => ({
      documentType: documentType as DocumentType,
      note: note.trim() || undefined,
    }));
    const { jobIds } = await submitIngestionMock(files, metadata);
    if (jobIds.length !== drafts.length) throw new Error('Unexpected ingestion response');

    const queued = jobIds.map((id, index): IngestionJob => ({
      id,
      filename: drafts[index].file.name,
      stage: 'QUEUED',
      progress: progressForStage('QUEUED'),
    }));
    setJobs((current) => [...[...queued].reverse(), ...current]);
    queued.forEach(persistActiveJob);
    setDrafts([]);
    setConfirmed(false);
    queued.forEach(({ id }) => startPolling(id));
  } catch {
    setSubmitError(true);
  } finally {
    setSubmitting(false);
  }
};
```

`persistActiveJob` must normalize each job to `{ id, filename, stage }` through the Task 1 read/write functions. The copied reverse keeps newest entries first without mutating `queued` or a React state array.

- [ ] **Step 6: Implement polling and cleanup**

Centralize `isTerminal(stage)`. Immediately poll every restored or new active job; schedule its next poll only after the current call settles. Stop on terminal, removal, or unmount so calls never overlap or resurrect stale state.

```tsx
const isTerminal = (stage: IngestionStage) => stage === 'COMPLETED' || stage === 'FAILED';

function persistActiveJob(job: IngestionJob) {
  const record: PersistedIngestionJob = {
    id: job.id,
    filename: job.filename,
    stage: job.stage,
  };
  const current = readPersistedIngestionJobs();
  const index = current.findIndex(({ id }) => id === job.id);
  writePersistedIngestionJobs(
    index === -1
      ? [record, ...current]
      : current.map((item) => (item.id === job.id ? record : item)),
  );
}

function removePersistedJob(jobId: string) {
  writePersistedIngestionJobs(readPersistedIngestionJobs().filter(({ id }) => id !== jobId));
}

const replaceJobById = (jobs: IngestionJob[], replacement: IngestionJob) =>
  jobs.map((job) => (job.id === replacement.id ? replacement : job));

const markJobFailedSafely = (jobs: IngestionJob[], jobId: string) =>
  jobs.map((job) => (job.id === jobId ? { ...job, stage: 'FAILED' as const } : job));

const timersRef = useRef(new Map<string, ReturnType<typeof setTimeout>>());
const pollingRef = useRef(new Set<string>());
const aliveRef = useRef(true);

const stopPolling = useCallback((jobId: string) => {
  const timer = timersRef.current.get(jobId);
  if (timer) clearTimeout(timer);
  timersRef.current.delete(jobId);
  pollingRef.current.delete(jobId);
}, []);

const startPolling = useCallback(
  (jobId: string) => {
    if (pollingRef.current.has(jobId)) return;
    pollingRef.current.add(jobId);

    const poll = async (): Promise<void> => {
      if (!aliveRef.current || !pollingRef.current.has(jobId)) return;
      try {
        const live = await pollIngestionStatusMock(jobId);
        if (!aliveRef.current || !pollingRef.current.has(jobId)) return;
        setJobs((current) => replaceJobById(current, live));
        if (isTerminal(live.stage)) {
          removePersistedJob(jobId);
          stopPolling(jobId);
          return;
        }
        persistActiveJob(live);
      } catch {
        if (!aliveRef.current || !pollingRef.current.has(jobId)) return;
        setJobs((current) => markJobFailedSafely(current, jobId));
        removePersistedJob(jobId);
        stopPolling(jobId);
        return;
      }
      const timer = setTimeout(() => void poll(), 2_500);
      timersRef.current.set(jobId, timer);
    };

    void poll();
  },
  [stopPolling],
);

useEffect(() => {
  aliveRef.current = true;
  const restored = readPersistedIngestionJobs().map((record): IngestionJob => ({
    ...record,
    progress: progressForStage(record.stage),
  }));
  setJobs(restored);
  restored.filter((job) => !isTerminal(job.stage)).forEach(({ id }) => startPolling(id));
  return () => {
    aliveRef.current = false;
    timersRef.current.forEach(clearTimeout);
    timersRef.current.clear();
    pollingRef.current.clear();
  };
}, [startPolling]);
```

Define `replaceJobById`, `markJobFailedSafely`, `persistActiveJob`, `removePersistedJob`, and `isTerminal` route-locally or in `ingestion-model.ts`. Both persistence helpers must read/normalize/filter/write through the exact Task 1 persistence functions; do not add a second storage adapter or a second mock module. The nested `poll` function avoids a self-referential hook initializer while preserving one in-flight request per job.

- [ ] **Step 7: Render jobs only through the shared component**

```tsx
<IngestionProgress jobs={orderedJobs} />
```

Do not recreate progress bars or expose `job.error`.

- [ ] **Step 8: Run focused tests and confirm GREEN**

```bash
cd frontend
npm run test:run -- app/admin/ingest/IngestionWorkspace.test.tsx app/admin/ingest/ingestion-model.test.ts app/admin/adminIngestion.test.ts
```

- [ ] **Step 9: Run Task 4 review gates**

Repair every blocker/important issue and repeat both fresh reviews until clean.

- [ ] **Step 10: Commit Task 4**

```bash
git add frontend/app/admin/ingest frontend/lib/mocks/adminIngestion.ts
git commit -m "feat(admin): add resumable ingestion job polling"
```

---

### Task 5: Verification, fidelity, post-phase gate, and PR

**Files:**

- Modify only if defects are found: approved Phase 3 paths.
- Create: `frontend/app/admin/screenshots/admin-status-desktop.png`
- Create: `frontend/app/admin/screenshots/admin-status-mobile.png`
- Create: `frontend/app/admin/screenshots/admin-status-down.png`
- Create: `frontend/app/admin/screenshots/admin-ingest-active.png`
- Create: `frontend/app/admin/screenshots/admin-ingest-failed.png`
- Create: `frontend/app/admin/screenshots/admin-ingest-completed.png`

**Interfaces:**

- Consumes: completed Phase 3 tasks and `docs/POST_PHASE_VERIFICATION_GATE.md`.
- Produces: verified implementation, screenshot evidence, scoped commits, and an open unmerged PR.

- [x] **Step 1: Run fresh static and unit checks**

```bash
cd frontend
npm ci
npm run test:run
npm run lint
npm run build
npm run format:check
```

Record exact test file, test, and route counts.

- [x] **Step 2: Run browser verification at 375, 768, and 1440 px**

Cover loading, Retry, every health state, refresh, multiple PDFs, metadata, dedicated invalid-file removal, confirmation reset/preservation, rejected submission retention, mixed job states, rehydration, keyboard/focus, 44×44 targets, headings, announcements, overflow, console output, and automated WCAG A/AA checks.

- [x] **Step 3: Compare concepts and screenshots directly**

Use `view_image` on each accepted concept and corresponding browser screenshot. Fix typography, layout, colors, container model, and responsive drift until agency sign-off fidelity. Shared `IngestionProgress` is authoritative where the concept differs.

- [x] **Step 4: Audit browser storage and safe output**

Confirm active storage keys are exactly `id`, `filename`, and `stage`; terminal records are removed. Search rendered output for seeded secrets, stack traces, private rejection strings, paths, notes, document types, and file contents.

- [x] **Step 5: Run scope checks**

```bash
git diff --check origin/main...HEAD
git diff --name-only origin/main...HEAD
git status --short
test ! -e frontend/lib/api.ts
```

- [ ] **Step 6: Run a fresh whole-branch review**

Give a new reviewer the prompt, design, plan, base, and full diff. Repair every blocker/important issue, rerun all checks, and repeat until clean.

- [ ] **Step 7: Run the entire post-phase verification gate**

Follow `docs/POST_PHASE_VERIFICATION_GATE.md` Steps 1–8 with a fresh reviewer. Any blocker requires repair and a complete gate restart.

- [ ] **Step 8: Commit evidence and push**

```bash
git add frontend/app/admin frontend/lib/mocks/adminIngestion.ts
git commit -m "test(admin): verify Phase 3 admin workflows"
git push -u origin feat/phase3-admin-mode-gugan
```

- [ ] **Step 9: Open the required unmerged PR**

Title:

```text
feat(frontend): Phase 3 — Admin Mode (/admin, /admin/ingest)
```

Include verification results, screenshots, scope confirmation, and these exact notes:

```text
CorpusStats/IngestionJob mocked pending live 1.R.2 endpoints; single swap point in lib/mocks/adminIngestion.ts

No shared components modified; assumes 2.V.2 route guard for /admin/* — TODO left in place if not yet merged

The provisional document-type values (`judgment`, `statute`, `other`) need a 30-second confirmation with Ananthu/Roshinee before they are treated as the live documents-table contract.
```

Do not merge the PR.
