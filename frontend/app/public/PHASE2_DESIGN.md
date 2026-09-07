# LegalAI Phase 2 — Public Mode Design

## Status and scope

This design is approved for Phase 2 on `feat/phase3-public-mode-gugan`, based on
`origin/main` at `d2ceacdc7f304daebb0aa4d2295a5a0b86fb3487`.

Owned implementation paths are limited to:

- `frontend/app/public/**`
- `frontend/lib/mocks/publicQuery.ts`

Phase 1 shared components are read-only. Backend, data, models, notebooks,
authentication, browser persistence, and `frontend/lib/api.ts` are out of scope.

## Product intent

Public Mode is LegalAI's unauthenticated, plain-language surface. It must feel
like a complete and trustworthy product rather than a restricted professional
tool. Visitors may ask a text question or submit one PDF for temporary analysis.
Nothing in the interface may imply that a document or conversation is saved,
stored, or added to the shared corpus.

The approved visual direction is **Guided editorial**: a calm landing page earns
trust before asking for information, and the conversation page prioritizes
readability over dense dashboard chrome.

## Routes and composition

### `/public`

The landing page contains:

- a restrained LegalAI identity with no login or professional-mode navigation;
- the heading “Understand your legal question without the legal jargon.”;
- supporting copy: “Ask in your own words or share one PDF. We explain the
  information clearly and suggest practical next steps.”;
- a prominent question composer;
- an “Upload one PDF” action that reveals the existing Phase 1
  `UploadDropzone`, configured with `multiple={false}` and
  `accept="application/pdf"`;
- three realistic example questions; and
- a short plain-language disclaimer explaining that the service is general
  information and that PDFs are checked once and not stored or added to a
  shared collection.

Submitting a non-empty text question or selecting one valid PDF stores one
pending input in memory and navigates to `/public/ask`.

### `/public/ask`

The ask page contains:

- a persistent conversation header and always-visible “Start New Conversation”
  control;
- a warm zero-message state with three example questions;
- a top-to-bottom message thread;
- user text and temporary-file turns;
- assistant responses rendered only through `ResponseCard mode="public"`;
- a transient inline `LoadingSpinner` while awaiting a result;
- safe inline `ErrorMessage` feedback with exact-turn Retry; and
- a text composer plus a revealed Phase 1 `UploadDropzone` for the alternative
  PDF input mode.

The composer is visually docked on larger screens and remains in normal flow on
small screens so it cannot cover messages or mobile browser controls.

## Session-only handoff and conversation state

`frontend/app/public/layout.tsx` hosts a route-local client provider. It stores
only one pending landing input:

```ts
type PublicQueryInput = { kind: 'text'; content: string } | { kind: 'file'; file: File };
```

The provider exists only to carry the pending input through client navigation.
It does not own the chat history. It uses no URL query, local storage, session
storage, cookie, server action, cache, database, or network persistence. A full
page reload intentionally clears it.

The ask page owns its thread with `useReducer`. The required `ChatMessage` union
is preserved exactly, while a route-local envelope supplies stable render IDs:

```ts
type ChatMessage =
  | { role: 'user'; kind: 'text'; content: string }
  | { role: 'user'; kind: 'file'; fileName: string }
  | { role: 'assistant'; response: PublicQueryResponse }
  | { role: 'assistant'; kind: 'error'; error: string };

type ChatEntry = { id: string; message: ChatMessage };
```

Only one request may be active. The active request retains its exact
`PublicQueryInput`, including the in-memory `File`, until success, retry, or new
conversation cleanup.

## Locked conversation behaviors

### Start New Conversation

- With zero or one message, activation clears immediately with no confirmation.
- With two or more messages, activation opens a simple accessible inline
  confirmation step.
- Cancel preserves the thread and returns focus to the initiating control.
- Confirm clears messages, pending request/file state, error state, and composer
  state, then returns focus to the text input.

### Alternative input modes

Text and PDF are alternative inputs for one turn and are never combined.

- Typing non-whitespace text arms **Text question** mode.
- Choosing “Add one PDF” reveals the existing dropzone. Selecting a valid PDF
  clears the text draft and arms **Temporary PDF** mode.
- Typing after a PDF is selected clears the selected file before arming text
  mode; because the shared dropzone has internal file state, switching away
  remounts it with a new route-local key so its visible selection also clears.
- The composer displays a visible active-mode label before submission.
- Enter submits an armed text turn; Shift+Enter inserts a newline.
- A PDF turn submits when the user activates Send after the file is visibly
  selected. Enter cannot accidentally combine it with text.
- Both modes and mode switching are disabled while a request is pending.

## Mock contract and swap boundary

`frontend/lib/mocks/publicQuery.ts` is the single authority for:

- `PublicQueryInput`;
- `PublicQueryResponse`;
- its simplified section/source types; and
- `fetchPublicQueryMock(input): Promise<PublicQueryResponse>`.

`PublicQueryResponse` contains:

- `explanation: string`;
- `sections`: simplified cited law entries with title, plain explanation, and
  public HTTPS link;
