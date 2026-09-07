# LegalAI Phase 2 Public Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a jargon-free `/public` landing page and session-only `/public/ask` conversation that accepts one text question or one temporary PDF per turn and renders safe mock answers through the Phase 1 public `ResponseCard`.

**Architecture:** A route-local provider carries one pending landing input through client navigation without storage or URL leakage. The ask page owns a reducer-driven thread and calls a single route-local query-client boundary backed by `frontend/lib/mocks/publicQuery.ts`; a pure adapter maps the public contract into existing `ResponseCard` props.

**Tech Stack:** Next.js 16.3.4 App Router, React 19.2.8, TypeScript 6.0.3, Tailwind CSS 4.3.3, Vitest 4.1.11, Testing Library, existing Phase 1 shared components.

**Spec:** `frontend/app/public/PHASE2_DESIGN.md`

## Global Constraints

- Work only on `feat/phase3-public-mode-gugan`, based on `origin/main` commit `d2ceacdc7f304daebb0aa4d2295a5a0b86fb3487`.
- Modify only `frontend/app/public/**` and `frontend/lib/mocks/publicQuery.ts`.
- Do not modify or copy anything under `frontend/components/shared/**`.
- Do not create or modify `frontend/lib/api.ts`.
- Do not touch backend, data, models, notebooks, authentication, or dependency/configuration files.
- Use only Phase 1 design tokens, shared components, fonts, colors, focus treatment, radii, shadows, and motion.
- Use no localStorage, sessionStorage, `window.storage`, cookies, URL-carried questions, or server persistence.
- Text and PDF are alternative turn inputs and are never combined.
- A full page reload intentionally clears the pending handoff and conversation.
- Never render raw thrown errors, backend/provider details, stack traces, file paths, file contents, confidence, or internal metadata.
- Keep the final PR open and unmerged.

---

## File map

- `frontend/lib/mocks/publicQuery.ts` — sole public mock input/response type authority, deterministic test controls, latency/failure mock.
- `frontend/app/public/query-client.ts` — the one import swap boundary consumed by route code.
- `frontend/app/public/response-adapter.ts` — pure conversion from `PublicQueryResponse` to public `ResponseCardProps`.
- `frontend/app/public/PublicSessionProvider.tsx` — in-memory pending landing-input handoff only.
- `frontend/app/public/layout.tsx` — installs the route-local provider.
- `frontend/app/public/PublicLanding.tsx` — interactive Guided Editorial landing experience.
- `frontend/app/public/page.tsx` — `/public` route metadata and shell.
- `frontend/app/public/ask/chat-model.ts` — exact `ChatMessage` union, stable envelope, reducer state/actions.
- `frontend/app/public/ask/PublicAsk.tsx` — thread, alternative-mode composer, requests, retry, focus, and confirmation.
- `frontend/app/public/ask/page.tsx` — `/public/ask` route metadata and shell.
- Co-located `*.test.ts` / `*.test.tsx` files — behavior regressions.
- `frontend/app/public/screenshots/**` — final required landing/chat/error/empty evidence.

---

### Task 1: Public query contract, mock, and ResponseCard adapter

**Files:**

- Create: `frontend/lib/mocks/publicQuery.ts`
- Create: `frontend/app/public/query-client.ts`
- Create: `frontend/app/public/response-adapter.ts`
- Test: `frontend/app/public/response-adapter.test.ts`
- Test: `frontend/app/public/query-client.test.ts`

**Interfaces:**

- Produces: `PublicQueryInput`, `PublicQueryResponse`, `configurePublicQueryMockForTests`, `resetPublicQueryMockForTests`, `fetchPublicQueryMock(input): Promise<PublicQueryResponse>`, `fetchPublicQuery`, and `toPublicResponseCardProps(response): ResponseCardProps`.
- Consumes: `ResponseCardProps` from `frontend/components/shared` without modifying it.

- [ ] **Step 1: Write failing contract and adapter tests**

