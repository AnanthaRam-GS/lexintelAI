import { expect, test } from '@playwright/test';

import { signIn } from './support';

test.describe('access control', () => {
  test('an anonymous visitor is sent from /professional to sign in', async ({ page }) => {
    await page.goto('/professional');
    await expect(page).toHaveURL('/login?next=%2Fprofessional');
    await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible();
  });

  test('a lawyer is denied /admin', async ({ page }) => {
    await signIn(page, 'lawyer');
    const denied = page
      .waitForResponse((r) => r.url().endsWith('/ingest/corpus/stats'), { timeout: 5_000 })
      .catch(() => null);
    await page.goto('/admin');
    await expect(page).toHaveURL('/professional');
    await expect(page.getByRole('region', { name: 'ChromaDB status' })).toHaveCount(0);
    // If the admin page asked the API at all before redirecting, the API refused it too.
    const response = await denied;
    if (response) expect(response.status()).toBe(403);
  });
});
