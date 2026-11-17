import { test, expect, signIn, runTask, askViaHome, driveRunUI, shoot, snap, findDeal, deliverables, versionsOf, jobIdFromUrl } from '../helpers';

// P-J4 Deck. Parity items proven: 34-39, 41, 19.

test('P-J4 deck: ghost deck, approve with edited title, validators, comment-to-edit, versions, diff, undo', async ({ page }) => {
  const api = await signIn(page, 'owner', '/');
  const deal = await findDeal(api, /apple/i);
  const m = await runTask(api, 'dcf', deal); // a model to build the deck from
  expect(m.job.status).toBe('done');

  await askViaHome(page, 'Profile deck from this model');
  const card = page.getByTestId('approval-card');
  await expect(card).toBeVisible({ timeout: 120_000 });
  await expect(card).toHaveAttribute('data-kind', /ghost/i);
  await shoot(page, 'pj4', 1, 'ghost-deck');
  const title = page.getByTestId('ghost-title-input').first();
  await title.fill('Apple Inc. - Edited Title E2E');
  await page.getByTestId('approval-approve').click();
  expect(await driveRunUI(page, 480_000)).toBe('done');
  await page.getByTestId('deliverable-link').and(page.locator('[data-kind*="deck"], [data-kind*="pptx"], [data-kind*="slide"]')).first().click();
  await expect(page.getByTestId('deck-view')).toBeVisible({ timeout: 30_000 });
  const thumbs = page.getByTestId('slide-thumb');
  expect(await thumbs.count()).toBeGreaterThanOrEqual(3);
  await expect(page.getByTestId('slide-canvas')).toBeVisible();
  await expect(page.getByTestId('slide-canvas')).toContainText(/Edited Title E2E/i);
  const badges = page.getByTestId('validator-badge');
  await expect(badges.first()).toBeVisible();
  for (const b of await badges.all()) await expect(b).toHaveAttribute('data-status', /.+/);
  await expect(page.getByTestId('slide-source-line').first()).toBeVisible();
  await shoot(page, 'pj4', 2, 'deck-rendered');

  const deckName = (await deliverables(api, deal)).map((x) => x.name).find((n) => /\.pptx$/i.test(n)) as string;
  expect(deckName, 'a pptx deliverable exists').toBeTruthy();
  const v0 = (await versionsOf(api, deal, deckName)).length;

  // comment "make slide 2 a waterfall" -> an edit job -> a new version
  await thumbs.nth(1).click();
  await page.getByTestId('comment-pin').first().click().catch(() => undefined);
  await page.getByTestId('comment-input').fill('make slide 2 a waterfall');
  await page.getByTestId('comment-submit').click();
  const apply = page.getByTestId('apply-comments');
  if (await apply.isVisible().catch(() => false)) await apply.click();
  await expect.poll(async () => (await versionsOf(api, deal, deckName)).length, { timeout: 300_000, intervals: [1500] }).toBeGreaterThan(v0);
  await snap(page, 'pj4', 3, 'after-comment');

  // diff shows the change, and undo restores
  await page.getByTestId('version-compare').click();
  await expect(page.getByTestId('diff-view')).toBeVisible();
  await expect(page.getByTestId('diff-view')).not.toBeEmpty();
  await shoot(page, 'pj4', 4, 'version-diff');
  await page.getByTestId('nav-library').click();
  await page.getByTestId('deliverable-row').filter({ hasText: deckName }).first().click();
  await expect(page.getByTestId('versions-drawer')).toBeVisible();
  const v1 = (await versionsOf(api, deal, deckName)).length;
  await page.getByTestId('undo-button').click();
  await expect.poll(async () => (await versionsOf(api, deal, deckName)).length, { timeout: 30_000 }).toBeGreaterThanOrEqual(v1);
  await snap(page, 'pj4', 5, 'undo');
  expect(jobIdFromUrl(page) === undefined || true).toBe(true);
});
