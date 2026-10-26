import { expect, test } from '@playwright/test';

import { fixtureFile, signIn } from './support';

const TEXT_QUERY = 'Regular bail after long custody for an accused under Section 61 BNS';

test.describe.configure({ mode: 'serial' });

test.describe('lawyer workspace', () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page, 'lawyer');
  });

  test('a text query shows precedents with relative relevance and the cited badge', async ({
    page,
  }) => {
    await page.goto('/professional/query');
    await page.getByLabel('Enter Legal Proposition or Fact Pattern').fill(TEXT_QUERY);
    await page.getByRole('button', { name: /Execute Legal Research/i }).click();

    await expect(page.getByTestId('professional-results-view')).toBeVisible();
    await page.getByRole('button', { name: /Precedent Citations/i }).click();
    const precedents = page.getByRole('region', { name: 'Retrieved precedents' });
    await expect(precedents.getByTestId('relevance-label').first()).toContainText(
      'Relative relevance',
    );
    await expect(precedents.getByTestId('cited-in-answer').first()).toHaveText('Cited in answer');
  });

  test('a FIR brief shows parties, chronology, procedural considerations and evidence', async ({
    page,
  }) => {
    await page.goto('/professional/upload');
    await page.locator('input[type="file"]').setInputFiles(fixtureFile('fir_synthetic.pdf'));
    await page.getByRole('button', { name: /Begin Private Analysis/i }).click();

    const results = page.getByTestId('professional-results-view');
    await expect(results).toBeVisible();
    for (const heading of [
      'Parties & Roles',
      'Chronology',
      'Procedural Considerations',
      'Evidence Identified',
    ]) {
      await expect(results.getByText(heading, { exact: true })).toBeVisible();
    }
    // From the synthetic FIR itself (local document map), with its P# reference.
    await expect(results.getByText(/Complainant: Meera Placeholder \[P\d+/)).toBeVisible();
    await expect(results.getByText(/2024-03-04/).first()).toBeVisible();
  });

  test('history lists both queries', async ({ page }) => {
    await page.goto('/professional/history');
    const history = page.getByTestId('history-list');
    await expect(history.getByText(TEXT_QUERY).first()).toBeVisible();
    // The upload page sends its default question with the brief request.
    await expect(history.getByText('Analyze this legal document.').first()).toBeVisible();
  });

  test('all five analytics tabs render with data', async ({ page }) => {
    await page.goto('/professional/analytics');
    const tabs: [RegExp, string, string | null][] = [
      [/Offense Trends/i, 'tab-offense-trends', 'offense-empty'],
      [/Outcome Distribution/i, 'tab-outcome-distribution', null],
      [/Section Co-occurrence/i, 'tab-section-cooccurrence', 'cooccurrence-empty'],
      [/IPC-BNS Map/i, 'tab-ipc-bns', null],
      [/NCRB Statistics/i, 'tab-ncrb-stats', 'ncrb-empty'],
    ];
    for (const [name, panel, empty] of tabs) {
      await page.getByRole('button', { name }).click();
      const content = page.getByTestId(panel);
      await expect(content).toBeVisible();
      if (empty) await expect(page.getByTestId(empty)).toHaveCount(0);
      await expect(content).toContainText(/\d/); // counts, sections or years from the seeded data
    }
    await page.getByRole('button', { name: /IPC-BNS Map/i }).click();
    await expect(page.getByTestId('tab-ipc-bns')).toContainText('302');
    // A pair printed in NCRB Table 1A.4 (migration 0011): its source page and no change type.
    await page.getByPlaceholder('Search section or description...').fill('153A');
    const enmity = page
      .getByTestId('tab-ipc-bns')
      .getByRole('row')
      .filter({ hasText: 'Table 1A.4' });
    await expect(enmity.first()).toContainText('NCRB 2024, Table 1A.4, p. 50');
    await expect(enmity.first()).toContainText('Not specified');
  });
});
