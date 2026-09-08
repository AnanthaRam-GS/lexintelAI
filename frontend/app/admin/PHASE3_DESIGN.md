# LegalAI Phase 3 — Admin Mode Design

## Status and scope

This design is approved for Phase 3 on `feat/phase3-admin-mode-gugan`, based on
`origin/main` commit `4ea1c75968c99d46cb324380c694c3e174269fa1`.

Owned implementation paths are limited to:

- `frontend/app/admin/**`
- `frontend/lib/mocks/adminIngestion.ts`

Phase 1 shared components are read-only. Backend, data, models, notebooks,
authentication, and `frontend/lib/api.ts` are out of scope.

The approved visual direction is **Guided editorial operations**: a calm,
authoritative admin surface that preserves LegalAI's editorial character while
making system health, permanent-corpus safeguards, and ingestion progress easy
to scan.

## Product intent

Admin Mode is the deliberate entry point for adding documents permanently to
LegalAI's shared corpus. It must never resemble the temporary document-analysis
flows in Public or Professional Mode. The interface therefore explains the
permanent effect before file selection and requires an explicit confirmation
before submission.

The status page provides a concise operational view rather than a broad admin
suite. The ingestion page supports a complete multi-PDF batch workflow and a
persistent job ledger without adding unrelated navigation, analytics, or
authentication work.

## Route protection boundary

Route protection belongs to Ravindran's Task `2.V.2`. No duplicate client-side
or server-side authorization check will be introduced in this phase.

If no guard is present when implementation begins, both route page files must
include this visible top-level comment:

```ts
// TODO(auth): route guard pending 2.V.2
```

The comment is coordination documentation only and must not be replaced by a
competing mock guard.

## Visual system

The implementation uses the merged Phase 1 tokens, fonts, focus treatment,
semantic colors, borders, radii, shadows, and motion. It introduces no new
colors or fonts.

The composition favors open regions and thin separators over a repetitive
bento-card grid:

- refined editorial headings establish hierarchy;
- crisp sans-serif UI text supports operational scanning;
- true white or the existing neutral page background remains dominant;
- semantic healthy, degraded, and down colors appear with an icon and written
  label, never as color alone; and
- decoration is restrained: no gradients, glows, stock imagery, invented
  metrics, or marketing-style hero treatment.

The approved generated concepts are visual references. All controls, text,
health states, forms, and job states remain code-native. The job presentation
uses the existing `IngestionProgress` component exactly as merged even where
the concept's illustrative timeline differs.

## `/admin` — system status

### Composition

The page contains:

- a simple Admin context header;
- the primary heading “System status”;
- a manual “Refresh status” action;
- a prominent Corpus region showing total documents, document-type breakdown,
  and last ingestion date;
- a distinct ChromaDB health region;
- a distinct PostgreSQL health region;
- a fourth clearly separated ingestion action region linking to
  `/admin/ingest`.

The corpus summary is the primary visual anchor. Service-health regions are
compact operational summaries rather than equally weighted decorative cards.

### Loading, refresh, and errors

`fetchCorpusStatsMock` runs on mount. The initial pending state uses the shared
`LoadingSpinner`. A failed initial load uses the shared `ErrorMessage` with
`variant="banner"` and a Retry action.

Manual refresh is the only recurring status update required in Phase 3. The
refresh action is disabled while a request is pending so overlapping fetches
cannot race. No silent auto-refresh loop is introduced.

Thrown values and private mock details are converted to fixed, user-safe copy
before rendering. Raw error objects, stack traces, paths, provider messages,
and database details never enter visible or accessible text.

### Health states

Both service fields use the contract union `healthy | degraded | down` with an
optional user-safe detail string. Each state is communicated through:

- a semantic Phase 1 color;
- a recognizable icon;
- the written label “Healthy”, “Degraded”, or “Down”; and
- optional safe explanatory text when supplied.

## `/admin/ingest` — permanent corpus ingestion

### Desktop composition

At wide desktop sizes the screen uses two coordinated work regions:

- the wider left region prepares the batch: permanent-corpus explanation,
  shared PDF dropzone, per-file metadata, explicit confirmation, and submit;
- the right region is a newest-first persistent job ledger rendered with the
  shared `IngestionProgress` component.

The ledger remains visible beside batch preparation so an administrator can
monitor existing jobs while arranging another batch.

### File selection and metadata

The shared `UploadDropzone` is configured with:

```tsx
multiple={true}
accept="application/pdf"
```

Each selected file receives an independent metadata row with:

- its display filename;
- a required document-type selector;
- an optional free-text note; and
- a remove action.