```ts
it('maps only plain public fields into ResponseCard public mode', () => {
  const props = toPublicResponseCardProps(responseFixture);
  expect(props.mode).toBe('public');
  expect(props.content.paragraphs).toEqual([responseFixture.explanation]);
  expect(props.content.keyPoints).toEqual([responseFixture.nextStepGuidance]);
  expect(props.sections[0]).not.toHaveProperty('confidence');
  expect(props.citations[0]).toEqual({
    title: responseFixture.sources[0].title,
    sourceUrl: responseFixture.sources[0].link,
  });
});

it('supports deterministic latency and failure without changing the call shape', async () => {
  configurePublicQueryMockForTests({ delayMs: 0, failNext: true });
  await expect(fetchPublicQueryMock({ kind: 'text', content: 'Help me' })).rejects.toThrow();
  resetPublicQueryMockForTests();
});
```

- [ ] **Step 2: Run the focused tests and confirm RED**

```bash
cd frontend
npm run test:run -- app/public/query-client.test.ts app/public/response-adapter.test.ts
```

Expected: FAIL because the mock contract, boundary, and adapter do not exist.

- [ ] **Step 3: Implement the unique mock contract**

```ts
export type PublicQueryInput = { kind: 'text'; content: string } | { kind: 'file'; file: File };

export interface PublicQueryResponse {
  explanation: string;
  sections: Array<{ title: string; explanation: string; link: string }>;
  sources: Array<{ title: string; link: string }>;
  nextStepGuidance: string;
}

// TODO(contract): confirm against backend/app/models/ and delete this mock once
// POST /query/public is exposed through frontend/lib/api.ts. Consumers must then
// change only the query-client import, not their state shape or rendering logic.
export async function fetchPublicQueryMock(input: PublicQueryInput): Promise<PublicQueryResponse> {
  // Validate the discriminant, wait 800–1500 ms by default, optionally reject,
  // and return a public-only fixture derived from the input kind.
}
```

Test controls remain exported only to tests, reset after each test, and do not
change the production-shaped one-argument request function.

- [ ] **Step 4: Implement the one-line client boundary and pure adapter**

```ts
export {
  fetchPublicQueryMock as fetchPublicQuery,
  type PublicQueryInput,
  type PublicQueryResponse,
} from '../../lib/mocks/publicQuery';
```

```ts
export function toPublicResponseCardProps(response: PublicQueryResponse): ResponseCardProps {
  return {
    mode: 'public',
    content: {
      heading: 'What this may mean for you',
      paragraphs: [response.explanation],
      keyPoints: [response.nextStepGuidance],
    },
    sections: response.sections.map((item) => ({
      code: '',
      section: '',
      title: item.title,
      explanation: item.explanation,
      sourceUrl: item.link,
    })),
    citations: response.sources.map((item) => ({
      title: item.title,
      sourceUrl: item.link,
    })),
  };
}
```

- [ ] **Step 5: Run focused tests and confirm GREEN**

```bash
cd frontend
npm run test:run -- app/public/query-client.test.ts app/public/response-adapter.test.ts
```

Expected: both files pass; no public object contains confidence or internal metadata.

- [ ] **Step 6: Commit Task 1**

```bash
git add frontend/lib/mocks/publicQuery.ts frontend/app/public/query-client.ts frontend/app/public/query-client.test.ts frontend/app/public/response-adapter.ts frontend/app/public/response-adapter.test.ts
git commit -m "feat(public): add mock query contract boundary"
```

---

### Task 2: In-memory landing handoff and Guided Editorial landing page

**Files:**

- Create: `frontend/app/public/PublicSessionProvider.tsx`
- Create: `frontend/app/public/PublicSessionProvider.test.tsx`
- Create: `frontend/app/public/PublicLanding.tsx`
- Create: `frontend/app/public/PublicLanding.test.tsx`
- Create: `frontend/app/public/layout.tsx`
- Create: `frontend/app/public/page.tsx`

**Interfaces:**

- Consumes: `PublicQueryInput` from `query-client.ts`; Phase 1 `UploadDropzone`.
- Produces: `usePublicSession()` with `pendingInput`, `setPendingInput`, and `takePendingInput`.

- [ ] **Step 1: Write failing provider and landing tests**

