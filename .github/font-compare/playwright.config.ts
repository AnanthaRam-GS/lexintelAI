// TEMPORARY (step 20 acceptance): see fonts.spec.ts. BASE_URL points at the frontend under test.
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: '.',
  snapshotPathTemplate: '{testDir}/snapshots/{arg}{ext}',
  workers: 1,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never', outputFolder: process.env.REPORT_DIR ?? 'report' }]],
  outputDir: process.env.OUTPUT_DIR ?? 'results',
  use: { baseURL: process.env.BASE_URL, ...devices['Desktop Chrome'] },
});
