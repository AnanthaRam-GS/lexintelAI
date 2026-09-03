# LegalAI Phase 1 Shared UX — Design Specification

**Date:** 2026-09-03  
**Branch:** `feat/phase3-shared-ux-gugan`  
**Scope:** Task 3.G.1 only

## Objective

Create the initial Next.js App Router frontend scaffold and five reusable,
production-quality shared components for LegalAI's Public, Professional, and
Admin modes. The work remains frontend-only and does not introduce an API
client, authentication behavior, backend changes, or Phase 2 application pages.

## Approved visual direction

LegalAI uses a calm Indian legal-editorial visual language inspired by court
records rather than generic AI or SaaS dashboards. The interface combines deep
ink navy, a warm paper-neutral canvas, and a restrained antique-brass accent.
Semantic green, amber, brick red, and blue are reserved for status feedback.
There are no gradients, glass effects, decorative courthouse scenes, oversized
rounding, or marketing chrome.

Headings use an authoritative old-style serif face. Body text, controls, labels,
and data use a clean sans-serif face. Components share a 10px radius, hairline
borders, one restrained elevation scale, visible focus rings, and 150–250ms
ease transitions. Phase 1 is deliberately light-theme only; all colors come
from documented semantic tokens so a later dark theme can be added without
rewriting component markup.

Approved references:

- `frontend/app/dev/concepts/legalai-components-desktop.png`
- `frontend/app/dev/concepts/legalai-components-mobile.png`

The references establish visual language and composition. Contract details in
this specification take precedence over any text imperfections in generated
mockups.

## Architecture

The frontend will use Next.js App Router, TypeScript in strict mode, Tailwind
CSS, ESLint, and Prettier. The root app supplies global font and token setup.
Reusable components live in `frontend/components/shared/`; component-specific
types stay beside their owning component or in a shared component type module,
not in `frontend/lib/api.ts`.

The route `frontend/app/dev/component-preview/page.tsx` composes a client-side
preview gallery. It demonstrates real local interactions: file selection and
removal, retry callbacks, technical-detail disclosure, progress-state changes,
and the Professional/Public response switch. Mock fixtures remain under the
preview route and are clearly marked as previews of the frozen contracts.

No code will be added to `frontend/lib/api.ts`. The frozen ingestion stage
names and public-response meaning come from `docs/API_CONTRACTS.md` and
`backend/app/models/`, but those files will not be modified.

## Design tokens

`frontend/app/globals.css` will document and define every design token at the
top of the file. Tailwind configuration will expose those CSS variables using
semantic names rather than duplicated values.

Token families:

- Surfaces: canvas, surface, raised surface, and subtle surface.
- Text: authority, body, muted, and inverse.
- Brand: ink and brass accent, including hover and focus states.
- Feedback: success, warning, error, and info, each with foreground, surface,
  and border roles.
- Geometry: 10px standard radius, compact inner radius, hairline border.
- Elevation: one soft component shadow and one overlay shadow.
- Motion: fast 150ms and standard 220ms ease transitions.
- Typography: serif display family and sans UI family with explicit scales for
  headings, body, labels, captions, and controls.

Components must not contain ad-hoc hex, RGB, or HSL values.

## Shared components

### LoadingSpinner

Accepts `size: 'sm' | 'md' | 'lg'`, optional `label`, and optional
`fullScreen`. It uses a small broken-ring motif in the accent/ink palette with
CSS animation and a motion-reduced static fallback. The accessible name is
announced through `role="status"`; the optional full-screen state creates a
page-level overlay without trapping focus.

### ErrorMessage

Accepts `title`, `message`, `variant: 'inline' | 'banner' | 'fullpage'`,
optional `onRetry`, and optional `technicalDetail`. Public-facing title and
message content remain plain-language. Technical detail is rendered only
inside a collapsed native disclosure and must itself be non-sensitive. The
component uses `role="alert"`; Retry is a real keyboard-operable button with a
visible focus state.

### UploadDropzone

Accepts `accept` (default PDF), `maxSizeMB`, `multiple`,
`onFilesSelected`, and `disabled`. It supports drag/drop and a visually clear
click-to-browse input. Selected files show name, formatted size, and an
accessible remove action before submission. Client validation rejects
unsupported MIME/extension combinations and oversized files. Validation is
reported through the shared inline `ErrorMessage`. The callback receives the
current valid file list after additions or removals.

### IngestionProgress

