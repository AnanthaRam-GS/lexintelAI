# Phase 5 — Public/Admin Error-State Audit

Verified base: `95f98c50dbcadab89fc767f101fd43046043d918` (latest `main` before the Phase 5 completion branch).

Final verification: all applicable cells pass. Evidence below references the
Phase 5 candidate source and focused regression tests.

| State                         | `/public` landing                       | `/public/ask` (per turn)                                                                                                                                                 | `/admin` status cards                                                                                                                                   | `/admin/ingest` (per file / per batch)                                                                                                                                                                                       |
| ----------------------------- | --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Initial load / empty          | N/A — static landing has no remote load | PASS — three examples are defined at `PublicAsk.tsx:27` and rendered at `PublicAsk.tsx:555`                                                                              | PASS — per-card initial spinners are rendered by `StatusLoadingRegions` at `AdminStatus.tsx:186`; populated cards replace them at `AdminStatus.tsx:301` | PASS — `IngestionProgress.tsx:94` renders the quiet empty state                                                                                                                                                              |
| Loading (fast, <2s)           | N/A                                     | PASS — `PublicAsk.tsx:586` renders the pending-turn spinner without hiding prior entries                                                                                 | PASS — Corpus, ChromaDB, and PostgreSQL each receive a card spinner; refresh is disabled while pending                                                  | N/A before submission; active rows expose named progress bars at `IngestionProgress.tsx:162`                                                                                                                                 |
| Loading (slow, 2–8s)          | N/A                                     | PASS — the 4-second timer changes only the understated status text to “Still working…”                                                                                   | PASS — the same per-card spinners remain visible until the bounded request settles                                                                      | PASS — `ACTIVE_STAGES` and the one progress map advance active mock jobs through 0/20/40/60/80/100                                                                                                                           |
| Timeout / very slow (>8–10s)  | N/A                                     | PASS — at 9 seconds the turn shows distinct long-wait copy plus Keep waiting and Cancel request; Cancel aborts the underlying fetch (`PublicAsk.tsx:237–268,466–488`)    | PASS — the 10-second bound aborts the request and produces timeout-specific safe copy with Retry (`AdminStatus.tsx:215–258`)                            | PASS — each active job receives a 15-second progress-inactivity deadline, reset only by increased live progress, and becomes FAILED only after the mock service acknowledges cancellation (`IngestionWorkspace.tsx:115–182`) |
| Hard failure (service error)  | N/A                                     | PASS — closed service copy and exact Retry; raw caught values are only classified, never rendered                                                                        | PASS — safe unavailable copy and Retry; backend `service.detail` and previously healthy cards are cleared rather than rendered as stale state           | PASS — explicit FAILED states are reduced to a closed reason category at `IngestionWorkspace.tsx:183` and rendered through caller-owned safe copy                                                                            |
| Network loss (client offline) | N/A                                     | PASS — TypeError/offline failures use “Check your connection”; live Chrome network abort verified                                                                        | PASS — a distinct connection message replaces the loading cards and provides Retry                                                                      | PASS — a rejected poll keeps the job active/persisted, shows connection guidance, and retries automatically (`IngestionWorkspace.tsx:155–165`)                                                                               |
| Partial batch failure         | N/A                                     | N/A                                                                                                                                                                      | N/A                                                                                                                                                     | PASS — component test submits 3 files and proves 2 COMPLETED rows remain visible beside 1 actionable FAILED row; live screenshot confirms the same                                                                           |
| Validation failure            | N/A                                     | PASS — empty input keeps Send disabled and the shared PDF validator rejects type/size before fetch                                                                       | N/A                                                                                                                                                     | PASS — upload and per-file document-type errors block submission locally (`IngestionWorkspace.tsx:81–88,386–437`)                                                                                                            |
| Retry                         | N/A                                     | PASS — every failed entry retains its exact in-memory input in `failedInputsRef`; retry removes only that error and never duplicates user text (`PublicAsk.tsx:447–464`) | PASS — manual Retry/Refresh is bounded, non-overlapping, and abortable                                                                                  | PASS — no single-file retry endpoint exists, so safe file guidance explicitly says to correct and add only that file in a new batch; no misleading whole-batch Retry is shown                                                |
| Recovery                      | N/A                                     | PASS — earlier failures remain visible when a later turn succeeds; any retained failed turn can still be retried                                                         | PASS — the next successful fetch clears the banner and restores healthy cards                                                                           | PASS — a successful poll clears the transient connection banner; terminal failed rows remain visible while later jobs complete                                                                                               |

