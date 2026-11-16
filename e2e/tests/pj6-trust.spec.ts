import * as path from 'path';
import { test, expect, signIn, runTask, shoot, snap, findDeal, deliverables, fixtures, Page } from '../helpers';

// P-J6 Trust. Parity items proven: 15, 16, 17, 21.

async function expectInspector(page: Page) {
  await expect(page.getByTestId('pdf-viewer')).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId('bbox-highlight').first()).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId('inspector-panel')).toBeVisible();
  await expect(page.getByTestId('inspector-page')).toContainText(/\d/);
  await expect(page.getByTestId('inspector-asof')).toContainText(/\d{4}|\d{1,2}[\/.-]\d{1,2}/);
  const href = await page.getByTestId('inspector-source-link').first().getAttribute('href');
  expect(href, 'source link has a target').toBeTruthy();
  await expect(page.getByTestId('inspector-quote')).not.toBeEmpty();
}

test('P-J6 trust: model number, grid cell and deck source line each open the highlighted source', async ({ page }) => {
  const api = await signIn(page, 'owner', '/');
  const deal = await findDeal(api, /apple/i);
  expect((await runTask(api, 'dcf', deal)).job.status).toBe('done');
  expect((await runTask(api, 'profile', deal)).job.status).toBe('done');
  const dels = await deliverables(api, deal);
  const model = dels.map((d) => d.name).find((n) => /\.xlsx$/i.test(n)) as string;
  const deck = dels.map((d) => d.name).find((n) => /\.pptx$/i.test(n)) as string;

  // model cell
  await page.goto(`/deals/${deal}/models/${encodeURIComponent(model)}`);
  await expect(page.getByTestId('model-view')).toBeVisible({ timeout: 30_000 });
  await page.locator('[data-testid="model-cell"][data-class="link"], [data-testid="model-cell"][data-class="input"]').first().click();
  await expectInspector(page);
  await shoot(page, 'pj6', 1, 'model-to-source');

  // deck source line
  await page.goto(`/deals/${deal}/decks/${encodeURIComponent(deck)}`);
  await expect(page.getByTestId('deck-view')).toBeVisible({ timeout: 30_000 });
  await page.getByTestId('slide-source-line').first().click();
  await expectInspector(page);
  await shoot(page, 'pj6', 2, 'deck-to-source');

  // grid cell (needs documents + a column)
  await page.goto(`/deals/${deal}`);
  await page.getByTestId('deal-tab-documents').click();
  const docs = await page.getByTestId('doc-row').count();
  if (docs === 0) await page.getByTestId('upload-input').setInputFiles([path.join(fixtures(), 'table.pdf')]);
  await page.getByTestId('deal-tab-grid').click();
  if ((await page.getByTestId('grid-cell').count()) === 0) {
    await page.getByTestId('grid-add-column').click();
    await page.getByTestId('column-prompt').fill('What was segment revenue? Cite the page.');
    await page.getByTestId('column-submit').click();
  }
  const cell = page.locator('[data-testid="grid-cell"]:not([data-state*="pending"]):not([data-state*="queued"])').filter({ hasNotText: /^\s*$/ }).first();
  await expect(cell).toBeVisible({ timeout: 120_000 });
  await cell.click();
  await expectInspector(page);
  await shoot(page, 'pj6', 3, 'grid-to-source');
});