Accepts a `jobs` array containing `id`, `filename`, `stage`, `progress`, and
`error`. `stage` is exactly one of `QUEUED`, `EXTRACTING`, `CHUNKING`,
`EMBEDDING`, `INDEXING`, `COMPLETED`, or `FAILED`. Progress is visually and
semantically clamped to 0–100. Rows reserve stable regions for stage, progress,
and error content so polling updates do not shift adjacent rows. Failed jobs
render the shared inline `ErrorMessage`; other stages use consistent status
icons and accessible progress bars.

### ResponseCard

Accepts `mode: 'professional' | 'public'`, structured answer content,
citations, and identified IPC/BNS sections. A discriminated TypeScript model
will make the content structure explicit without importing an unfinished API
client contract. Citation values are exactly `title`, optional `court`, optional
`year`, `sourceUrl`, and optional `excerpt`. A statutory section contains its
act/code label, section number, title, optional explanation, source URL, and
optional confidence. Answer content contains a heading, ordered paragraphs,
and optional key points; it never contains raw HTML.

Professional mode is dense and research-oriented: structured sections,
complete court/year citation metadata, excerpts where supplied, statutory
provision detail, and confidence values. Public mode is a genuinely separate
presentation branch: larger plain-language copy, simplified provision
explanations, no confidence values, and sources reduced to clear “Learn more”
links. Shared low-level primitives may be reused, but the two modes will not be
implemented as one identical layout with fields merely hidden.

## Responsive behavior

The preview uses an open two-column desktop composition and collapses into one
stack from tablet widths downward. At 375px, controls remain at least 44px high,
file names truncate without hiding remove controls, progress rows reflow rather
than scroll horizontally, citations wrap safely, and no primary content clips.
At 768px, the component gallery uses a single comfortable column. At 1440px,
related examples use balanced columns while ResponseCard receives full width.

## Data and interaction flow

All Phase 1 behavior is local:

1. The preview supplies frozen-contract-shaped fixtures to shared components.
2. UploadDropzone validates browser `File` objects and reports the current
   valid selection to its preview parent.
3. Preview controls replace ingestion job arrays to demonstrate polling-style
   rerenders; IngestionProgress remains stateless.
4. Retry buttons call preview callbacks and expose a visible acknowledgement.
5. The response-mode control swaps between separate Professional and Public
   fixtures and layouts.

There are no HTTP calls, persisted user data, or competing API abstractions in
Phase 1.

## Error and accessibility policy

Visible user errors never contain stack traces, exception names, database
details, filesystem paths, or secrets. Technical disclosures use safe summary
text only. Upload validation identifies the file and gives a corrective action.
Failed ingestion rows preserve the filename and state what can be retried.

The implementation uses semantic headings, native buttons/inputs/disclosures,
keyboard-operable dropzone browsing, visible `:focus-visible` treatment,
programmatic labels, live-region/status semantics, sufficient color contrast,
and `prefers-reduced-motion` handling. Information is never communicated by
color alone.

## Files in scope

- Frontend scaffold/config files under `frontend/`, including package and lock
  files required by Next.js, TypeScript, Tailwind, linting, and formatting.
- `frontend/app/globals.css` and the minimum root layout/page files needed for
  a valid App Router build.
- `frontend/components/shared/` for the five components and focused helpers.
- `frontend/app/dev/` for this specification, approved concepts, fixtures, and
  the component-preview route.

Explicitly out of scope: `frontend/lib/api.ts`, backend code, database/data
files, models, notebooks, Phase 2 routes, authentication, live ingestion, and
live public queries.

## Verification

Automated checks:

- TypeScript strict compilation through the production build.
- ESLint with zero errors.
- Production `next build` with zero errors.
- Focused component tests for file validation/removal, retry behavior,
  technical-detail disclosure, frozen stage rendering, progress semantics, and
  Professional/Public differences using Vitest, React Testing Library, and
  user-event in a jsdom environment.

Visual and interaction checks:

- Run the preview and inspect it at 375px, 768px, and 1440px.
- Exercise browse, drag/drop, removal, invalid type, oversized file, retry,
  disclosure, progress updates, failure state, and response-mode switching.
- Capture desktop and mobile screenshots and compare them directly with the
  approved concepts using image inspection.
- Audit copy, typography, palette, spacing, container model, status icons,
  focus states, and overflow.
- Review `git diff --stat main` and confirm no unauthorized path changed.

## Delivery

Implementation commits will follow the repository's conventional commit style.
After verification, the branch will be pushed and a pull request opened against
`main`. The PR will list all five components, include mobile and desktop
screenshots, record lint/build results, state that no backend/data/model files
were touched, and state that `frontend/lib/api.ts` was intentionally not
created. The PR will be left unmerged for team review.
