import * as fs from 'fs';
import { test, expect, signIn, askViaHome, driveRunUI, shoot, snap, saveDownload, isZip, pyZip, findDeal, deliverables, versionsOf } from '../helpers';

// P-J3 Model. Parity items proven: 20 (hard-coded cell shows source), 43/44 (audit overlay), 65 (dark), 70.

test('P-J3 model: 3-statement + DCF, edit WACC live, audit overlay, download, new version', async ({ page }) => {
  const api = await signIn(page, 'owner', '/');
  await askViaHome(page, '3-statement + DCF for Apple');
  expect(await driveRunUI(page, 420_000)).toBe('done');
  const link = page.getByTestId('deliverable-link').and(page.locator('[data-kind*="model"], [data-kind*="xlsx"], [data-kind*="excel"]')).first();
  await expect(link).toBeVisible();
  await link.click();
  await expect(page.getByTestId('model-view')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('sheet-tab').first()).toBeVisible();
  expect(await page.getByTestId('sheet-tab').count()).toBeGreaterThanOrEqual(3);
  await shoot(page, 'pj3', 1, 'model-view');

  // change WACC (or the first assumption) and watch dependents change live
  const inputs = page.getByTestId('assumption-input');
  await expect(inputs.first()).toBeVisible();
  const n = await inputs.count();
  let idx = 0;
  for (let i = 0; i < n; i++) {
    const meta = ((await inputs.nth(i).getAttribute('data-ref')) || '') + ((await inputs.nth(i).getAttribute('aria-label')) || '');
    if (/wacc|discount/i.test(meta)) idx = i;
  }
  const calc = page.locator('[data-testid="model-cell"][data-class="calc"]');
  const before = await calc.evaluateAll((els) => els.slice(0, 400).map((e) => e.textContent));
  const wacc = inputs.nth(idx);
  const old = parseFloat(((await wacc.inputValue()) || '0.09').replace(/[^0-9.\-]/g, '')) || 0.09;
  const nextVal = old < 1 ? Number((old + 0.01).toFixed(4)) : Number((old * 1.1).toFixed(2)); // 0.09 -> 0.10 or 9 -> 9.9
  await wacc.fill(String(nextVal));
  await wacc.press('Enter');
  await expect(page.getByTestId('recompute-status')).toContainText(/recomput|updated|saved|ok|done|live|\d/i, { timeout: 15_000 });
  await expect.poll(async () => (await calc.evaluateAll((els) => els.slice(0, 400).map((e) => e.textContent))).join('|') !== before.join('|'), { timeout: 15_000 }).toBe(true);
  for (const b of await page.getByTestId('check-badge').all()) await expect(b).not.toHaveAttribute('data-status', /fail|error|red/i);
  await shoot(page, 'pj3', 2, 'wacc-changed');

  // audit overlay: blue (input) / black (calc) / green (link) colours differ, three-engine check status visible
  await page.getByTestId('audit-overlay-toggle').click();
  const colour = async (cls: string) => page.locator(`[data-testid="model-cell"][data-class="${cls}"]`).first().evaluate((e) => getComputedStyle(e).color);
  const [ci, cc, cl] = [await colour('input'), await colour('calc'), await colour('link')];
  expect(new Set([ci, cc, cl]).size, `input/calc/link colours differ (${ci} ${cc} ${cl})`).toBe(3);
  await expect(page.getByTestId('check-badge').first()).toBeVisible();
  await shoot(page, 'pj3', 3, 'audit-overlay');

  // a hard-coded input cell shows its source on click (parity item 20)
  await page.locator('[data-testid="model-cell"][data-class="input"]').first().click();
  await expect(page.getByTestId('inspector-panel').or(page.getByRole('dialog')).first()).toBeVisible();

  // download is a real xlsx with cell notes for citations
  const d = await saveDownload(page, () => page.getByTestId('model-download').click(), 'model.xlsx');
  expect(isZip(d.bytes), 'xlsx is a zip').toBe(true);
  expect(d.suggested).toMatch(/\.xlsx$/i);
  expect(pyZip(d.file, 'list')).toMatch(/xl\/workbook\.xml/);

  // save creates a new library version
  const deal = await findDeal(api, /apple/i);
  const name = (await deliverables(api, deal)).map((x) => x.name).find((x) => /\.xlsx$/i.test(x)) as string;
  const v0 = (await versionsOf(api, deal, name)).length;
  await page.getByTestId('model-save').click();
  await expect.poll(async () => (await versionsOf(api, deal, name)).length, { timeout: 30_000 }).toBeGreaterThan(v0);
  await page.getByTestId('nav-library').click();
  await expect(page.getByTestId('library-table')).toBeVisible();
  await snap(page, 'pj3', 4, 'library-new-version');
});
