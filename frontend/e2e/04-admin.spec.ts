import { expect, type Page, test } from '@playwright/test';

import { fixtureFile, signIn } from './support';

const INGEST_FILE = 'ingest_judgment_synthetic.pdf';
const STORES = ['PostgreSQL status', 'ChromaDB status', 'Keyword index status'];

test.describe.configure({ mode: 'serial' });

async function documentCount(page: Page): Promise<number> {
  await page.goto('/admin');
  const text = await page.getByText(/^\d+ documents$/).textContent();
  return Number(text!.split(' ')[0]);
}

async function expectHealthyStores(page: Page): Promise<void> {
  for (const store of STORES) {
    await expect(page.getByRole('region', { name: store })).toContainText('Healthy');
  }
}

async function submitIngest(page: Page): Promise<void> {
  await page.goto('/admin/ingest');
  await page.getByLabel('Choose PDF files').setInputFiles(fixtureFile(INGEST_FILE));
  await page.getByLabel(`Document type for ${INGEST_FILE}`).selectOption('judgment');
  await page
    .getByRole('checkbox', { name: 'I understand this is a permanent corpus update' })
    .check();
  await page.getByRole('button', { name: 'Start ingestion' }).click();
}

test.describe('admin', () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page, 'admin');
  });

  test('the status page shows healthy stores', async ({ page }) => {
    await page.goto('/admin');
    await expectHealthyStores(page);
  });

  test('ingesting a fixture PDF completes and the corpus count goes up by one', async ({
    page,
  }) => {
    test.setTimeout(240_000);
    const before = await documentCount(page);
    await submitIngest(page);

    const job = page
      .getByTestId('ingestion-jobs')
      .getByRole('listitem')
      .filter({ hasText: INGEST_FILE });
    await expect(job).toContainText('COMPLETED', { timeout: 180_000 });
    expect(await documentCount(page)).toBe(before + 1);
    await expectHealthyStores(page);
  });

  test('uploading the same PDF again is refused as a duplicate', async ({ page }) => {
    const before = await documentCount(page);
    const upload = page.waitForResponse((r) => r.url().endsWith('/ingest/upload'));
    await submitIngest(page);

    const response = await upload;
    expect(response.status()).toBe(409);
    expect(((await response.json()) as { code: string }).code).toBe('DOCUMENT_ALREADY_INGESTED');
    // The workspace has no duplicate-specific copy; it shows its submission failure alert and starts no job.
    await expect(
      page.getByRole('region', { name: 'Select documents and metadata' }).getByRole('alert'),
    ).toBeVisible();
    await expect(page.getByTestId('ingestion-jobs')).toHaveCount(0);
    expect(await documentCount(page)).toBe(before);
  });
});
