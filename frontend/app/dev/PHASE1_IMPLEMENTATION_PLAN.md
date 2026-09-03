# LegalAI Phase 1 Shared UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scaffold the LegalAI Next.js frontend and deliver five typed, accessible, responsive shared UX components with an interactive preview.

**Architecture:** A strict TypeScript Next.js App Router application owns global design tokens and fonts, while focused stateless components live under `frontend/components/shared`. A client-side preview gallery owns demo state and contract-shaped fixtures; shared components never import an API client or perform network requests.

**Tech Stack:** Next.js 16.3.4, React 19.2.8, TypeScript 7.0.2, Tailwind CSS 4.3.3, Lucide React 1.39.0, Vitest 4.1.11, React Testing Library 16.3.3, user-event 14.6.7, jsdom 30.0.1, ESLint 10.9.1, Prettier 3.9.6

**Spec:** `frontend/app/dev/PHASE1_DESIGN.md`

## Global Constraints

- Work only on `feat/phase3-shared-ux-gugan`; never commit or merge directly to `main`.
- Phase 1 is limited to the scaffold, design system, five shared components, and `/dev/component-preview`.
- Never create or modify `frontend/lib/api.ts`.
- Never modify `backend/`, `data/`, `models/`, or `notebooks/`.
- Ingestion stages are exactly `QUEUED | EXTRACTING | CHUNKING | EMBEDDING | INDEXING | COMPLETED | FAILED`.
- Use design tokens only in components; no ad-hoc hex, RGB, or HSL values.
- The approved theme is light-only, ink navy on warm paper with restrained brass and semantic status colors.
- Support keyboard use, visible focus, reduced motion, plain-language errors, and layouts from 375px upward.
- Preserve distinct Professional and Public `ResponseCard` compositions; Public never displays confidence.
- Every implementation task follows red-green-refactor and ends in a conventional commit.

## File map

- `frontend/package.json`: pinned dependencies and lint, test, build, format scripts.
- `frontend/package-lock.json`: reproducible npm dependency graph.
- `frontend/tsconfig.json`, `frontend/next-env.d.ts`, `frontend/next.config.ts`: strict Next.js/TypeScript setup.
- `frontend/postcss.config.mjs`, `frontend/tailwind.config.ts`: Tailwind integration and semantic utility mapping.
- `frontend/eslint.config.mjs`, `frontend/prettier.config.mjs`, `frontend/.prettierignore`: code-quality configuration.
- `frontend/vitest.config.ts`, `frontend/vitest.setup.ts`: jsdom component-test environment.
- `frontend/app/globals.css`: documented tokens, typography, reset, focus, animation, and shared utility primitives.
- `frontend/app/design-system.test.ts`: guards required token families and prevents accidental literal component colors.
- `frontend/app/layout.tsx`: global stylesheet and font setup.
- `frontend/app/page.tsx`: server redirect to the component preview.
- `frontend/components/shared/shared-icons.tsx`: consistent internal SVG icon wrappers sourced from Lucide.
- `frontend/components/shared/LoadingSpinner.tsx`: branded status indicator and optional page overlay.
- `frontend/components/shared/ErrorMessage.tsx`: inline, banner, and full-page error treatments.
- `frontend/components/shared/file-validation.ts`: pure upload validation and file-size formatting.
- `frontend/components/shared/UploadDropzone.tsx`: drag, browse, validation, selection, and removal.
- `frontend/components/shared/IngestionProgress.tsx`: stable polling-driven job list.
- `frontend/components/shared/response-types.ts`: local presentation-only response contracts.
- `frontend/components/shared/ResponseCard.tsx`: separate Professional and Public compositions.
- `frontend/components/shared/index.ts`: public exports for the shared component package.
- `frontend/components/shared/*.test.tsx`: focused behavior and accessibility assertions.
- `frontend/app/dev/component-preview/fixtures.ts`: frozen-contract-shaped preview data.
- `frontend/app/dev/component-preview/PreviewGallery.tsx`: interactive preview state and composition.
- `frontend/app/dev/component-preview/page.tsx`: route metadata and gallery entry point.