## Cross-check with Professional Mode

Professional Mode is now present in the merged baseline and uses the same
shared `ErrorMessage` component. Its analytics, history, text-query, and upload
pages currently pass caught `Error.message` values through as visible copy.
That is materially less restrictive than the closed Public/Admin vocabulary.
Per Ground Rule 4, this completion pass does not rewrite Ravindran's `4.V.1`
behavior; the inconsistency is explicitly flagged for his follow-up review.
No shared error component was changed.

## Locked implementation decisions

- All rendered copy comes from `app/public/error-copy.ts`, including Admin copy.
- Raw thrown values, service details, backend failure strings, paths, and stack
  traces are never rendered or placed in accessibility text.
- An offline/rejected ingestion poll keeps the job active and visible while
  automatic polling continues; only an explicit FAILED status or 15 seconds
  without increased live progress makes it terminal. The inactivity window is
  reset when the first authoritative live poll arrives and thereafter only when
  a successful poll reports a higher progress value; persisted stage-derived
  progress remains an initial-render placeholder and never becomes the baseline.
- Public Cancel, Admin status timeout, Admin submit timeout, route unmount, and
  active-job shutdown now abort the underlying request rather than only hiding
  its eventual result.
- A timed-out ingestion job is shown as FAILED and removed from mock persistence
  only after `cancelIngestionJobMock` removes it from the mock service. The
  persistence removal happens immediately after cancellation acknowledgement,
  even if the page unmounts before the UI update. The mock boundary documents
  that a real cancel/idempotency endpoint is required before swapping in live
  ingestion APIs.
- Admin browser verification can deterministically select slow/timeout status,
  one-shot status service/network failures, one-shot submission service/network
  failures, submission timeout, and one-shot poll service/network failures with
  recovery through `NEXT_PUBLIC_LEGALAI_ADMIN_MOCK_SCENARIO`. These switches are
  confined to the mock boundary and disappear with the future live API swap.
- Because the current ingestion boundary exposes no single-file retry endpoint,
  a failed row tells the admin to correct and re-add that file in a new batch;
  it does not pretend to resubmit the whole batch or provide a misleading Retry.

## Verification evidence

- Clean install: Node `v25.6.0`, npm `11.8.0`, `npm ci` completed with zero
  vulnerabilities. npm reported the repository-pinned ESLint 9 release as
  deprecated.
- `npm run test:run`: 32 files, 228 tests passed.
- `npm run lint`: zero warnings/errors.
- Phase-owned and branch-added files pass targeted Prettier checks. The Phase 5
  prompt does not require a repository-wide formatting gate; unchanged merged
  Professional files remain outside this phase and are not reformatted here.
- `npm run build`: warning-free compile/type-check with all 13 application routes
  generated, including restored `/login`, `/admin`, and Professional routes.
- Live Chrome: `/public`, `/public/ask`, `/admin`, `/admin/ingest`, `/login`, and
  `/professional` passed at 375, 768, and 1440px with no horizontal overflow or
  runtime overlay. Public cancellation was confirmed to abort its `AbortSignal`.
- axe-core 4.12.1 WCAG A/AA: zero violations and zero incomplete checks on the
  Public/Admin mobile and desktop verification states.
- Screenshots: `public/screenshots/phase5/` contains slow, timeout, and network
  states plus the current 375px abortable-timeout state;
  `admin/screenshots/phase5/` contains current service-down, timeout-cancelled,
  and 3-file partial-failure states.