```tsx
it('carries one text input through memory and consumes it once', async () => {
  render(<ProviderHarness />);
  await user.click(screen.getByRole('button', { name: 'Set text' }));
  expect(screen.getByText('text:My landlord kept my deposit')).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Consume' }));
  expect(screen.getByText('none')).toBeInTheDocument();
});

it('submits plain text to the ask route without placing it in the URL', async () => {
  render(<PublicLanding />, { wrapper: TestPublicSessionProvider });
  await user.type(screen.getByLabelText('Your question'), 'Can my employer keep my pay?');
  await user.click(screen.getByRole('button', { name: 'Ask your question' }));
  expect(setPendingInput).toHaveBeenCalledWith({
    kind: 'text',
    content: 'Can my employer keep my pay?',
  });
  expect(push).toHaveBeenCalledWith('/public/ask');
});
```

Add assertions for exact jargon-free copy, no login/professional navigation,
three examples, disclaimer, upload reveal, valid single-PDF handoff, and no
empty submission.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
cd frontend
npm run test:run -- app/public/PublicSessionProvider.test.tsx app/public/PublicLanding.test.tsx
```

Expected: FAIL because provider and landing modules do not exist.

- [ ] **Step 3: Implement the route-local provider and layout**

```tsx
const PublicSessionContext = createContext<PublicSessionValue | null>(null);

export function PublicSessionProvider({ children }: PropsWithChildren) {
  const [pendingInput, setPendingInput] = useState<PublicQueryInput | null>(null);
  const pendingInputRef = useRef<PublicQueryInput | null>(null);
  const storePendingInput = useCallback((input: PublicQueryInput) => {
    pendingInputRef.current = input;
    setPendingInput(input);
  }, []);
  const takePendingInput = useCallback(() => {
    const input = pendingInputRef.current;
    pendingInputRef.current = null;
    setPendingInput(null);
    return input;
  }, []);
  return (
    <PublicSessionContext.Provider
      value={{ pendingInput, setPendingInput: storePendingInput, takePendingInput }}
    >
      {children}
    </PublicSessionContext.Provider>
  );
}
```

The ref-backed `takePendingInput()` must be Strict Mode safe and covered by the
consume-once test; no module-global state may carry a user's question or file.

- [ ] **Step 4: Implement the approved landing composition**

Use semantic landmarks, exact approved copy, Phase 1 token utilities, and the
existing `UploadDropzone`. The upload action reveals the dropzone; selecting one
valid PDF calls `setPendingInput({ kind: 'file', file })` then
`router.push('/public/ask')`.

- [ ] **Step 5: Run focused tests and confirm GREEN**

```bash
cd frontend
npm run test:run -- app/public/PublicSessionProvider.test.tsx app/public/PublicLanding.test.tsx
```

Expected: provider and landing tests pass.

- [ ] **Step 6: Commit Task 2**

```bash
git add frontend/app/public/PublicSessionProvider.tsx frontend/app/public/PublicSessionProvider.test.tsx frontend/app/public/PublicLanding.tsx frontend/app/public/PublicLanding.test.tsx frontend/app/public/layout.tsx frontend/app/public/page.tsx
git commit -m "feat(public): add guided public landing page"
```

---

### Task 3: Conversation model and alternative-input composer

**Files:**

- Create: `frontend/app/public/ask/chat-model.ts`
- Create: `frontend/app/public/ask/chat-model.test.ts`
- Create: `frontend/app/public/ask/PublicAsk.tsx`
- Create: `frontend/app/public/ask/PublicAsk.test.tsx`
- Create: `frontend/app/public/ask/page.tsx`

**Interfaces:**

- Consumes: `usePublicSession`, `PublicQueryInput`, Phase 1 `UploadDropzone`.
- Produces: exact `ChatMessage`, `ChatEntry`, `ChatState`, `chatReducer`, and the interactive ask route.

- [ ] **Step 1: Write failing reducer and composer tests**

```ts
it('keeps the required ChatMessage union in stable entry envelopes', () => {
  const state = chatReducer(initialChatState, {
    type: 'append-user',
    entry: { id: 'turn-1-user', message: { role: 'user', kind: 'text', content: 'Help me' } },
  });
  expect(state.entries[0].id).toBe('turn-1-user');
});
```

```tsx
it('makes text and PDF visibly alternative modes', async () => {
  renderAsk();
  await user.type(screen.getByLabelText('Your question'), 'Help me understand this');
  expect(screen.getByText('Active input: Text question')).toBeInTheDocument();
  await selectPdf('notice.pdf');
  expect(screen.getByLabelText('Your question')).toHaveValue('');
  expect(screen.getByText('Active input: Temporary PDF')).toBeInTheDocument();
});
```

Add tests for three empty examples, PDF-to-text clearing/remount, Enter submit,
Shift+Enter newline, whitespace rejection, and disabled switching while pending.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
cd frontend
npm run test:run -- app/public/ask/chat-model.test.ts app/public/ask/PublicAsk.test.tsx
```

