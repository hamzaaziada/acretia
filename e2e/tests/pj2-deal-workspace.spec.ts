import * as path from 'path';
import { test, expect, signIn, newDealUI, uploadAndIndex, shoot, snap, fixtures } from '../helpers';

// P-J2 Deal workspace. Parity items proven: 1 (first cells < 10 s), 2, 9, 13, 15, 16.

const READY = /^(?!.*(pending|queued|running|loading|empty|skeleton|waiting)).+$/i;

test('P-J2 deal workspace: create deal, VDR zip, diligence grid, cited cell opens the bbox', async ({ page }) => {
  await signIn(page, 'owner', '/');
  const name = `Project E2E ${Date.now()}`;
  await newDealUI(page, name);
  await shoot(page, 'pj2', 1, 'new-deal');

  // 52 PDFs (2 Arabic) in one zip: indexed with progress
  await uploadAndIndex(page, [path.join(fixtures(), 'vdr.zip')], { min: 50, timeout: 420_000 });
  const rows = page.getByTestId('doc-row');
  expect(await rows.count()).toBeGreaterThanOrEqual(50);
  const statuses = await rows.evaluateAll((els) => els.map((e) => (e as HTMLElement).dataset.status || ''));
  expect(statuses.filter((s) => /fail|error/i.test(s)), 'no indexing failures on a clean VDR').toHaveLength(0);
  await expect(page.getByTestId('doc-row').filter({ hasText: /تقرير/ }).first(), 'Arabic documents are listed').toBeVisible();
  await shoot(page, 'pj2', 2, 'documents-indexed');

  // grid: add a question column, see the cost estimate first, cells fill
  await page.getByTestId('deal-tab-grid').click();
  await expect(page.getByTestId('grid')).toBeVisible();
  await page.getByTestId('grid-add-column').click();
  await page.getByTestId('column-prompt').fill('What was FY2024 revenue and Adjusted EBITDA? Cite the page.');
  await expect(page.getByTestId('grid-estimate')).toBeVisible();
  await expect(page.getByTestId('grid-estimate')).toContainText(/\$|usd|min|sec|cost/i);
  await shoot(page, 'pj2', 3, 'grid-estimate');
  const t0 = Date.now();
  await page.getByTestId('column-submit').click();
  const cells = page.getByTestId('grid-cell');
  await expect.poll(async () => (await cells.evaluateAll((els) => els.map((e) => (e as HTMLElement).dataset.state || ''))).filter((s) => s && READY.test(s)).length, { timeout: 10_000 }).toBeGreaterThan(0);
  expect(Date.now() - t0, 'first grid cells within 10 s (parity item 1)').toBeLessThan(10_000);
  await expect.poll(async () => (await cells.evaluateAll((els) => els.map((e) => (e as HTMLElement).dataset.state || ''))).filter((s) => /pending|queued|running|loading/i.test(s)).length, { timeout: 240_000 }).toBe(0);
  await shoot(page, 'pj2', 4, 'grid-filled');

  await expect(page.getByTestId('risks-panel')).toBeVisible();
  await expect(page.getByTestId('risks-panel')).not.toBeEmpty();
  await snap(page, 'pj2', 5, 'risks-panel');

  // click a cell: PDF opens at the page with the bbox highlighted
  await cells.filter({ hasNotText: /^\s*$/ }).first().click();
  await expect(page.getByTestId('pdf-viewer')).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId('bbox-highlight').first()).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId('inspector-page')).toContainText(/\d/);
  await shoot(page, 'pj2', 6, 'cell-to-bbox');
});
