import { test, expect, signIn, runTask, driveRunUI, shoot, snap, findDeal, deliverables, versionsOf, items } from '../helpers';

// P-J5 Earnings update. Parity items proven: 40 (refresh on data change), 66 (notifications), 37 (versions).

test('P-J5 earnings: roll forward re-versions model and deck, diff shown, bell notified', async ({ page }) => {
  const api = await signIn(page, 'owner', '/');
  const deal = await findDeal(api, /apple/i);
  expect((await runTask(api, 'dcf', deal)).job.status).toBe('done');
  expect((await runTask(api, 'profile', deal)).job.status).toBe('done');
  const dels = await deliverables(api, deal);
  const model = dels.map((d) => d.name).find((n) => /\.xlsx$/i.test(n)) as string;
  const deck = dels.map((d) => d.name).find((n) => /\.pptx$/i.test(n)) as string;
  expect(model && deck, 'model and deck exist before the roll-forward').toBeTruthy();
  const [vm, vd] = [(await versionsOf(api, deal, model)).length, (await versionsOf(api, deal, deck)).length];
  const unread0 = items((await api.get('/notifications?unread=1')).json).length;

  await page.goto('/agents');
  const card = page.locator('[data-testid="agent-card"][data-agent="earnings_update"]').first();
  await expect(card).toBeVisible();
  await card.getByTestId('agent-run').click();
  const dlg = page.getByRole('dialog');
  if (await dlg.isVisible({ timeout: 2000 }).catch(() => false)) await dlg.getByRole('button', { name: /run|start|go|submit|confirm/i }).first().click();
  await expect(page.getByTestId('run-view')).toBeVisible({ timeout: 30_000 });
  expect(await driveRunUI(page, 480_000)).toBe('done');
  await shoot(page, 'pj5', 1, 'rollforward-run');

  expect((await versionsOf(api, deal, model)).length, 'model re-versioned').toBeGreaterThan(vm);
  expect((await versionsOf(api, deal, deck)).length, 'deck refreshed (new version)').toBeGreaterThan(vd);

  await page.goto(`/deals/${deal}`);
  await page.getByTestId('deal-tab-library').click();
  await page.getByTestId('deliverable-row').filter({ hasText: model }).first().click();
  await expect(page.getByTestId('versions-drawer')).toBeVisible();
  await page.getByTestId('version-diff').first().click();
  await expect(page.getByTestId('diff-view')).toBeVisible();
  await expect(page.getByTestId('diff-view')).not.toBeEmpty();
  await shoot(page, 'pj5', 2, 'model-diff');

  expect(items((await api.get('/notifications?unread=1')).json).length, 'a notification was created').toBeGreaterThan(unread0);
  await page.goto('/');
  await expect(page.getByTestId('notif-count')).toBeVisible();
  await page.getByTestId('notif-bell').click();
  await expect(page.getByTestId('notif-drawer')).toBeVisible();
  await expect(page.getByTestId('notif-item').first()).toBeVisible();
  await shoot(page, 'pj5', 3, 'bell');
});