Expected: FAIL because the chat model and ask page do not exist.

- [ ] **Step 3: Implement the reducer model**

```ts
export type ChatMessage =
  | { role: 'user'; kind: 'text'; content: string }
  | { role: 'user'; kind: 'file'; fileName: string }
  | { role: 'assistant'; response: PublicQueryResponse }
  | { role: 'assistant'; kind: 'error'; error: string };

export interface ChatEntry {
  id: string;
  message: ChatMessage;
}
```

Reducer actions append user/assistant entries, remove an error before retry, and
clear the complete thread. Stable IDs come from a route-local monotonic ref or
`crypto.randomUUID()` at event time, never during render.

- [ ] **Step 4: Implement empty state and alternative-mode composer**

Render the approved ask shell. Maintain `draft`, `selectedFile`, `uploadKey`,
and derived `activeMode`. File selection clears the draft. Typing clears the
file and increments `uploadKey` so the shared uncontrolled selection remounts.
Display “Active input: Text question”, “Active input: Temporary PDF”, or
“Choose text or one PDF”.

- [ ] **Step 5: Run focused tests and confirm GREEN**

```bash
cd frontend
npm run test:run -- app/public/ask/chat-model.test.ts app/public/ask/PublicAsk.test.tsx
```

Expected: reducer and composer behavior passes without storage APIs.

- [ ] **Step 6: Commit Task 3**

```bash
git add frontend/app/public/ask/chat-model.ts frontend/app/public/ask/chat-model.test.ts frontend/app/public/ask/PublicAsk.tsx frontend/app/public/ask/PublicAsk.test.tsx frontend/app/public/ask/page.tsx
git commit -m "feat(public): add session-only conversation composer"
```

---

### Task 4: Request lifecycle, response rendering, safe error, and exact Retry

**Files:**

- Modify: `frontend/app/public/ask/PublicAsk.tsx`
- Modify: `frontend/app/public/ask/PublicAsk.test.tsx`

**Interfaces:**

- Consumes: `fetchPublicQuery`, `toPublicResponseCardProps`, `LoadingSpinner`, `ErrorMessage`, `ResponseCard`.
- Produces: serialized request lifecycle with retained exact-turn retry input.

- [ ] **Step 1: Add failing lifecycle tests**

```tsx
it('keeps prior turns visible while an inline assistant loading row is pending', async () => {
  requestDeferred.resolveLater();
  await submitText('Can my employer keep my final pay?');
  expect(screen.getByText('Can my employer keep my final pay?')).toBeInTheDocument();
  expect(screen.getByRole('status', { name: 'Finding a clear answer' })).toBeInTheDocument();
});

it('retries the exact failed turn without duplicating its user message', async () => {
  fetchPublicQuery.mockRejectedValueOnce(new Error('/private/path database timeout'));
  await submitText('What can I do?');
  expect(screen.queryByText('/private/path database timeout')).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Retry' }));
  expect(fetchPublicQuery).toHaveBeenNthCalledWith(2, { kind: 'text', content: 'What can I do?' });
  expect(screen.getAllByText('What can I do?')).toHaveLength(1);
});
```

Add successful text/PDF response, public ResponseCard, no confidence/internal
metadata, one request at a time, and consumed landing-input auto-submit tests.

- [ ] **Step 2: Run the ask test and confirm RED**

```bash
cd frontend
npm run test:run -- app/public/ask/PublicAsk.test.tsx
```

