import { expect, test } from '@playwright/test';

test.describe('responsive layout', () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test('/public/ask at 375 px has no horizontal scroll and a usable question box', async ({
    page,
  }) => {
    await page.goto('/public/ask');
    const input = page.getByLabel('Your question');
    await expect(input).toBeVisible();

    const widths = await page.evaluate(() => ({
      scroll: document.documentElement.scrollWidth,
      client: document.documentElement.clientWidth,
    }));
    expect(widths.scroll).toBeLessThanOrEqual(widths.client);

    const box = (await input.boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(375);
    await input.fill('Is a verbal agreement binding?');
    await expect(input).toHaveValue('Is a verbal agreement binding?');
    await expect(page.getByRole('button', { name: 'Send' })).toBeEnabled();
  });
});