---

### Task 1: Scaffold the frontend, test harness, and design system

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/package-lock.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/next-env.d.ts`
- Create: `frontend/next.config.ts`
- Create: `frontend/postcss.config.mjs`
- Create: `frontend/tailwind.config.ts`
- Create: `frontend/eslint.config.mjs`
- Create: `frontend/prettier.config.mjs`
- Create: `frontend/.prettierignore`
- Create: `frontend/vitest.config.ts`
- Create: `frontend/vitest.setup.ts`
- Create: `frontend/app/layout.tsx`
- Create: `frontend/app/page.tsx`
- Create: `frontend/app/globals.css`
- Create: `frontend/app/design-system.test.ts`
- Delete: `frontend/app/.gitkeep`

**Interfaces:**
- Produces: npm scripts `dev`, `build`, `lint`, `test`, `test:run`, `format`, and `format:check`.
- Produces: Tailwind utilities backed by `--color-*`, `--radius-*`, `--shadow-*`, `--motion-*`, `--font-display`, and `--font-ui` tokens.
- Consumes: approved visual references and the light-theme rules in the design spec.

- [ ] **Step 1: Create the pinned package manifest**

```json
{
  "name": "legalai-frontend",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "lint": "eslint . --max-warnings=0",
    "test": "vitest",
    "test:run": "vitest run",
    "format": "prettier --write .",
    "format:check": "prettier --check ."
  },
  "dependencies": {
    "lucide-react": "1.39.0",
    "next": "16.3.4",
    "react": "19.2.8",
    "react-dom": "19.2.8"
  },
  "devDependencies": {
    "@tailwindcss/postcss": "4.3.3",
    "@testing-library/jest-dom": "7.0.1",
    "@testing-library/react": "16.3.3",
    "@testing-library/user-event": "14.6.7",
    "@types/node": "26.4.1",
    "@types/react": "19.2.18",
    "@types/react-dom": "19.2.5",
    "eslint": "10.9.1",
    "eslint-config-next": "16.3.4",
    "eslint-config-prettier": "10.1.8",
    "jsdom": "30.0.1",
    "prettier": "3.9.6",
    "tailwindcss": "4.3.3",
    "typescript": "7.0.2",
    "vitest": "4.1.11"
  }
}
```

- [ ] **Step 2: Install dependencies and create the lockfile**

Run: `cd frontend && npm install`

Expected: npm exits 0 and creates `package-lock.json` with no unresolved peer dependency.

- [ ] **Step 3: Configure strict TypeScript, Next.js, Tailwind, ESLint, Prettier, and Vitest**

Use `moduleResolution: "bundler"`, `strict: true`, `noEmit: true`, the `@/*` alias, and Next's generated plugin settings. Load Tailwind through `@tailwindcss/postcss`; point `vitest.config.ts` at jsdom and `vitest.setup.ts`; extend Next core-web-vitals and TypeScript ESLint presets through the flat configuration.

```ts
// vitest.config.ts
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: { environment: 'jsdom', setupFiles: ['./vitest.setup.ts'] },
  resolve: { alias: { '@': new URL('./', import.meta.url).pathname } },
});
```

```ts
// vitest.setup.ts
import '@testing-library/jest-dom/vitest';
```

- [ ] **Step 4: Write a failing design-token contract test**

Read `app/globals.css` with `node:fs` and assert that the required canvas,
surface, ink, brass, focus, success, warning, error, info, radius, shadow, and
motion custom properties exist.

```ts
it('defines every shared semantic token family', () => {
  const css = readFileSync(new URL('./globals.css', import.meta.url), 'utf8');
  for (const token of ['--color-canvas', '--color-surface', '--color-ink', '--color-brass', '--color-success', '--color-warning', '--color-error', '--color-info', '--radius-standard', '--shadow-component', '--motion-standard']) {
    expect(css).toContain(token);
  }
});
```

Run: `cd frontend && npm run test:run -- design-system.test.ts`

Expected: FAIL because `globals.css` does not exist yet.

- [ ] **Step 5: Define and document the token system before component code**

At the top of `globals.css`, document the palette, typography, geometry, elevation, and motion ownership. Define warm canvas/surfaces, ink/body/muted/inverse text, brass action states, and foreground/surface/border triples for success, warning, error, and info. Add global focus-visible, reduced-motion, body, button/input font, and selection rules.

```css
@config "../tailwind.config.ts";
@import "tailwindcss";

:root {
  --color-canvas: #f7f3eb;
  --color-surface: #fffdf8;
  --color-ink: #0b294d;
  --color-body: #1d2b3c;
  --color-muted: #657180;
  --color-brass: #a86f28;
  --color-focus: #1f67b1;
  --radius-standard: 0.625rem;
  --shadow-component: 0 0.5rem 1.5rem rgb(11 41 77 / 0.08);
  --motion-fast: 150ms;
  --motion-standard: 220ms;
}
```

Add the remaining semantic tokens in the same documented block. Component files must refer to named utilities or `var(...)`, never literal color values.

- [ ] **Step 6: Verify the token contract passes**

Run: `cd frontend && npm run test:run -- design-system.test.ts`

Expected: PASS.

- [ ] **Step 7: Create the root layout and redirect**

Use `next/font/google` with Libre Baskerville for display and IBM Plex Sans for UI, bind them to CSS variables, import `globals.css`, and set LegalAI metadata. Make `app/page.tsx` call `redirect('/dev/component-preview')` without adding visible marketing content.

- [ ] **Step 8: Run baseline checks**

Run: `cd frontend && npm run lint && npm run test:run && npm run build && npm run format:check`

Expected: all four commands exit 0 and the design-system test passes.

- [ ] **Step 9: Commit the scaffold and tokens**

```bash
git add frontend
git commit -m "chore(frontend): scaffold Next.js and design system"
```

---

### Task 2: Build LoadingSpinner and ErrorMessage

**Files:**
- Create: `frontend/components/shared/shared-icons.tsx`
- Create: `frontend/components/shared/LoadingSpinner.tsx`
- Create: `frontend/components/shared/LoadingSpinner.test.tsx`
- Create: `frontend/components/shared/ErrorMessage.tsx`
- Create: `frontend/components/shared/ErrorMessage.test.tsx`

**Interfaces:**
- Produces: `LoadingSpinner({ size, label, fullScreen }: LoadingSpinnerProps)`.
- Produces: `ErrorMessage({ title, message, variant, onRetry, technicalDetail }: ErrorMessageProps)`.
- Consumes: global semantic tokens and shared Lucide icon wrappers.

- [ ] **Step 1: Write failing LoadingSpinner tests**

```tsx
it('announces its label and applies the requested size', () => {
  render(<LoadingSpinner size="lg" label="Loading legal analysis" />);
  expect(screen.getByRole('status', { name: 'Loading legal analysis' })).toHaveAttribute('data-size', 'lg');
});

it('marks a full-screen spinner without trapping focus', () => {
  render(<LoadingSpinner size="md" fullScreen />);
  expect(screen.getByRole('status')).toHaveAttribute('data-full-screen', 'true');
});
```

- [ ] **Step 2: Verify LoadingSpinner tests fail**

Run: `cd frontend && npm run test:run -- LoadingSpinner.test.tsx`

Expected: FAIL because `LoadingSpinner` does not exist.

- [ ] **Step 3: Implement LoadingSpinner minimally**

Define the exact prop union, default the label to `Loading`, use `role="status"` plus `aria-label`, render a broken-ring motif, and map `sm`, `md`, and `lg` to stable dimensions. Full-screen mode adds a fixed token-backed overlay; reduced-motion styling stops rotation.

```ts
export interface LoadingSpinnerProps {
  size?: 'sm' | 'md' | 'lg';
  label?: string;
  fullScreen?: boolean;
}
```

- [ ] **Step 4: Run LoadingSpinner tests until green**

Run: `cd frontend && npm run test:run -- LoadingSpinner.test.tsx`

Expected: PASS.

- [ ] **Step 5: Write failing ErrorMessage tests**

```tsx
it('calls retry and keeps technical detail collapsed by default', async () => {
  const retry = vi.fn();
  render(<ErrorMessage title="Try again" message="We could not finish this request." variant="banner" onRetry={retry} technicalDetail="Reference service unavailable." />);
  expect(screen.queryByText('Reference service unavailable.')).not.toBeVisible();
  await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
  expect(retry).toHaveBeenCalledOnce();
});
```

- [ ] **Step 6: Verify ErrorMessage tests fail**

Run: `cd frontend && npm run test:run -- ErrorMessage.test.tsx`

Expected: FAIL because `ErrorMessage` does not exist.

- [ ] **Step 7: Implement all ErrorMessage variants**

Use a variant class map, `role="alert"`, a native `<details>` disclosure for safe technical detail, and a Retry button only when `onRetry` is supplied. Inline stays compact, banner uses a horizontal layout above 640px, and fullpage centers within a bounded panel without becoming an application overlay.

```ts
export interface ErrorMessageProps {
  title: string;
  message: string;
  variant: 'inline' | 'banner' | 'fullpage';
  onRetry?: () => void;
  technicalDetail?: string;
}
```

- [ ] **Step 8: Run focused and aggregate checks**

Run: `cd frontend && npm run test:run -- LoadingSpinner.test.tsx ErrorMessage.test.tsx && npm run lint`

Expected: tests and lint PASS.

- [ ] **Step 9: Commit both feedback components**

```bash
git add frontend/components/shared frontend/app/globals.css
git commit -m "feat(ux): add loading and error feedback components"
```

---

### Task 3: Build UploadDropzone

**Files:**
- Create: `frontend/components/shared/file-validation.ts`
- Create: `frontend/components/shared/file-validation.test.ts`
- Create: `frontend/components/shared/UploadDropzone.tsx`
- Create: `frontend/components/shared/UploadDropzone.test.tsx`

**Interfaces:**
- Produces: `formatFileSize(bytes: number): string`.
- Produces: `validateFiles(files: File[], options: ValidationOptions): ValidationResult`.
- Produces: `UploadDropzone({ accept = 'application/pdf,.pdf', maxSizeMB = 10, multiple = false, onFilesSelected, disabled = false }: UploadDropzoneProps)`.
- Consumes: `ErrorMessage` for validation feedback.

- [ ] **Step 1: Write failing pure validation tests**

```ts
it('rejects a non-PDF and an oversized PDF with actionable messages', () => {
  const wrong = new File(['x'], 'notes.txt', { type: 'text/plain' });
  const large = new File([new Uint8Array(2_000_000)], 'large.pdf', { type: 'application/pdf' });
  const result = validateFiles([wrong, large], { accept: 'application/pdf,.pdf', maxSizeMB: 1, multiple: true });
  expect(result.valid).toHaveLength(0);
  expect(result.errors).toEqual(expect.arrayContaining([expect.stringContaining('notes.txt'), expect.stringContaining('large.pdf')]));
});
```

- [ ] **Step 2: Run the validation test and observe failure**

Run: `cd frontend && npm run test:run -- file-validation.test.ts`

Expected: FAIL because the utility does not exist.

- [ ] **Step 3: Implement deterministic validation**

Parse comma-separated MIME types and extensions, treat `.pdf` as a valid fallback when browsers provide an empty MIME, enforce the size in bytes, deduplicate by name/size/lastModified, and return all safe user-facing errors.

```ts
export interface ValidationOptions { accept: string; maxSizeMB: number; multiple: boolean }
export interface ValidationResult { valid: File[]; errors: string[] }
```

- [ ] **Step 4: Run validation tests until green**

Run: `cd frontend && npm run test:run -- file-validation.test.ts`

Expected: PASS.

- [ ] **Step 5: Write failing interaction tests**

Test browse upload, drag/drop, single-file replacement, multi-file accumulation, remove, disabled behavior, invalid type, and oversize reporting.

```tsx
it('reports the current valid list after add and remove', async () => {
  const onFilesSelected = vi.fn();
  render(<UploadDropzone multiple onFilesSelected={onFilesSelected} />);
  const pdf = new File(['judgment'], 'judgment.pdf', { type: 'application/pdf' });
  await userEvent.upload(screen.getByLabelText('Choose PDF files'), pdf);
  expect(onFilesSelected).toHaveBeenLastCalledWith([pdf]);
  await userEvent.click(screen.getByRole('button', { name: 'Remove judgment.pdf' }));
  expect(onFilesSelected).toHaveBeenLastCalledWith([]);
});
```

- [ ] **Step 6: Implement the dropzone**

Use a native hidden file input activated by a real button, drag-enter depth tracking to avoid flicker, keyboard-accessible browse, clear disabled states, selected-file rows with formatted sizes, and named remove buttons. Pass every candidate through `validateFiles`; render combined errors through inline `ErrorMessage`.

```ts
export interface UploadDropzoneProps {
  accept?: string;
  maxSizeMB?: number;
  multiple?: boolean;
  onFilesSelected: (files: File[]) => void;
  disabled?: boolean;
}
```

- [ ] **Step 7: Run tests, lint, and commit**

Run: `cd frontend && npm run test:run -- file-validation.test.ts UploadDropzone.test.tsx && npm run lint`

Expected: PASS.

```bash
git add frontend/components/shared
git commit -m "feat(ux): add accessible PDF upload dropzone"
```

---

### Task 4: Build IngestionProgress

**Files:**
- Create: `frontend/components/shared/IngestionProgress.tsx`
- Create: `frontend/components/shared/IngestionProgress.test.tsx`

**Interfaces:**
- Produces: `IngestionStage`, `IngestionJob`, `IngestionProgressProps`, and `IngestionProgress({ jobs })`.
- Consumes: `ErrorMessage` and token-backed status icons.

- [ ] **Step 1: Write failing stage, progress, and failure tests**

```tsx
const jobs: IngestionJob[] = [
  { id: 'a', filename: 'queued.pdf', stage: 'QUEUED', progress: 0 },
  { id: 'b', filename: 'done.pdf', stage: 'COMPLETED', progress: 120 },
  { id: 'c', filename: 'failed.pdf', stage: 'FAILED', progress: 72, error: 'Indexing could not be completed.' },
];

it('renders frozen stages, clamps progress, and exposes failures', () => {
  render(<IngestionProgress jobs={jobs} />);
  expect(screen.getByText('QUEUED')).toBeInTheDocument();
  expect(screen.getByRole('progressbar', { name: 'done.pdf progress' })).toHaveAttribute('aria-valuenow', '100');
  expect(screen.getByRole('alert')).toHaveTextContent('Indexing could not be completed.');
});
```

- [ ] **Step 2: Verify the tests fail**

Run: `cd frontend && npm run test:run -- IngestionProgress.test.tsx`

Expected: FAIL because the component does not exist.

- [ ] **Step 3: Implement the stable job list**

```ts
export type IngestionStage = 'QUEUED' | 'EXTRACTING' | 'CHUNKING' | 'EMBEDDING' | 'INDEXING' | 'COMPLETED' | 'FAILED';
export interface IngestionJob { id: string; filename: string; stage: IngestionStage; progress: number; error?: string }
export interface IngestionProgressProps { jobs: IngestionJob[] }
```

Render a semantic list keyed only by `id`. Each row reserves a stage line, a progress region, and an error region. Clamp displayed and ARIA progress to 0–100. Completed and failed status overrides use semantic success/error tokens; every other stage retains its exact enum label. An empty `jobs` array renders a quiet “No ingestion jobs yet.” state.

- [ ] **Step 4: Add a rerender assertion for polling updates**

Use Testing Library's `rerender` to change a job from `EXTRACTING` at 20 to `CHUNKING` at 48, then assert one filename row remains and its `aria-valuenow` updates to 48.

- [ ] **Step 5: Run tests, lint, and commit**

Run: `cd frontend && npm run test:run -- IngestionProgress.test.tsx && npm run lint`

Expected: PASS.

```bash
git add frontend/components/shared
git commit -m "feat(ux): add ingestion progress component"
```

---

### Task 5: Build ResponseCard with separate mode compositions

**Files:**
- Create: `frontend/components/shared/response-types.ts`
- Create: `frontend/components/shared/ResponseCard.tsx`
- Create: `frontend/components/shared/ResponseCard.test.tsx`

**Interfaces:**
- Produces: `AnswerContent`, `Citation`, `LegalSection`, `ResponseCardProps`, and `ResponseCard`.
- Consumes: no backend/API module; receives all content through props.

- [ ] **Step 1: Define the presentation contracts in the failing test**

```ts
export interface AnswerContent { heading: string; paragraphs: string[]; keyPoints?: string[] }
export interface Citation { title: string; court?: string; year?: number; sourceUrl: string; excerpt?: string }
export interface LegalSection { code: 'IPC' | 'BNS' | 'CrPC' | 'BNSS' | string; section: string; title: string; explanation?: string; sourceUrl: string; confidence?: number }
export interface ResponseCardProps { mode: 'professional' | 'public'; content: AnswerContent; citations: Citation[]; sections: LegalSection[] }
```

- [ ] **Step 2: Write failing Professional/Public distinction tests**

```tsx
it('shows research metadata and confidence only to professionals', () => {
  const { rerender } = render(<ResponseCard mode="professional" content={content} citations={citations} sections={sections} />);
  expect(screen.getByText('Supreme Court of India')).toBeInTheDocument();
  expect(screen.getByText('82% confidence')).toBeInTheDocument();
  rerender(<ResponseCard mode="public" content={content} citations={citations} sections={sections} />);
  expect(screen.queryByText('82% confidence')).not.toBeInTheDocument();
  expect(screen.getAllByRole('link', { name: 'Learn more' })).not.toHaveLength(0);
});
```

Also assert external links use `target="_blank"` and `rel="noreferrer"`, missing optional metadata does not leave punctuation artifacts, and paragraphs render as text rather than raw HTML.

- [ ] **Step 3: Run the tests and observe failure**

Run: `cd frontend && npm run test:run -- ResponseCard.test.tsx`

Expected: FAIL because the component and types do not exist.

- [ ] **Step 4: Implement two explicit layout branches**

Keep one public `ResponseCard` entry but delegate to `ProfessionalResponse` and `PublicResponse` internal components. Professional uses dense three-region structure, full citation metadata/excerpts, and clamped confidence percentages. Public uses a plain-language lead, generous spacing, simplified provision explanations, and Learn more links only. Both include a non-advice footer; no confidence element is constructed in the Public branch.

- [ ] **Step 5: Run tests, lint, and commit**

Run: `cd frontend && npm run test:run -- ResponseCard.test.tsx && npm run lint`

Expected: PASS.

```bash
git add frontend/components/shared
git commit -m "feat(ux): add public and professional response card"
```

---

### Task 6: Assemble the interactive component preview

**Files:**
- Create: `frontend/components/shared/index.ts`
- Create: `frontend/app/dev/component-preview/fixtures.ts`
- Create: `frontend/app/dev/component-preview/PreviewGallery.tsx`
- Create: `frontend/app/dev/component-preview/PreviewGallery.test.tsx`
- Create: `frontend/app/dev/component-preview/page.tsx`

**Interfaces:**
- Produces: `/dev/component-preview` with all required components and states.
- Consumes: only exports from `@/components/shared` and local fixtures.

- [ ] **Step 1: Create exact shared exports**

Export the five components and all consumer-facing prop/type definitions from `components/shared/index.ts`. Do not export preview fixtures or internal icon helpers.

- [ ] **Step 2: Write failing preview interaction tests**

```tsx
it('demonstrates every shared component and switches response mode', async () => {
  render(<PreviewGallery />);
  expect(screen.getByRole('heading', { name: 'LegalAI Component Library' })).toBeInTheDocument();
  expect(screen.getByText('UploadDropzone')).toBeInTheDocument();
  expect(screen.getByText('IngestionProgress')).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Public' }));
  expect(screen.getByRole('heading', { name: 'Plain-language answer' })).toBeInTheDocument();
  expect(screen.queryByText(/confidence/i)).not.toBeInTheDocument();
});
```

Add tests that Retry produces a visible status acknowledgement, technical detail can be disclosed, and the progress demo advances without changing job identity.

- [ ] **Step 3: Verify preview tests fail**

Run: `cd frontend && npm run test:run -- PreviewGallery.test.tsx`

Expected: FAIL because the preview gallery does not exist.

- [ ] **Step 4: Build safe, contract-shaped fixtures**

Use specific Indian legal content and URLs suitable for demonstration, clearly comment that fixtures are presentation mocks mapped from the frozen Phase 0 contract, and use only the seven frozen ingestion enum values. Include one safe failure string: “Indexing could not be completed. Retry this document.”

- [ ] **Step 5: Implement the approved preview composition**

Build a compact LegalAI brand header and the exact five numbered sections. Use a balanced two-column layout at 1100px+, one column at 768px, and 16px mobile gutters. Provide SM/MD/LG spinner examples, all three ErrorMessage variants, a functional UploadDropzone, all ingestion states, and a full-width ResponseCard section with an accessible Professional/Public tab-style control.

Use local state only. Retry writes to a polite live region. “Advance progress” replaces fixture arrays while preserving ids. The mode switch uses buttons with `aria-pressed` and 44px targets.

- [ ] **Step 6: Add route metadata and render the gallery**

```tsx
export const metadata = { title: 'Component Library | LegalAI' };

export default function ComponentPreviewPage() {
  return <PreviewGallery />;
}
```

- [ ] **Step 7: Run the full automated suite**

Run: `cd frontend && npm run test:run && npm run lint && npm run build && npm run format:check`

Expected: all checks PASS with zero lint warnings and zero type/build errors.

- [ ] **Step 8: Commit the component preview**

```bash
git add frontend/app frontend/components/shared frontend/package.json frontend/package-lock.json
git commit -m "feat(ux): add interactive shared component preview"
```

---

### Task 7: Perform browser fidelity, responsive, and interaction QA

**Files:**
- Modify as evidence requires: `frontend/app/globals.css`
- Modify as evidence requires: `frontend/components/shared/*.tsx`
- Modify as evidence requires: `frontend/app/dev/component-preview/PreviewGallery.tsx`
- Create: `frontend/app/dev/component-preview/screenshots/legalai-components-desktop.png`
- Create: `frontend/app/dev/component-preview/screenshots/legalai-components-mobile.png`

**Interfaces:**
- Produces: agency-signoff fidelity to both approved concepts and verified core interactions.
- Consumes: the completed preview from Task 6.

- [ ] **Step 1: Start the production-like preview**

Run: `cd frontend && npm run dev`

Expected: Next.js serves `/dev/component-preview` without console or runtime errors.

- [ ] **Step 2: Verify the core workflow in Browser/IAB**

At 1440px, exercise browse/upload, remove, invalid file, Retry, technical disclosure, progress advance, external source links, and Professional/Public switching. Confirm state visibly changes and no browser console errors appear.

- [ ] **Step 3: Capture three responsive widths**

Capture the full page at 1440px and 375px for committed PR evidence; inspect 768px interactively. Verify no horizontal scroll, clipped primary content, accidental wrapping, or targets below 44px at mobile width.

- [ ] **Step 4: Compare concept and render with image inspection**

Use `view_image` in one QA pass on:

- `frontend/app/dev/concepts/legalai-components-desktop.png`
- `frontend/app/dev/component-preview/screenshots/legalai-components-desktop.png`
- `frontend/app/dev/concepts/legalai-components-mobile.png`
- `frontend/app/dev/component-preview/screenshots/legalai-components-mobile.png`

Record and repair mismatches in at least copy, section order/layout, typography, palette, spacing/container model, icon treatment, and responsive behavior. Contract correctness overrides generated-image text defects.

- [ ] **Step 5: Run the above-the-fold copy diff**

Allowed copy before the first component section is exactly `LegalAI`, `Indian Criminal Law RAG Assistant`, `LegalAI Component Library`, and `Shared UX for Public, Professional & Admin modes`. Remove or record any deviation.

- [ ] **Step 6: Re-run all checks after visual repairs**

Run: `cd frontend && npm run test:run && npm run lint && npm run build && npm run format:check`

Expected: all checks PASS.

- [ ] **Step 7: Commit fidelity repairs and screenshots**

```bash
git add frontend/app frontend/components/shared
git commit -m "fix(ux): align component preview with approved design"
```

Skip this commit only if Task 6 already matches and the screenshot files were included in its commit; never create an empty commit.

---

### Task 8: Audit scope, push, and open the pull request

**Files:**
- No source files should change during this task.

**Interfaces:**
- Produces: pushed branch and an unmerged PR into `main` with honest verification evidence.
- Consumes: a clean, fully verified Task 7 branch.

- [ ] **Step 1: Audit every changed path**

Run: `git status --short && git diff --stat main && git diff --name-only main`

Expected: only intended `frontend/` paths appear; `frontend/lib/api.ts`, `backend/`, `data/`, `models/`, and `notebooks/` do not appear.

- [ ] **Step 2: Verify no component contains literal colors or unsafe error copy**

Run: `rg -n "#[0-9a-fA-F]{3,8}|rgb\\(|hsl\\(|stack trace|Traceback|permission denied" frontend/components/shared frontend/app/dev/component-preview`

Expected: no matches. Token definitions in `globals.css` are intentionally outside this search.

- [ ] **Step 3: Run final verification from a clean process**

Run: `cd frontend && npm ci && npm run test:run && npm run lint && npm run build && npm run format:check`

Expected: every command exits 0.

- [ ] **Step 4: Push the feature branch**

Run: `git push -u origin feat/phase3-shared-ux-gugan`

Expected: upstream is configured and the remote branch points at local HEAD.

- [ ] **Step 5: Open, but do not merge, the PR**

Use title: `feat(frontend): Phase 1 — shared UX components + design system`

The body must list LoadingSpinner, ErrorMessage, UploadDropzone, IngestionProgress, and ResponseCard; embed or link both committed screenshots; state “No backend/data/model files touched”; state “frontend/lib/api.ts was intentionally not created because it is Ravindran's deliverable”; and check off test, lint, build, formatting, 375px, 768px, and 1440px verification.

- [ ] **Step 6: Confirm delivery state**

Run: `git status --short --branch && gh pr view --json url,title,state,baseRefName,headRefName`

Expected: clean working tree, branch tracks origin, PR is OPEN from `feat/phase3-shared-ux-gugan` into `main`. Do not merge it.
