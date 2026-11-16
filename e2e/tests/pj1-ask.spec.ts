import * as fs from 'fs';
import * as path from 'path';
import { execFileSync } from 'child_process';
import { test, expect, loginUI, signIn, askViaCmdk, driveRunUI, jobIdFromUrl, shoot, snap, items, jobOf, TASKS, findDeal, deliverables, sleep, textOf } from '../helpers';

// P-J1 Ask. Parity items proven: 24-26 (run/step progress), 33 (live steps), 64 (shell), 70 (starter state).

async function assertRunQuality(page: any, api: any, task: string, status: string) {
  const id = jobIdFromUrl(page);
  expect(id, 'run view URL has the job id').toBeTruthy();
  // per-step time/cost and the time-saved estimate (D-032)
  await expect(page.getByTestId('run-cost')).toBeVisible();
  await expect(page.getByTestId('run-elapsed')).toBeVisible();
  expect(await page.getByTestId('run-step').count(), 'plan shows steps').toBeGreaterThan(0);
  const j = jobOf((await api.get(`/jobs/${id}`)).json);
  const kind = `${j.kind ?? ''} ${j.agent_id ?? ''} ${j.task_id ?? ''}`;
  expect(kind, `prompt for ${task} must route to that built-in agent`).toContain(task);
  if (status === 'done') {
    await expect(page.getByTestId('run-time-saved')).toBeVisible();
  } else {
    // no dead end: a failed run must name the missing engine stage in a step hint
    const failed = page.getByTestId('run-step').and(page.locator('[data-status="failed"]'));
    expect(await failed.count(), 'failed run has a failed step').toBeGreaterThan(0);
    const txt = (await failed.allTextContents()).join(' ');
    expect(txt, 'failed step shows a hint naming the missing engine stage').toMatch(/engine|stage|landed|not (yet )?(built|available)|install/i);
  }
}

test.describe('P-J1 ask', () => {
  test('P-J1 ask: login form, command bar, live plan, deliverable in library', async ({ page }) => {
    const t0 = Date.now();
    await loginUI(page, 'owner');
    expect(Date.now() - t0, 'login to shell under 10 s').toBeLessThan(10_000);
    await expect(page.getByTestId('starter-task').first()).toBeVisible(); // starter state, never blank (item 70)
    await shoot(page, 'pj1', 1, 'home');

    await askViaCmdk(page, 'Spread trading comps for Apple vs peers and add a football field');
    // plan with steps, estimate, cost and elapsed time are visible while it runs
    await expect(page.getByTestId('run-step').first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId('run-cost')).toBeVisible();
    await expect(page.getByTestId('run-elapsed')).toBeVisible();
    await snap(page, 'pj1', 2, 'run-plan');
    const status = await driveRunUI(page, 300_000);
    expect(status).toBe('done');
    await expect(page.getByTestId('run-time-saved')).toBeVisible();
    expect(await page.getByTestId('source-chip').count(), 'sourced answer').toBeGreaterThan(0);
    await shoot(page, 'pj1', 3, 'run-done');

    const link = page.getByTestId('deliverable-link').first();
    await expect(link).toBeVisible();
    await link.click();
    await expect(page.getByTestId('app-shell')).toBeVisible();
    await expect(page).not.toHaveURL(/\/runs\//);
    await shoot(page, 'pj1', 4, 'deliverable-opened');

    const api = await signIn(page, 'owner', '');
    const deal = await findDeal(api, /apple/i);
    await page.goto(`/deals/${deal}`);
    await page.getByTestId('deal-tab-library').click();
    await expect(page.getByTestId('deliverable-row').first()).toBeVisible();
    await shoot(page, 'pj1', 5, 'library');
  });

  test('P-J1 ask: email-in request becomes a run with source=email', async ({ page }) => {
    const api = await signIn(page, 'owner', '/');
    const md = process.env.E2E_MAILDIR as string;
    const cfg = { kind: 'maildir', path: md, folder: 'new', poll_seconds: 60, send_enabled: false,
      allowed_senders: ['owner@meridian.example'], allowed_senders_json: ['owner@meridian.example'] };
    const r = await api.put('/firm/mailbox', cfg);
    expect(r.status, `PUT /firm/mailbox ${r.body.toString().slice(0, 200)}`).toBeLessThan(300);
    const subj = `Spread trading comps for Apple vs peers ${Date.now()}`;
    fs.writeFileSync(path.join(md, 'new', `${Date.now()}.eml`),
      `From: owner@meridian.example\nTo: agent@meridian.example\nSubject: ${subj}\nMessage-ID: <${Date.now()}@e2e.example>\n` +
      `Date: Mon, 16 Nov 2026 09:00:00 +0000\nContent-Type: text/plain; charset=utf-8\n\nPlease spread trading comps for Apple vs peers and add a football field.\n`);
    execFileSync('python3', ['-m', 'om.api', 'poll-mail', '--data', process.env.E2E_DATA_DIR as string], {
      cwd: path.resolve(__dirname, '..', '..'), env: { ...process.env, ACRETIA_LLM_MODE: 'replay' }, stdio: 'pipe',
    });
    let job: any;
    for (let i = 0; i < 60 && !job; i++) {
      job = items((await api.get('/jobs?limit=200')).json).find((j) => j.source === 'email' && /comps/i.test(JSON.stringify(j)));
      if (!job) await sleep(500);
    }
    expect(job, 'poll-mail created an email job').toBeTruthy();
    await page.goto(`/runs/${job.id}`);
    await expect(page.getByTestId('run-view')).toBeVisible();
    expect(await driveRunUI(page, 300_000)).toBe('done');
    await expect(page.getByTestId('run-row').first().or(page.getByTestId('run-view'))).toContainText(/email/i);
    await shoot(page, 'pj1', 6, 'email-run');
  });

  for (const t of TASKS) {
    test(`P-J1 ask catalogue (command bar): ${t.id}`, async ({ page }) => {
      const api = await signIn(page, 'owner', '/');
      await askViaCmdk(page, t.prompt);
      const status = await driveRunUI(page, 480_000);
      expect(['done', 'failed']).toContain(status);
      await assertRunQuality(page, api, t.id, status);
      if (['comps', 'three_statement', 'profile'].includes(t.id)) await snap(page, 'pj1', 20, `catalogue-${t.id}`);
    });
  }

  for (const t of TASKS) {
    test(`P-J1 ask catalogue (agent library): ${t.id}`, async ({ page }) => {
      const api = await signIn(page, 'owner', '/agents');
      await expect(page.getByTestId('agent-card').first()).toBeVisible();
      const card = page.locator(`[data-testid="agent-card"][data-agent="${t.id}"]`).first();
      await expect(card, `agent library has a built-in card for ${t.id}`).toBeVisible();
      await card.getByTestId('agent-run').click();
      // a run may need a deal / prompt confirmation dialog: submit it if one appears
      const dlg = page.getByRole('dialog');
      if (await dlg.isVisible({ timeout: 2000 }).catch(() => false)) {
        const inp = dlg.getByRole('textbox').first();
        if (await inp.isVisible().catch(() => false)) if (!(await inp.inputValue())) await inp.fill(t.prompt);
        await dlg.getByRole('button', { name: /run|start|go|submit|confirm/i }).first().click();
      }
      await expect(page.getByTestId('run-view')).toBeVisible({ timeout: 30_000 });
      const status = await driveRunUI(page, 480_000);
      expect(['done', 'failed']).toContain(status);
      await assertRunQuality(page, api, t.id, status);
    });
  }
});
