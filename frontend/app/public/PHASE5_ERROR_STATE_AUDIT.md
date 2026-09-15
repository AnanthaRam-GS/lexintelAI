# Phase 5 — Public/Admin Error-State Audit

Baseline: `cd3fd2a05821e33f4be2def6084e53d0504a8c2b` (latest `main` when the Phase 5 branch was created).

Final verification: all applicable cells pass. Evidence below references the
Phase 5 candidate source and focused regression tests.

| State                         | `/public` landing                       | `/public/ask` (per turn)                                                                                                                                                 | `/admin` status cards                                                                                                                                   | `/admin/ingest` (per file / per batch)                                                                                                                                        |
| ----------------------------- | --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Initial load / empty          | N/A — static landing has no remote load | PASS — three examples are defined at `PublicAsk.tsx:27` and rendered at `PublicAsk.tsx:555`                                                                              | PASS — per-card initial spinners are rendered by `StatusLoadingRegions` at `AdminStatus.tsx:186`; populated cards replace them at `AdminStatus.tsx:301` | PASS — `IngestionProgress.tsx:94` renders the quiet empty state                                                                                                               |
| Loading (fast, <2s)           | N/A                                     | PASS — `PublicAsk.tsx:586` renders the pending-turn spinner without hiding prior entries                                                                                 | PASS — Corpus, ChromaDB, and PostgreSQL each receive a card spinner; refresh is disabled while pending                                                  | N/A before submission; active rows expose named progress bars at `IngestionProgress.tsx:162`                                                                                  |
| Loading (slow, 2–8s)          | N/A                                     | PASS — the 4-second timer changes only the understated status text to “Still working…”                                                                                   | PASS — the same per-card spinners remain visible until the bounded request settles                                                                      | PASS — `ACTIVE_STAGES` and the one progress map advance active mock jobs through 0/20/40/60/80/100                                                                            |
| Timeout / very slow (>8–10s)  | N/A                                     | PASS — at 9 seconds `PublicAsk.tsx:588` shows distinct long-wait copy plus Keep waiting and Cancel request                                                               | PASS — the 10-second bound produces timeout-specific safe copy and Retry (`AdminStatus.tsx:228–239`)                                                    | PASS — each active job receives a 15-second deadline (`IngestionWorkspace.tsx:34,127`) and becomes FAILED with timeout-specific per-file guidance                             |
| Hard failure (service error)  | N/A                                     | PASS — closed service copy and exact Retry; raw caught values are only classified, never rendered                                                                        | PASS — safe unavailable copy and Retry; backend `service.detail` is not rendered, and status text comes from the closed vocabulary                      | PASS — explicit FAILED states are reduced to a closed reason category at `IngestionWorkspace.tsx:146` and rendered through caller-owned safe copy                             |
| Network loss (client offline) | N/A                                     | PASS — TypeError/offline failures use “Check your connection”; live Chrome network abort verified                                                                        | PASS — a distinct connection message replaces the loading cards and provides Retry                                                                      | PASS — a rejected poll keeps the job active/persisted, shows connection guidance, and retries automatically (`IngestionWorkspace.tsx:155–165`)                                |
| Partial batch failure         | N/A                                     | N/A                                                                                                                                                                      | N/A                                                                                                                                                     | PASS — component test submits 3 files and proves 2 COMPLETED rows remain visible beside 1 actionable FAILED row; live screenshot confirms the same                            |
| Validation failure            | N/A                                     | PASS — empty input keeps Send disabled and the shared PDF validator rejects type/size before fetch                                                                       | N/A                                                                                                                                                     | PASS — upload and per-file document-type errors block submission locally (`IngestionWorkspace.tsx:81–88,386–437`)                                                             |
| Retry                         | N/A                                     | PASS — every failed entry retains its exact in-memory input in `failedInputsRef`; retry removes only that error and never duplicates user text (`PublicAsk.tsx:436–449`) | PASS — manual Retry/Refresh is bounded and non-overlapping                                                                                              | PASS — no single-file retry endpoint exists, so safe file guidance explicitly says to correct and add only that file in a new batch; no misleading whole-batch Retry is shown |
| Recovery                      | N/A                                     | PASS — earlier failures remain visible when a later turn succeeds; any retained failed turn can still be retried                                                         | PASS — the next successful fetch clears the banner and restores healthy cards                                                                           | PASS — a successful poll clears the transient connection banner; terminal failed rows remain visible while later jobs complete                                                |

## Cross-check with Professional Mode

No Professional Mode `4.V.1` implementation or matching error-state commit is
present in this `main` baseline. Phase 5 therefore preserves the existing
shared-component defaults and flags its single additive shared API for review
rather than guessing at an unmerged convention.

## Locked implementation decisions

- All rendered copy comes from `app/public/error-copy.ts`, including Admin copy.
- Raw thrown values, service details, backend failure strings, paths, and stack
  traces are never rendered or placed in accessibility text.
- An offline/rejected ingestion poll keeps the job active and visible while
  automatic polling continues; only an explicit FAILED status or the bounded
  job deadline makes it terminal.
- Because the current ingestion boundary exposes no single-file retry endpoint,
  a failed row tells the admin to correct and re-add that file in a new batch;
  it does not pretend to resubmit the whole batch or provide a misleading Retry.

## Verification evidence

- `npm run test:run`: 19 files, 172 tests passed.
- `npm run lint`: zero warnings/errors.
- `npm run format:check`: pass.
- `npm run build`: compiled, type-checked, and generated all seven routes. The
  existing Node module-type warning for `tailwind.config.ts` remains unchanged.
- Live Chrome: `/public`, `/public/ask`, `/admin`, and `/admin/ingest` passed at
  375, 768, and 1440px with no horizontal overflow or unexpected runtime error.
- axe-core WCAG A/AA: zero violations at 375 and 1440px on all four routes.
  `/public/ask` returned one `color-contrast` incomplete/manual-review item at
  both widths; it was not reported as a violation.
- Screenshots: `public/screenshots/phase5/` contains slow, timeout, and network
  states; `admin/screenshots/phase5/` contains service-down and 3-file partial
  failure states.