Expected: lifecycle assertions fail before request logic exists.

- [ ] **Step 3: Implement one serialized submit function**

```ts
const submitInput = async (input: PublicQueryInput, appendUser = true) => {
  if (requestRef.current) return;
  if (appendUser) dispatch({ type: 'append-user', entry: toUserEntry(input) });
  requestRef.current = input;
  setRequestStatus('loading');
  try {
    const response = await fetchPublicQuery(input);
    dispatch({ type: 'append-assistant', entry: toAssistantEntry(response) });
    requestRef.current = null;
    setRequestStatus('idle');
  } catch {
    dispatch({ type: 'append-error', entry: safeErrorEntry() });
    setRequestStatus('error');
  }
};
```

Use mounted/request-generation guards so late promises cannot repopulate a newly
cleared conversation. Retry removes the visible error, keeps the exact retained
input, and calls `submitInput(retained, false)`.

- [ ] **Step 4: Render shared loading/error/response components**

Use inline `LoadingSpinner`, inline `ErrorMessage`, and `ResponseCard` with the
pure adapter. Never interpolate the caught value. Preserve previous turns.

- [ ] **Step 5: Run lifecycle tests and confirm GREEN**

```bash
cd frontend
npm run test:run -- app/public/ask/PublicAsk.test.tsx
```

Expected: text, PDF, loading, success, failure, safe copy, and exact Retry pass.

- [ ] **Step 6: Commit Task 4**

```bash
git add frontend/app/public/ask/PublicAsk.tsx frontend/app/public/ask/PublicAsk.test.tsx
git commit -m "feat(public): wire mock answers and exact-turn retry"
```

---

### Task 5: New-conversation threshold, focus, and scroll behavior

**Files:**

- Modify: `frontend/app/public/ask/PublicAsk.tsx`
- Modify: `frontend/app/public/ask/PublicAsk.test.tsx`

**Interfaces:**

- Consumes: reducer clear action and request-generation guard.
- Produces: locked 0–1 immediate clear, 2+ confirmation, cancellation, focus restoration, and latest-entry scrolling.

- [ ] **Step 1: Add failing confirmation/focus/scroll tests**

```tsx
it.each([0, 1])('clears %i messages immediately without confirmation', async (count) => {
  renderAskWithMessages(count);
  await user.click(screen.getByRole('button', { name: 'Start New Conversation' }));
  expect(
    screen.queryByRole('region', { name: 'Confirm new conversation' }),
  ).not.toBeInTheDocument();
  expect(screen.getByLabelText('Your question')).toHaveFocus();
});

it('requires confirmation at two messages and Cancel preserves the thread', async () => {
  renderAskWithMessages(2);
  await user.click(screen.getByRole('button', { name: 'Start New Conversation' }));
  expect(screen.getByRole('region', { name: 'Confirm new conversation' })).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Keep conversation' }));
  expect(screen.getAllByTestId('chat-entry')).toHaveLength(2);
});
```

Add confirmed-clear, late-response cancellation, focus return, and
`scrollIntoView` calls after new thread content.

- [ ] **Step 2: Run the ask test and confirm RED**

```bash
cd frontend
npm run test:run -- app/public/ask/PublicAsk.test.tsx
```

Expected: threshold/confirmation/focus assertions fail.

- [ ] **Step 3: Implement the exact threshold and accessible confirmation**

Zero or one entry calls `clearConversation()` immediately. Two or more entries
show an inline labelled region with “Keep conversation” and “Start fresh”.
Cancel restores focus to the initiating button; confirm invalidates the active
request generation, clears all state, and focuses the textarea.

- [ ] **Step 4: Implement reduced-motion-aware latest-entry scrolling**

```ts
useEffect(() => {
  latestEntryRef.current?.scrollIntoView({
    block: 'nearest',
    behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
  });
}, [entries.length, requestStatus]);
```

Guard `matchMedia` in tests and avoid stealing focus during ordinary updates.

- [ ] **Step 5: Run all Public Mode tests and confirm GREEN**

```bash
cd frontend
npm run test:run -- app/public
```

Expected: all Public Mode unit/integration tests pass.

