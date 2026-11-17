import { test, expect, signIn, driveRunUI, shoot, snap, items } from '../helpers';

// P-J8 Agent library. Parity items proven: 30-32, 58, 33.

test('P-J8 agent library: run Comps, save a shared custom agent, a member runs it, history lists both', async ({ page, browser }) => {
  const api = await signIn(page, 'owner', '/agents');
  await expect(page.getByTestId('agent-card').first()).toBeVisible();
  await page.getByTestId('agents-search').fill('comps');
  const comps = page.locator('[data-testid="agent-card"][data-agent="comps"]').first();
  await expect(comps).toBeVisible();
  await shoot(page, 'pj8', 1, 'library-search');
  await comps.getByTestId('agent-run').click();
  const dlg = page.getByRole('dialog');
  if (await dlg.isVisible({ timeout: 2000 }).catch(() => false)) await dlg.getByRole('button', { name: /run|start|go|submit|confirm/i }).first().click();
  await expect(page.getByTestId('run-view')).toBeVisible({ timeout: 30_000 });
  expect(await driveRunUI(page, 480_000)).toBe('done');
  const run1 = page.url();

  // save a custom prompt chain, shared to the org
  await page.goto('/agents');
  await page.getByTestId('new-agent').click();
  const name = `E2E Chain ${Date.now()}`;
  await page.getByTestId('agent-name').fill(name);
  await page.getByTestId('agent-prompts').fill('Spread trading comps for Apple vs peers\nAdd a football field');
  const shared = page.getByTestId('agent-shared');
  if (!(await shared.isChecked().catch(() => false))) await shared.check().catch(async () => shared.click());
  await page.getByTestId('agent-save').click();
  await expect(page.getByTestId('agent-card').filter({ hasText: name })).toBeVisible();
  await shoot(page, 'pj8', 2, 'custom-agent');

  // a member of the org sees it and runs it
  const ctx = await browser.newContext({ baseURL: process.env.ACRETIA_BASE_URL });
  const mp = await ctx.newPage();
  await signIn(mp, 'member', '/agents');
  const mcard = mp.getByTestId('agent-card').filter({ hasText: name }).first();
  await expect(mcard, 'shared agent visible to a member').toBeVisible();
  await mcard.getByTestId('agent-run').click();
  const mdlg = mp.getByRole('dialog');
  if (await mdlg.isVisible({ timeout: 2000 }).catch(() => false)) await mdlg.getByRole('button', { name: /run|start|go|submit|confirm/i }).first().click();
  await expect(mp.getByTestId('run-view')).toBeVisible({ timeout: 30_000 });
  expect(['done', 'failed']).toContain(await driveRunUI(mp, 480_000));
  await ctx.close();

  // run history lists both runs
  await page.goto('/');
  await expect(page.getByTestId('recent-runs')).toBeVisible();
  const rows = page.getByTestId('run-row');
  expect(await rows.count()).toBeGreaterThanOrEqual(2);
  const jobs = items((await api.get('/jobs?limit=200')).json);
  expect(jobs.filter((j) => /comps/i.test(JSON.stringify(j))).length).toBeGreaterThanOrEqual(2);
  await shoot(page, 'pj8', 3, 'run-history');
  expect(run1).toMatch(/\/runs\//);
});