The provisional selector values are `judgment`, `statute`, and `other`, matching
the Phase 3 prompt but not yet confirmed against the live documents-table
contract. The selector definition must carry this visible comment:

```ts
// TODO(contract): confirm doc_type values with Ananthu/Roshinee before treating
// judgment | statute | other as the live documents-table contract.
```

The Phase 3 PR description must also state that these values need a 30-second
confirmation with Ananthu/Roshinee before being treated as final. Shipping the
mock options does not establish the backend contract.

Metadata is keyed by a route-local stable file identifier rather than filename
alone so two distinct files with the same display name cannot overwrite one
another's selections.

### Validation and permanent-action safeguard

No file may be submitted without a valid document type. Every incomplete file
is identified beside its own row.

The confirmation region states the current file count, for example:

> 2 files will be permanently added to the shared corpus.

The administrator must deliberately confirm understanding of the permanent
update. “Start ingestion” remains disabled unless all of these conditions are
true in the current render:

- at least one PDF is selected;
- every selected file has valid required metadata;
- no submission is already pending; and
- the permanent-update confirmation is active.

Removing a file updates the validation result, confirmation count, and submit
eligibility synchronously from the next state calculation. In particular, when
the only invalid file is removed and every remaining file is valid, “Start
ingestion” becomes enabled in that same resulting render; it must not depend on
an effect, timer, or later render cycle.

Adding or replacing files expands or changes the permanent action and therefore
clears confirmation. Removing a file only narrows the already-confirmed action,
so an active confirmation is preserved while its visible file count updates.
This makes the required invalid-file-removal transition synchronous: if the
removed file was the only invalid file, the remaining batch has valid metadata,
and confirmation was already active, “Start ingestion” is enabled in that same
resulting render.

### Submission behavior

Submission sends the current files and aligned metadata through
`submitIngestionMock`. The mock returns one job ID per file. New jobs are added
to the ledger newest first and begin independent polling.

The selected `File` objects and metadata notes exist only in React memory. They
are released after a successful submission and are never written to browser
storage. If batch submission itself fails, the batch remains selected so the
administrator can retry without re-entering metadata.

### Polling lifecycle

Every non-terminal job is polled independently through
`pollIngestionStatusMock(jobId)` approximately every 2.5 seconds.

- A successful poll replaces that job's current state by stable ID.
- One job's failure or completion does not stop other jobs.
- Polling for a specific job stops immediately after `COMPLETED` or `FAILED`.
- Timers are cleared on unmount.
- Repeated callbacks cannot resurrect a removed or terminal polling loop.
- Active and terminal jobs remain ordered newest first within the mounted
  session.

The mock progression is deterministic under test control so every stage and
the failure branch can be verified reliably. Production-shaped callers retain
the required endpoint-equivalent signatures.

### Safe job failures

Jobs use the exact shared ingestion stages:

```text
QUEUED | EXTRACTING | CHUNKING | EMBEDDING | INDEXING | COMPLETED | FAILED
```

The stage type is imported from the Phase 1 shared component contract rather
than redefined. The mock's exported `IngestionJob` aliases or extends the shared
shape without creating a competing stage enum.

Failed jobs are rendered through the existing `IngestionProgress` failure UI.
The only stored or returned error strings are fixed and user-safe, for example:

> This file could not be processed. Review the file and try again.

No raw exception message, response body, SQL/Chroma detail, stack trace,
filesystem path, or file content is placed in job state, visible DOM, or
accessibility text.

## Refresh persistence

`sessionStorage` is a mock-phase stand-in for backend-driven job-list
rehydration. It is not a durable job database or source of truth.

The stored record contains only:

```ts
type PersistedIngestionJob = {
  id: string;
  filename: string;
  stage: IngestionStage;
};
```

The storage mechanism must never contain:

- `File` objects or file bytes;
- file contents or extracted text;
- metadata notes or document type;
- progress values;
- error strings;
- corpus data; or
- any other field.

Storage read/write code must carry this removal comment:

```ts
// TODO(contract): mock-phase sessionStorage rehydration stand-in. Delete this
// mechanism when the backend job-listing endpoint exists; do not leave it as
// dead fallback code.
```

Only non-terminal records remain in storage. On page mount:

1. read and defensively validate the minimal stored records;
2. show them as initial placeholders, deriving temporary progress from stage;
3. immediately call `pollIngestionStatusMock` for every stored job ID; and
4. replace each placeholder with the live mock/endpoint result.

Stored stage and derived progress are never authoritative after mount. When a
job reaches `COMPLETED` or `FAILED`, its storage entry is removed immediately.
The terminal row remains visible in React state for the rest of the current
mounted session, then disappears after a later refresh because it is no longer
persisted. Malformed or disallowed stored fields are ignored and normalized
back to the minimal record shape, preventing unbounded or unsafe accumulation.