- [ ] **Step 6: Commit Task 5**

```bash
git add frontend/app/public/ask/PublicAsk.tsx frontend/app/public/ask/PublicAsk.test.tsx
git commit -m "test(public): lock conversation reset and focus flows"
```

---

### Task 6: Full verification, screenshots, scope audit, push, and PR

**Files:**

- Create: `frontend/app/public/screenshots/public-landing-desktop.png`
- Create: `frontend/app/public/screenshots/public-landing-mobile.png`
- Create: `frontend/app/public/screenshots/public-chat-active.png`
- Create: `frontend/app/public/screenshots/public-chat-error.png`
- Create: `frontend/app/public/screenshots/public-chat-empty.png`
- Modify only evidence-driven files under `frontend/app/public/**` when a verified defect requires repair.

**Interfaces:**

- Consumes: completed Public Mode routes and local `docs/POST_PHASE_VERIFICATION_GATE.md`.
- Produces: verified branch, committed screenshots, pushed remote branch, open unmerged PR, independent gate report.

- [ ] **Step 1: Run a clean dependency install and full automated gates**

```bash
cd frontend
node --version
npm --version
npm ci
npm run test:run
npm run lint
npm run build
npm run format:check
```

Expected: zero failures/errors. Record every warning without suppressing it.

- [ ] **Step 2: Run security, contract, and scope searches**

```bash
git diff --name-status origin/main...HEAD
git diff --unified=0 origin/main...HEAD -- '*.ts' '*.tsx' | rg 'localStorage|sessionStorage|window\.storage|dangerouslySetInnerHTML|api[_-]?key|bearer|stack|exception'
rg -n 'interface PublicQueryResponse|type PublicQueryResponse' frontend/app/public frontend/lib/mocks/publicQuery.ts
rg -n 'from .*publicQuery|from .*query-client' frontend/app/public frontend/lib/mocks/publicQuery.ts
test ! -e frontend/lib/api.ts
git diff --exit-code origin/main...HEAD -- frontend/components/shared backend data models notebooks
```

Expected: only allowed paths; one response definition; route consumers use the
boundary; storage/unsafe searches have no unsafe production match; frozen paths unchanged.

- [ ] **Step 3: Verify real-browser flows at 1440, 768, and 375 px**

At both routes exercise landing text handoff, landing PDF handoff, empty state,
examples, alternative-mode switching, text success, PDF success, loading with
prior turns, induced failure, exact Retry, 0–1 immediate clear, 2+ confirmation
Cancel/Confirm, Enter/Shift+Enter, focus, reduced motion, console, and reload
clearing. Measure overflow/clipping and 44 px mobile targets. Run WCAG A/AA axe
checks at desktop and mobile.

- [ ] **Step 4: Capture and inspect required screenshots**

Capture landing desktop/mobile, active chat, error, and empty chat. Inspect each
image at native size against the approved Guided Editorial composition and Phase
1 token system. Do not commit browser chrome or framework overlays.

- [ ] **Step 5: Commit verified visual evidence**

```bash
git add frontend/app/public/screenshots frontend/app/public
git diff --cached --check
git commit -m "test(public): add verified responsive evidence"
```

- [ ] **Step 6: Run the independent post-phase verification gate**

Use `docs/POST_PHASE_VERIFICATION_GATE.md` through Steps 1–7 against the frozen
candidate SHA. A reviewer must inspect actual repo/browser evidence and must not
fix findings. Any blocker returns to a separate test-first repair/review cycle,
followed by a complete gate rerun.

- [ ] **Step 7: Push and open the required PR only after a clean gate**

```bash
git push -u origin feat/phase3-public-mode-gugan
```

Open a PR to `main` titled:

```text
feat(frontend): Phase 2 — Public Mode (/public, /public/ask)
```

Include all required screenshots and these exact notes:

```text
PublicQueryResponse is mocked pending live POST /query/public; single import swap point documented in lib/mocks/publicQuery.ts.
No shared components modified.
```

Include clean test/lint/build/format results and every accepted warning. Confirm
the PR is OPEN, targets `main`, points to the verified head SHA, and remains
unmerged.