- `sources`: title and public HTTPS link only; and
- `nextStepGuidance: string`.

It contains no confidence score, retrieval metadata, internal identifier, raw
provider response, or backend exception detail.

The mock waits 800–1500 ms. It supports deterministic test configuration while
its production-shaped export retains the one-input call signature. Its default
mock behavior may occasionally reject with a private internal error; the UI
always converts that rejection to fixed safe copy. Tests and browser QA control
the failure branch without changing component logic.

The file includes one prominent comment:

```ts
// TODO(contract): confirm against backend/app/models/ and delete this mock once
// POST /query/public is exposed through frontend/lib/api.ts. Consumers must then
// change only this import, not their state shape or rendering logic.
```

The ask feature imports the request function and contract types through one
route-local boundary module. The future live client must expose the same input
and response shape, allowing an import-only swap.

## ResponseCard adapter

Public Mode does not create another answer renderer. A pure route-local adapter
maps `PublicQueryResponse` into the existing `ResponseCard` props:

- a fixed calm heading plus `explanation` becomes `content`;
- `nextStepGuidance` becomes the public “What you can do” key point;
- simplified cited sections map to `sections` without confidence;
- title/link sources map to `citations` without court, year, excerpt, or
  metadata; and
- `mode` is always `public`.

No shared component is copied or modified.

## Request, loading, error, and retry lifecycle

1. Validate and arm exactly one text or file input.
2. Append one user entry and retain its exact request input.
3. Render a transient assistant loading row while keeping earlier turns visible.
4. Call the single imported public-query function.
5. On success, append one assistant response and release the retained input.
6. On failure, append one assistant error entry with fixed calm copy and retain
   the failed input for Retry.
7. Retry removes/replaces the error state and resends the retained input without
   duplicating the user entry.

Visible failure copy is fixed and safe:

> We couldn't answer that just now. Your question is still here—please try
> again.

Raw errors, stack traces, filesystem/database/provider messages, file contents,
and private paths are never rendered or placed into accessibility text.

## Focus, scrolling, and accessibility

- A semantic heading hierarchy and landmarks describe both pages.
- Every interactive target is at least 44×44 px on mobile.
- Focus indicators use the Phase 1 focus token.
- The latest thread entry scrolls into view after a message or loading-state
  change, respecting reduced-motion preferences.
- Status and error feedback use the semantics already supplied by
  `LoadingSpinner` and `ErrorMessage`.
- Input-mode labels and selected-file status are programmatically available.
- New-conversation confirmation is an accessible inline region with explicit
  Confirm and Cancel buttons; it is not a blocking browser dialog.
- After clearing, focus returns to the text input.
- Empty examples are buttons that populate/arm text without submitting
  unexpectedly.

## Visual system and responsive behavior

All color, typography, radius, shadow, focus, and motion values come from Phase
1 tokens. No new color or font is introduced.

- At 1440 px, content uses a comfortable editorial measure and the ask composer
  may remain docked within the page shell.
- At 768 px, layouts collapse without horizontal scrolling and retain clear
  action separation.
- At 375 px, actions stack when needed, filenames truncate without hiding their
  controls, the composer stays in document flow, and no content is obscured.
- Public responses use the existing roomy public `ResponseCard` branch.

## Test and verification strategy

Implementation follows test-first behavior development. Coverage includes:

- the unique mock contract, input union, latency/failure controls, and safe
  response shape;
- landing text handoff and PDF handoff;
- no empty/whitespace submissions;
- exact alternative-mode transitions and visible active-mode labeling;
- Enter versus Shift+Enter;
- loading visibility without hiding previous turns;
- successful text and file turns;
- safe failure rendering and exact-turn Retry without user-message duplication;
- immediate clearing at zero/one message;
- confirmation, cancellation, confirmed clearing, and focus restoration at two
  or more messages;
- public `ResponseCard` rendering with no confidence/internal metadata;
- absence of localStorage/sessionStorage/window.storage; and
- plain-language copy and required disclaimers.

Before delivery, run a clean install, full tests, lint, production build, and
format check. In a real browser, verify `/public` and `/public/ask` at 375, 768,
and 1440 px across empty, loading, success, file, error/retry, mode-switching,
and new-conversation flows. Run keyboard, focus, overflow, console, and automated
WCAG A/AA checks. Capture landing mobile/desktop, empty conversation, active
thread, and error-state screenshots.

After implementation review, run `docs/POST_PHASE_VERIFICATION_GATE.md` as an
independent gate before finalizing the PR. The local gate document is explicitly
excluded from this Phase 2 PR.

## Delivery

Commit only approved Phase 2 paths, push
`feat/phase3-public-mode-gugan`, and open a PR into `main` titled:

> feat(frontend): Phase 2 — Public Mode (/public, /public/ask)

The PR must include the required screenshots, mock-contract swap note, explicit
confirmation that shared components were not modified, and fresh verification
results. It must remain open and unmerged pending human review.
