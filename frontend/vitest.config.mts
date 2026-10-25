import { configDefaults, defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'jsdom',
    setupFiles: ['./vitest.setup.ts'],
    // Browser journeys run under Playwright (playwright.config.ts), not Vitest.
    exclude: [...configDefaults.exclude, 'e2e/**'],
  },
  resolve: { alias: { '@': new URL('./', import.meta.url).pathname } },
});
