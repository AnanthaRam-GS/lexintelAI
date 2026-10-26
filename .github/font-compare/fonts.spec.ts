// TEMPORARY (step 20 acceptance): screenshots of key pages. Run once against main (Google-hosted fonts) with
// --update-snapshots, then against this branch (self-hosted fonts): any pixel difference fails. Reverted after the run.
import { expect, test } from '@playwright/test';

const PAGES = ['/', '/public', '/public/ask', '/login', '/register'];
const WIDTHS = [1280, 375];

for (const width of WIDTHS) {
  for (const path of PAGES) {
    test(`${path} at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(path);
      await page.waitForLoadState('networkidle');
      await page.evaluate(() => document.fonts.ready);
      const name = `${path === '/' ? 'home' : path.slice(1).replaceAll('/', '-')}-${width}.png`;
      await expect(page).toHaveScreenshot(name, { fullPage: true, maxDiffPixels: 0, animations: 'disabled' });
    });
  }
}
