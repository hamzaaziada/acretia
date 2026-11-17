import * as path from 'path';
import { test, expect, signIn, shoot, snap, fixtures, items, newDealUI, findDeal, USERS, DEMO_PW } from '../helpers';

// P-J7 Firm setup. Parity items proven: 58, 60, 61, 63 (admin surfaces), 55/56 (permissions inherited).

test('P-J7 firm setup: templates, definitions, invite, connector, mailbox; viewer is read-only; deal carries definitions', async ({ page, browser }) => {
  const api = await signIn(page, 'owner', '/settings/templates');
  const EBITDA = 'EBITDA before one-offs and IFRS 16 lease costs (E2E)';
  const NETDEBT = 'Borrowings less cash and equivalents, excluding leases (E2E)';

  // templates + a sample deck
  await expect(page.getByTestId('template-upload')).toBeAttached();
  await page.getByTestId('template-upload').setInputFiles([path.join(fixtures(), 'template.pptx'), path.join(fixtures(), 'sample-deck.pptx')]);
  await expect.poll(async () => items((await api.get('/firm/assets')).json).length, { timeout: 60_000 }).toBeGreaterThanOrEqual(2);
  await shoot(page, 'pj7', 1, 'templates');

  // accounting definitions
  await page.goto('/settings/definitions');
  await expect(page.getByTestId('definitions-form')).toBeVisible();
  await page.getByTestId(/^definition-.*ebitda/i).first().fill(EBITDA);
  await page.getByTestId(/^definition-.*net.?debt/i).first().fill(NETDEBT);
  await page.getByTestId('definitions-form').getByRole('button', { name: /save|apply|update/i }).click();
  await expect.poll(async () => JSON.stringify((await api.get('/firm/definitions')).json), { timeout: 20_000 }).toContain('E2E');
  await shoot(page, 'pj7', 2, 'definitions');

  // invite a viewer
  await page.goto('/settings/users');
  await expect(page.getByTestId('members-table')).toBeVisible();
  await page.getByTestId('invite-button').click();
  await page.getByTestId('invite-email').fill(`invited.${Date.now()}@meridian.example`);
  await page.getByTestId('invite-role').selectOption('viewer').catch(async () => {
    await page.getByTestId('invite-role').click();
    await page.getByRole('option', { name: /viewer/i }).click();
  });
  await page.getByTestId('invite-submit').click();
  await expect(page.getByTestId('invite-link')).toBeVisible();
  expect(((await page.getByTestId('invite-link').textContent()) || '') + ((await page.getByTestId('invite-link').inputValue().catch(() => '')) || '')).toMatch(/https?:\/\/|\/invite/i);
  await shoot(page, 'pj7', 3, 'invite');

  // connector
  await page.goto('/settings/connectors');
  await page.getByTestId('connector-add').click();
  const dlg = page.getByRole('dialog');
  await expect(dlg).toBeVisible();
  await dlg.getByRole('textbox', { name: /name/i }).first().fill('E2E SharePoint');
  await dlg.getByRole('button', { name: /add|save|connect|create/i }).last().click();
  await expect.poll(async () => JSON.stringify((await api.get('/firm/connectors')).json), { timeout: 20_000 }).toContain('E2E SharePoint');
  await snap(page, 'pj7', 4, 'connectors');

  // mailbox with sending disabled
  await page.goto('/settings/mailbox');
  await expect(page.getByTestId('mailbox-form')).toBeVisible();
  await expect(page.getByTestId('mailbox-send-enabled')).not.toBeChecked();
  await page.getByTestId('mailbox-form').getByRole('button', { name: /save|apply|update/i }).click();
  expect(((await api.get('/firm/mailbox')).json || {}).send_enabled).toBeFalsy();
  await snap(page, 'pj7', 5, 'mailbox');

  // a new deal carries the firm definitions
  await page.goto('/');
  const dealName = `Firm Defs ${Date.now()}`;
  await newDealUI(page, dealName);
  const id = await findDeal(api, new RegExp(dealName));
  const detail = JSON.stringify((await api.get(`/deals/${id}`)).json);
  expect(detail).toContain('E2E');

  // the viewer cannot mutate anything
  const ctx = await browser.newContext({ baseURL: process.env.ACRETIA_BASE_URL });
  const vp = await ctx.newPage();
  const vapi = await signIn(vp, 'viewer', '/');
  await expect(vp.getByTestId('app-shell')).toBeVisible();
  await vp.getByTestId('nav-deals').click();
  await expect(vp.getByTestId('new-deal')).toHaveCount(0).catch(async () => expect(vp.getByTestId('new-deal')).toBeDisabled());
  expect((await vapi.post('/deals', { name: 'viewer must not create' })).status).toBe(403);
  expect((await vapi.put('/firm/definitions', {})).status).toBe(403);
  await vp.goto('/settings/users');
  await expect(vp.getByTestId('invite-button')).toHaveCount(0).catch(async () => expect(vp.getByTestId('invite-button')).toBeDisabled());
  await shoot(vp, 'pj7', 6, 'viewer-readonly');
  await ctx.close();
});
