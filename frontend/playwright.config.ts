import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { defineConfig, devices } from '@playwright/test';

/**
 * Browser journeys (step 17, TEST-002). Run them through backend/scripts/e2e/run_e2e.sh, which prepares the
 * database and the state directory and sets the backend's end-to-end environment (docs/TESTING.md).
 */
const frontendDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(frontendDir, '..');
const python = process.env.E2E_PYTHON ?? path.join(repoRoot, '.venv/bin/python');
const realMode = process.env.E2E_MODE === 'real';

export default defineConfig({
  testDir: './e2e',
  // One worker: the journeys share one database and corpus, and the admin journey changes the corpus count.
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  // Real retrieval (BGE-M3 and the reranker on the local machine) is slower than the fakes.
  timeout: realMode ? 180_000 : 60_000,
  expect: { timeout: realMode ? 90_000 : 15_000 },
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  use: {
    baseURL: 'http://localhost:3000',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: `"${python}" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000`,
      cwd: repoRoot,
      url: 'http://127.0.0.1:8000/health',
      timeout: realMode ? 300_000 : 120_000,
      reuseExistingServer: false,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      // E2E_SKIP_BUILD=1 reuses an existing .next build (CI builds in an earlier step). E2E_NEXT_DEV=1 serves
      // with `next dev` instead, for machines that cannot reach Google Fonts during `next build`.
      command: process.env.E2E_NEXT_DEV
        ? 'npx next dev -p 3000'
        : process.env.E2E_SKIP_BUILD
          ? 'npx next start -p 3000'
          : 'npx next build && npx next start -p 3000',
      cwd: frontendDir,
      url: 'http://localhost:3000',
      timeout: 300_000,
      reuseExistingServer: false,
      env: { NEXT_PUBLIC_API_BASE_URL: 'http://localhost:8000' },
    },
  ],
});