All mock endpoint calls and mock-only persistence helpers remain centralized in
`frontend/lib/mocks/adminIngestion.ts`, preserving one replacement boundary for
the future `1.R.2` API integration.

## Responsive behavior

- At 1440 px, `/admin/ingest` uses the approved two-column workspace and
  `/admin` gives the corpus summary visual priority.
- At 768 px, both routes become a single readable column without horizontal
  scrolling. Batch preparation precedes the job ledger.
- At 375 px, actions stack, metadata controls use the available width,
  filenames truncate without obscuring remove controls, and all interactive
  targets remain at least 44×44 px.
- Content stays in document flow; no sticky element may cover job rows, errors,
  confirmation controls, or mobile browser controls.

## Accessibility

- Semantic landmarks and heading order describe both routes.
- All form controls have visible and programmatic labels.
- File-specific validation is associated with the corresponding row.
- Health never relies on color alone.
- Existing shared loading, error, dropzone, and progress semantics are reused.
- Keyboard focus remains visible and follows a logical order.
- Pending and terminal job updates are announced without repeatedly announcing
  unchanged rows.
- Reduced-motion preferences are honored by any transition used.

## Mock contract and swap boundary

`frontend/lib/mocks/adminIngestion.ts` is the single Phase 3 mock authority for:

- `CorpusStats`;
- the shared-compatible `IngestionJob` type;
- `fetchCorpusStatsMock(): Promise<CorpusStats>`;
- `submitIngestionMock(files, metadata[]): Promise<{ jobIds: string[] }>`;
- `pollIngestionStatusMock(jobId): Promise<IngestionJob>`; and
- the narrowly scoped mock rehydration helpers described above.

One prominent TODO block must explain that the three endpoint mocks are deleted
and replaced by `frontend/lib/api.ts` calls when dependency `1.R.2` is live.
Route callers consume them through this single boundary so live integration
does not require redesigning route state or rendering.

## Test and verification strategy

Implementation follows test-first behavior development. Coverage includes:

- exact corpus and service-health contract shapes;
- all healthy, degraded, and down icon-plus-text states;
- initial loading, refresh disablement, failure banner, and Retry;
- multi-PDF selection and independent metadata keyed safely per file;
- incomplete-file identification and submit disablement;
- **removing the only invalid file makes the remaining batch valid and enables
  “Start ingestion” in that same resulting render, with no effect/timer cycle**;
- permanent confirmation clears when files are added or replaced and remains
  active when the already-confirmed batch only shrinks;
- submit remains blocked until every condition is satisfied;
- successful batch submission creates aligned job IDs and clears file/metadata
  memory;
- failed batch submission preserves the selected batch for Retry;
- independent 2.5-second polling and stable newest-first updates;
- polling stops per terminal job and every timer is cleaned up;
- deterministic active, completed, and failed job branches;
- fixed safe failure copy with no raw error detail;
- refresh placeholders are immediately re-polled and replaced;
- terminal entries are removed from storage but remain visible in the mounted
  session;
- storage contains exactly ID, display filename, and stage—never progress,
  errors, document type, notes, `File` objects, bytes, or contents;
- malformed stored data is handled safely; and
- the provisional document-type TODO remains visible until the backend contract
  is confirmed.

Before delivery, run a clean install, full tests, lint, production build, and
format check. In a real browser, verify both routes at 375, 768, and 1440 px,
including loading, error/Retry, every health state, metadata validation,
single-invalid-file removal, permanent confirmation, submission failure,
mixed concurrent stages, completion, safe failure, refresh rehydration,
keyboard navigation, focus, overflow, console output, and automated WCAG A/AA
checks.

After implementation review, run `docs/POST_PHASE_VERIFICATION_GATE.md` as an
independent post-phase gate. Any blocker triggers repair followed by the entire
gate again before delivery.

## Delivery

Commit only approved Phase 3 paths, push
`feat/phase3-admin-mode-gugan`, and open an unmerged PR titled:

> feat(frontend): Phase 3 — Admin Mode (/admin, /admin/ingest)

The PR must include the required responsive and state screenshots, verification
results, and these exact notes:

> CorpusStats/IngestionJob mocked pending live 1.R.2 endpoints; single swap
> point in lib/mocks/adminIngestion.ts

> No shared components modified; assumes 2.V.2 route guard for /admin/* — TODO
> left in place if not yet merged

It must additionally flag:

> The provisional document-type values (`judgment`, `statute`, `other`) need a
> 30-second confirmation with Ananthu/Roshinee before they are treated as the
> live documents-table contract.

Do not merge the PR.
