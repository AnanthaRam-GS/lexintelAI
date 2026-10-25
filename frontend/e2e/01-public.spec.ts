import { expect, test } from '@playwright/test';

import { fixtureFile } from './support';

const NO_COVERAGE = 'The available sources do not cover this question.';

test.describe('public questions', () => {
  test('a text question gets an answer with sources', async ({ page }) => {
    await page.goto('/public/ask');
    await page
      .getByLabel('Your question')
      .fill('Can I get bail in a murder case after long custody?');
    await page.getByRole('button', { name: 'Send' }).click();

    const answer = page.getByRole('article', { name: 'Plain-language legal information' });
    await expect(answer).toBeVisible();
    await expect(answer.getByRole('heading', { name: 'Sources' })).toBeVisible();
    await expect(answer.getByRole('link', { name: 'Learn more' }).first()).toBeVisible();
    await expect(answer.getByText(NO_COVERAGE)).toHaveCount(0);
  });

  test('an out-of-scope question gets the no-coverage answer', async ({ page }) => {
    await page.goto('/public/ask');
    await page.getByLabel('Your question').fill('How do I register a trademark for my bakery?');
    await page.getByRole('button', { name: 'Send' }).click();

    const answer = page.getByRole('article', { name: 'Plain-language legal information' });
    await expect(answer).toContainText(NO_COVERAGE);
    await expect(answer.getByRole('heading', { name: 'Sources' })).toHaveCount(0);
  });

  test('an uploaded FIR gets an answer', async ({ page }) => {
    await page.goto('/public/ask');
    await page.getByRole('button', { name: 'Add one PDF' }).click();
    await page.getByLabel('Choose PDF files').setInputFiles(fixtureFile('fir_synthetic.pdf'));
    await expect(page.getByText('fir_synthetic.pdf')).toBeVisible();
    await page
      .getByLabel('Your question')
      .fill('What does this FIR say happened, and what can the complainant do next?');
    const response = page.waitForResponse((r) => r.url().endsWith('/query/public/pdf'));
    await page.getByRole('button', { name: 'Send' }).click();

    expect((await response).status()).toBe(200);
    const answer = page.getByRole('article', { name: 'Plain-language legal information' });
    await expect(answer).toBeVisible();
    await expect(answer.getByRole('heading', { level: 2 })).not.toBeEmpty();
  });
});
