import * as fs from 'fs';
import * as path from 'path';
import {
  test, expect, signIn, runTask, startJob, waitJob, findDeal, deliverables, versionsOf, items, fixtures, saveDownload, isZip, pyZip, sha,
  driveRunUI, askViaHome, pageBgLum, setTheme, setLocale, newDealUI, enc, Api, Page, shoot, snap, sleep, TASKS, USERS, DEMO_PW,
} from '../helpers';

// One test per testable item of docs/parity-spec.md "Acceptance checklist" (tag @item-N in the title).
// Not browser-testable and therefore not listed: 42, 43, 45, 46 (Excel/Word plug-ins, reconcile/structure engines), 51 (clipboard),
// 59 (SCIM), 62 (connector permission mirroring), 68 (audio). Items whose feature is absent FAIL; none are skipped.

const J = 'parity';
const S: { deal?: string; nile?: string; model?: string; deck?: string; comps?: string } = {};

async function setup(page: Page): Promise<Api> {
  const api = await signIn(page, 'owner', '/');
  S.deal ??= await findDeal(api, /apple/i);
  S.nile ??= await findDeal(api, /nile|sewedy/i);
  return api;
}

async function artifacts(api: Api) {
  if (!S.model || !S.deck) {
    await setup0(api);
  }
  return S as Required<Pick<typeof S, 'deal' | 'model' | 'deck'>>;
}
async function setup0(api: Api) {
  S.deal ??= await findDeal(api, /apple/i);
  expect((await runTask(api, 'dcf', S.deal)).job.status).toBe('done');
  expect((await runTask(api, 'profile', S.deal)).job.status).toBe('done');
  const d = await deliverables(api, S.deal);
  S.model = d.map((x) => x.name).find((n) => /\.xlsx$/i.test(n));
  S.deck = d.map((x) => x.name).find((n) => /\.pptx$/i.test(n));
  expect(S.model && S.deck, 'model and deck deliverables exist').toBeTruthy();
}

async function compsRun(api: Api): Promise<string> {
  if (!S.comps) {
    S.deal ??= await findDeal(api, /apple/i);
    const r = await runTask(api, 'comps', S.deal);
    expect(r.job.status).toBe('done');
    S.comps = r.id;
  }
  return S.comps;
}

async function gridWithCells(page: Page, api: Api, deal?: string) {
  deal ??= S.deal ?? (await findDeal(api, /apple/i));
  await page.goto(`/deals/${deal}`);
  await page.getByTestId('deal-tab-grid').click();
  await expect(page.getByTestId('grid')).toBeVisible();
  if ((await page.getByTestId('grid-cell').count()) === 0) {
    await page.getByTestId('grid-add-column').click();
    await page.getByTestId('column-prompt').fill('What was revenue? Cite the page.');
    await page.getByTestId('column-submit').click();
  }
  await expect(page.getByTestId('grid-cell').first()).toBeVisible({ timeout: 60_000 });
}

const t = (n: number, title: string, fn: (a: { page: Page; browser: any }) => Promise<void>) =>
  test(`parity item ${n}: ${title} @item-${n}`, async ({ page, browser }) => fn({ page, browser }));

// ---------------------------------------------------------------- Grid (1-14)
t(1, 'first grid cells within 10 s of adding a column', async ({ page }) => {
  const api = await setup(page);
  await page.goto(`/deals/${S.deal}`);
  await page.getByTestId('deal-tab-grid').click();
  await page.getByTestId('grid-add-column').click();
  await page.getByTestId('column-prompt').fill('Who is the auditor and on which page is that stated?');
  const t0 = Date.now();
  await page.getByTestId('column-submit').click();
  await expect(page.locator('[data-testid="grid-cell"][data-state]:not([data-state*="pending"]):not([data-state*="queued"]):not([data-state*="empty"]):not([data-state*="running"])').first()).toBeVisible({ timeout: 10_000 });
  expect(Date.now() - t0).toBeLessThan(10_000);
  void api;
});
t(2, 'two-step creation wizard (documents, then split into columns)', async ({ page }) => {
  await setup(page);
  await page.goto(`/deals/${S.deal}`);
  await page.getByTestId('deal-tab-grid').click();
  await page.getByTestId('grid-add-column').click();
  const w = page.getByTestId('grid-wizard');
  await expect(w).toBeVisible();
  await expect(w).toContainText(/step 1|1 of 2|choose documents|select documents/i);
  await w.getByRole('button', { name: /next|continue/i }).click();
  await expect(w).toContainText(/step 2|2 of 2|columns|split/i);
});
t(3, 'a column run condition skips rows visibly', async ({ page }) => {
  const api = await setup(page);
  await gridWithCells(page, api);
  await page.getByTestId('grid-add-column').click();
  await page.getByTestId('column-prompt').fill('Is there a change-of-control clause?');
  await page.getByLabel(/run condition|only run if|condition/i).first().fill('column 1 is empty');
  await page.getByTestId('column-submit').click();
  await expect(page.locator('[data-testid="grid-cell"][data-state*="skip"]').first()).toBeVisible({ timeout: 60_000 });
});
t(4, 'editing an input variable re-runs dependent columns', async ({ page }) => {
  const api = await setup(page);
  await gridWithCells(page, api);
  await page.getByTestId('column-manager').or(page.getByRole('button', { name: /column manager/i })).first().click();
  const v = page.getByRole('textbox', { name: /variable|input/i }).first();
  await expect(v).toBeVisible();
  await v.fill('FY2023');
  await v.press('Enter');
  await expect(page.locator('[data-testid="grid-cell"][data-state*="running"], [data-testid="grid-cell"][data-state*="pending"], [data-testid="grid-cell"][data-state*="queued"]').first()).toBeVisible({ timeout: 10_000 });
});
t(5, 'Column Manager: rename, reorder, edit prompt, swap model, bulk run', async ({ page }) => {
  const api = await setup(page);
  await gridWithCells(page, api);
  await page.getByRole('button', { name: /column manager|manage columns/i }).or(page.getByTestId('column-manager')).first().click();
  const cm = page.getByTestId('column-manager');
  await expect(cm).toBeVisible();
  for (const re of [/rename/i, /(move|reorder|drag)/i, /prompt/i, /model/i, /(run all|bulk run|run selected)/i])
    await expect(cm.getByRole('button', { name: re }).or(cm.getByLabel(re)).first(), `Column Manager offers ${re}`).toBeVisible();
});
t(6, 'Workflow View shows the column dependency graph', async ({ page }) => {
  const api = await setup(page);
  await gridWithCells(page, api);
  await page.getByRole('button', { name: /workflow/i }).first().click();
  const wf = page.getByTestId('workflow-view');
  await expect(wf).toBeVisible();
  expect(await wf.locator('[role="listitem"], [role="treeitem"], g.node, [data-node], li').count()).toBeGreaterThan(0);
});
t(7, 'conditional formatting with AND/OR rules', async ({ page }) => {
  const api = await setup(page);
  await gridWithCells(page, api);
  await page.getByRole('button', { name: /conditional format|formatting/i }).first().click();
  const dlg = page.getByRole('dialog').or(page.getByTestId('column-manager'));
  await expect(dlg.getByText(/\bAND\b/).first()).toBeVisible();
  await expect(dlg.getByText(/\bOR\b/).first()).toBeVisible();
});
t(8, 'transfer filtered documents to a new Matrix or Chat', async ({ page }) => {
  const api = await setup(page);
  await gridWithCells(page, api);
  await expect(page.getByRole('button', { name: /transfer|new matrix|open in chat|send to/i }).first()).toBeVisible();
});
t(9, 'a Document Source column groups by data-room folder', async ({ page }) => {
  const api = await setup(page);
  await gridWithCells(page, api, S.nile);
  await expect(page.getByTestId('grid')).toContainText(/document source|folder|data room/i);
});
t(10, 'Excel export keeps values, with a logo option', async ({ page }) => {
  const api = await setup(page);
  await gridWithCells(page, api);
  await page.getByTestId('grid-export').click();
  const logo = page.getByRole('checkbox', { name: /logo/i });
  await expect(logo, 'export offers a logo option').toBeVisible();
  const d = await saveDownload(page, async () => {
    const go = page.getByRole('button', { name: /^(export|download)( to excel| xlsx)?$/i }).last();
    if (await go.isVisible().catch(() => false)) await go.click();
    else await page.getByTestId('grid-export').click();
  }, 'grid.xlsx');
  expect(isZip(d.bytes)).toBe(true);
  expect(pyZip(d.file, 'list')).toMatch(/xl\/worksheets\/sheet1\.xml/);
});
t(11, 'Matrix Chat answers with row citations, first tokens within 5 s', async ({ page }) => {
  const api = await setup(page);
  await gridWithCells(page, api);
  await page.getByTestId('grid-chat-input').fill('Which documents mention a change-of-control clause?');
  const t0 = Date.now();
  await page.keyboard.press('Enter');
  const answer = page.getByRole('log').or(page.getByTestId('grid-chat')).first();
  await expect(answer).toContainText(/\S{3,}/, { timeout: 5_000 });
  expect(Date.now() - t0).toBeLessThan(5_000);
  await expect(page.getByTestId('source-chip').first()).toBeVisible({ timeout: 60_000 });
});
t(12, 'a 500-row grid scrolls and sorts at 60 fps', async ({ page }) => {
  const api = await setup(page);
  const deal = (await api.post('/deals', { name: `Perf ${Date.now()}` })).json;
  const id = deal?.id ?? deal?.deal?.id;
  expect(id, 'deal created').toBeTruthy();
  const rows = Array.from({ length: 500 }, (_, i) => ({ name: `Row ${i}`, label: `Row ${i}` }));
  const r = await api.post(`/deals/${id}/grid/rows`, { rows });
  expect(r.status, `POST grid/rows with 500 rows: ${r.body.toString().slice(0, 200)}`).toBeLessThan(300);
  await page.goto(`/deals/${id}`);
  await page.getByTestId('deal-tab-grid').click();
  await expect(page.getByTestId('grid')).toBeVisible();
  const fps = await page.evaluate(async () => {
    const el = (document.querySelector('[data-testid="grid"]') as HTMLElement);
    const scroller = [el, ...el.querySelectorAll<HTMLElement>('*')].find((e) => e.scrollHeight > e.clientHeight + 50 && /auto|scroll/.test(getComputedStyle(e).overflowY)) || el;
    const frames: number[] = [];
    let last = performance.now();
    await new Promise<void>((res) => {
      let i = 0;
      const step = () => {
        const n = performance.now();
        frames.push(n - last);
        last = n;
        scroller.scrollTop += 120;
        if (++i < 90) requestAnimationFrame(step);
        else res();
      };
      requestAnimationFrame(step);
    });
    frames.sort((a, b) => a - b);
    return { p95: frames[Math.floor(frames.length * 0.95)], n: frames.length, rows: el.querySelectorAll('[data-testid="grid-cell"]').length };
  });
  expect(fps.p95, `p95 frame time ${fps.p95} ms must be <= 20 ms (~60 fps)`).toBeLessThanOrEqual(20);
  const t0 = Date.now();
  await page.getByRole('columnheader').first().click();
  await expect(page.getByTestId('grid')).toBeVisible();
  expect(Date.now() - t0, 'sort completes within 500 ms').toBeLessThan(500);
});
t(13, 'a 100-file upload shows per-file status, overall progress and failure alerts', async ({ page }) => {
  await setup(page);
  await newDealUI(page, `Upload100 ${Date.now()}`);
  await page.getByTestId('deal-tab-documents').click();
  const dir = path.join(fixtures(), 'many');
  await page.getByTestId('upload-input').setInputFiles(fs.readdirSync(dir).map((f) => path.join(dir, f)));
  await expect(page.getByTestId('upload-progress').first()).toBeVisible({ timeout: 30_000 });
  await expect.poll(async () => page.getByTestId('doc-row').count(), { timeout: 240_000 }).toBeGreaterThanOrEqual(100);
  expect(await page.getByTestId('doc-row').first().getAttribute('data-status')).toBeTruthy();
  await expect(page.getByRole('alert').or(page.getByTestId('toast')).filter({ hasText: /corrupt|fail|could not|error/i }).first(), 'failure alert for corrupt.pdf').toBeVisible({ timeout: 120_000 });
});
t(14, 'tables auto-extracted from PDFs can be exported', async ({ page }) => {
  await setup(page);
  await newDealUI(page, `Tables ${Date.now()}`);
  await page.getByTestId('deal-tab-documents').click();
  await page.getByTestId('upload-input').setInputFiles([path.join(fixtures(), 'table.pdf')]);
  await expect(page.getByTestId('doc-row').first()).toHaveAttribute('data-status', /index|ready|done/i, { timeout: 120_000 });
  await page.getByTestId('doc-open').first().click();
  await expect(page.getByTestId('pdf-viewer')).toBeVisible();
  await expect(page.getByRole('button', { name: /export.*table|table.*(csv|excel|export)|extract.*table/i }).first()).toBeVisible();
});

// ---------------------------------------------------------------- Citations (15-23)
t(15, 'hovering a citation previews the source within 0.5 s', async ({ page }) => {
  const api = await setup(page);
  await page.goto(`/runs/${await compsRun(api)}`);
  const chip = page.getByTestId('source-chip').first();
  await expect(chip).toBeVisible();
  const t0 = Date.now();
  await chip.hover();
  await expect(page.getByTestId('citation-popover')).toBeVisible({ timeout: 500 });
  expect(Date.now() - t0).toBeLessThan(500 + 150);
  await expect(page).toHaveURL(/\/runs\//);
});
t(16, 'clicking a citation opens the source at the highlighted span within 2 s', async ({ page }) => {
  const api = await setup(page);
  await page.goto(`/runs/${await compsRun(api)}`);
  const t0 = Date.now();
  await page.getByTestId('source-chip').first().click();
  const hl = page.getByTestId('bbox-highlight').first();
  await expect(hl).toBeInViewport({ timeout: 2_000 });
  expect(Date.now() - t0).toBeLessThan(2_000 + 200);
});
t(17, 'a reviewer can trace a random figure to its source quickly', async ({ page }) => {
  const api = await setup(page);
  const a = await artifacts(api);
  await page.goto(`/deals/${a.deal}/models/${enc(a.model)}`);
  const cells = page.locator('[data-testid="model-cell"][data-class="link"], [data-testid="model-cell"][data-class="input"]');
  const n = await cells.count();
  expect(n).toBeGreaterThan(0);
  const t0 = Date.now();
  await cells.nth(Math.floor(Math.random() * n)).click();
  await expect(page.getByTestId('inspector-quote')).not.toBeEmpty();
  await expect(page.getByTestId('inspector-page')).toContainText(/\d/);
  expect(Date.now() - t0).toBeLessThan(120_000);
});
t(18, 'the source panel has a download-all-sources control', async ({ page }) => {
  const api = await setup(page);
  await page.goto(`/runs/${await compsRun(api)}`);
  await expect(page.getByTestId('download-sources')).toBeVisible();
});
t(19, 'exported slides carry inline markers with sources in the footer', async ({ page }) => {
  const api = await setup(page);
  const a = await artifacts(api);
  await page.goto(`/deals/${a.deal}/decks/${enc(a.deck)}`);
  const d = await saveDownload(page, () => page.getByTestId('deck-download').click(), 'deck.pptx');
  const files = pyZip(d.file, 'list').split('\n').filter((f) => /^ppt\/slides\/slide\d+\.xml$/.test(f));
  expect(files.length).toBeGreaterThan(2);
  const withSource = files.filter((f) => /Source/i.test(pyZip(d.file, 'read', f))).length;
  expect(withSource / files.length, 'slides with a source footer').toBeGreaterThanOrEqual(0.8);
});
t(20, 'a hard-coded Excel cell shows its source', async ({ page }) => {
  const api = await setup(page);
  const a = await artifacts(api);
  await page.goto(`/deals/${a.deal}/models/${enc(a.model)}`);
  await page.locator('[data-testid="model-cell"][data-class="input"]').first().click();
  await expect(page.getByTestId('inspector-source-link').first().or(page.getByTestId('inspector-quote'))).toBeVisible();
  const d = await saveDownload(page, () => page.getByTestId('model-download').click(), 'm.xlsx');
  expect(pyZip(d.file, 'list'), 'cell notes (comments) are written into the workbook').toMatch(/xl\/comments|threadedComments|xl\/drawings\/vmlDrawing/);
});
t(21, 'data-provider citations render as cards with links', async ({ page }) => {
  const api = await setup(page);
  await page.goto(`/runs/${await compsRun(api)}`);
  await page.getByTestId('source-chip').first().hover();
  await expect(page.getByTestId('citation-popover').getByRole('link').first()).toBeVisible();
});
t(22, 'low-credibility web sources are excluded', async ({ page }) => {
  const api = await setup(page);
  await page.goto('/');
  await page.getByTestId('source-toggle-web').click();
  await page.getByTestId('ask-input').fill('What is the latest news on Apple supply chain?');
  await page.getByTestId('ask-submit').click();
  await expect(page.getByTestId('run-view')).toBeVisible();
  await driveRunUI(page, 240_000);
  await expect(page.getByTestId('run-view')).toContainText(/low[- ]credib|excluded|filtered|credibility/i);
  void api;
});
t(23, 'PDF exports keep citations and the logo', async ({ page }) => {
  const api = await setup(page);
  const a = await artifacts(api);
  await page.goto(`/deals/${a.deal}/decks/${enc(a.deck)}`);
  await page.getByTestId('deck-download').click();
  const pdf = page.getByRole('menuitem', { name: /pdf/i }).or(page.getByRole('button', { name: /pdf/i })).first();
  await expect(pdf, 'a PDF export option exists').toBeVisible();
  const d = await saveDownload(page, () => pdf.click(), 'deck.pdf');
  expect(d.bytes.subarray(0, 4).toString()).toBe('%PDF');
});

// ---------------------------------------------------------------- Agents (24-33)
t(24, 'a pre-run source-review step that can be turned off', async ({ page }) => {
  await setup(page);
  await page.goto('/');
  await expect(page.getByRole('checkbox', { name: /review.*sources?|sources?.*review/i }).or(page.getByRole('switch', { name: /review.*sources?|sources?.*review/i })).first()).toBeVisible();
});
t(25, 'scheduled runs (daily, weekly, custom, one future date)', async ({ page }) => {
  await setup(page);
  await page.goto('/agents');
  await page.getByTestId('new-agent').click();
  const sched = page.getByLabel(/schedule|repeat|frequency/i).first();
  await expect(sched).toBeVisible();
  const txt = (await page.getByRole('dialog').or(page.locator('main')).first().textContent()) || '';
  for (const re of [/daily/i, /weekly/i, /custom/i, /(once|single|one[- ]time|specific date)/i]) expect(txt).toMatch(re);
});
t(26, 'an email request returns citations and files', async ({ page }) => {
  const api = await setup(page);
  const jobs = items((await api.get('/jobs?limit=200')).json).filter((j) => j.source === 'email' && j.status === 'done');
  expect(jobs.length, 'a finished email-sourced job exists (run P-J1 first)').toBeGreaterThan(0);
  await page.goto(`/runs/${jobs[0].id}`);
  await expect(page.getByTestId('deliverable-link').first()).toBeVisible();
  await expect(page.getByTestId('source-chip').first()).toBeVisible();
});
t(27, 'an email deck request lands in the Library', async ({ page }) => {
  const api = await setup(page);
  const jobs = items((await api.get('/jobs?limit=200')).json).filter((j) => j.source === 'email' && /deck|slide|pitch/i.test(JSON.stringify(j)));
  expect(jobs.length, 'an email-sourced deck job exists').toBeGreaterThan(0);
  await page.getByTestId('nav-library').click();
  await expect(page.getByTestId('deliverable-row').filter({ hasText: /\.pptx/i }).first()).toBeVisible();
});
t(28, 'recurring monitoring by email', async ({ page }) => {
  await setup(page);
  await page.goto('/agents');
  await expect(page.getByRole('button', { name: /monitor|watch|alert me|recurring/i }).or(page.getByTestId('agent-card').filter({ hasText: /monitor/i })).first()).toBeVisible();
});
t(29, 'a buyer email saves attached material to the project folder', async ({ page }) => {
  const api = await setup(page);
  const md = process.env.E2E_MAILDIR as string;
  await api.put('/firm/mailbox', { kind: 'maildir', path: md, folder: 'new', poll_seconds: 60, send_enabled: false, allowed_senders: [USERS.owner], allowed_senders_json: [USERS.owner] });
  fs.copyFileSync(path.join(fixtures(), 'buyer-material.eml'), path.join(md, 'new', `${Date.now()}-buyer.eml`));
  require('child_process').execFileSync('python3', ['-m', 'om.api', 'poll-mail', '--data', process.env.E2E_DATA_DIR as string], {
    cwd: path.resolve(__dirname, '..', '..'), env: { ...process.env, ACRETIA_LLM_MODE: 'replay' }, stdio: 'pipe',
  });
  await expect.poll(async () => {
    const deals = items((await api.get('/deals?limit=200')).json);
    for (const d of deals) if (/buyer-table/i.test(JSON.stringify((await api.get(`/deals/${d.id}/documents`)).json))) return true;
    return false;
  }, { timeout: 60_000 }).toBe(true);
});
t(30, '"/" opens multi-skill selection', async ({ page }) => {
  await setup(page);
  await page.goto('/');
  await page.getByTestId('ask-input').fill('/');
  await expect(page.getByTestId('skill-picker')).toBeVisible();
  const opts = page.getByTestId('skill-picker').getByRole('option');
  expect(await opts.count()).toBeGreaterThan(1);
  await opts.nth(0).click();
  await page.getByTestId('ask-input').type('/');
  await page.getByTestId('skill-picker').getByRole('option').nth(0).click();
  expect(await page.getByTestId('skill-chip').count()).toBeGreaterThanOrEqual(2);
});
t(31, 'a tick-and-tie agent cross-checks page by page', async ({ page }) => {
  await setup(page);
  await page.goto('/agents');
  await expect(page.getByTestId('agent-card').filter({ hasText: /tick[- ]?(and|&)[- ]?tie|tie[- ]out/i }).first()).toBeVisible();
});
t(32, 'agent search by description respects admin-disabled agents', async ({ page, browser }) => {
  const api = await setup(page);
  await page.goto('/agents');
  const card = page.locator('[data-testid="agent-card"][data-agent="buyer_list"]').first();
  const tog = card.getByTestId('agent-enabled-toggle');
  await expect(tog).toBeVisible();
  const was = await tog.isChecked().catch(() => true);
  if (was) await tog.click();
  const ctx = await browser.newContext({ baseURL: process.env.ACRETIA_BASE_URL });
  const mp = await ctx.newPage();
  await signIn(mp, 'member', '/agents');
  await mp.getByTestId('agents-search').fill('buyer');
  await expect(mp.locator('[data-testid="agent-card"][data-agent="buyer_list"]')).toHaveCount(0);
  await ctx.close();
  if (was) await tog.click(); // restore
  void api;
});
t(33, 'long runs show step progress and a cancel control', async ({ page }) => {
  await setup(page);
  await askViaHome(page, 'Build an LBO model for ElSewedy Electric');
  await expect(page.getByTestId('run-cancel')).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId('run-step').first()).toBeVisible();
  await page.getByTestId('run-cancel').click();
  await expect(page.getByTestId('run-status')).toContainText(/cancel|done/i, { timeout: 30_000 });
});

// ---------------------------------------------------------------- Decks (34-41)
t(34, 'a branded 10-slide deck in under 3 minutes', async ({ page }) => {
  const api = await setup(page);
  const t0 = Date.now();
  const r = await runTask(api, 'pitchbook_section', S.deal, 'Create a branded 10-slide pitch deck for Apple');
  expect(r.job.status).toBe('done');
  expect(Date.now() - t0, 'wall time under 180 s').toBeLessThan(180_000);
  const deck = (await deliverables(api, S.deal!)).map((x) => x.name).filter((n) => /\.pptx$/i.test(n)).pop() as string;
  await page.goto(`/deals/${S.deal}/decks/${enc(deck)}`);
  expect(await page.getByTestId('slide-thumb').count()).toBeGreaterThanOrEqual(10);
});

async function slideHashes(api: Api, deal: string, name: string, n: number): Promise<string[]> {
  const out: string[] = [];
  for (let i = 1; i <= n; i++) out.push(sha((await api.get(`/decks/${deal}/${enc(name)}/slides/${i}.png`)).body));
  return out;
}
async function commentAndWait(api: Api, deal: string, name: string, slides: number[], body: string) {
  const v0 = (await versionsOf(api, deal, name)).length;
  for (const s of slides) {
    const r = await api.post(`/decks/${deal}/${enc(name)}/comments`, { slide: s, body });
    expect(r.status, `comment on slide ${s}: ${r.body.toString().slice(0, 150)}`).toBeLessThan(300);
  }
  await expect.poll(async () => (await versionsOf(api, deal, name)).length, { timeout: 300_000, intervals: [2000] }).toBeGreaterThan(v0);
  return v0;
}
t(35, 'editing one slide changes only that slide', async ({ page }) => {
  const api = await setup(page);
  const a = await artifacts(api);
  const n = 4;
  const before = await slideHashes(api, a.deal, a.deck, n);
  await commentAndWait(api, a.deal, a.deck, [2], 'make slide 2 a waterfall');
  const after = await slideHashes(api, a.deal, a.deck, n);
  expect(after[1], 'slide 2 changed').not.toBe(before[1]);
  for (const i of [0, 2, 3]) expect(after[i], `slide ${i + 1} unchanged`).toBe(before[i]);
});
t(36, 'comment anchors on several slides apply in one bulk revision, in place', async ({ page }) => {
  const api = await setup(page);
  const a = await artifacts(api);
  await page.goto(`/deals/${a.deal}/decks/${enc(a.deck)}`);
  for (const s of [2, 3]) {
    await page.getByTestId('slide-thumb').nth(s - 1).click();
    await page.getByTestId('comment-input').fill(`tighten the title on slide ${s}`);
    await page.getByTestId('comment-submit').click();
  }
  const v0 = (await versionsOf(api, a.deal, a.deck)).length;
  await page.getByTestId('apply-comments').click();
  await expect.poll(async () => (await versionsOf(api, a.deal, a.deck)).length, { timeout: 300_000, intervals: [2000] }).toBe(v0 + 1);
});
t(37, 'each annotation round is a version', async ({ page }) => {
  const api = await setup(page);
  const a = await artifacts(api);
  const v0 = await commentAndWait(api, a.deal, a.deck, [3], 'use sentence case in the headline');
  const v1 = (await versionsOf(api, a.deal, a.deck)).length;
  expect(v1).toBe(v0 + 1);
  await commentAndWait(api, a.deal, a.deck, [3], 'add a footnote on units');
  expect((await versionsOf(api, a.deal, a.deck)).length).toBe(v1 + 1);
});
t(38, 'accepted slides stay byte-identical when another slide is revised', async ({ page }) => {
  const api = await setup(page);
  const a = await artifacts(api);
  const get = async (v: number) => {
    const f = path.join(__dirname, '..', 'test-results', `p38-${v}.pptx`);
    fs.mkdirSync(path.dirname(f), { recursive: true });
    fs.writeFileSync(f, (await api.get(`/deals/${a.deal}/deliverables/${enc(a.deck)}/versions/${v}/download`)).body);
    return f;
  };
  const vs0 = await versionsOf(api, a.deal, a.deck);
  await commentAndWait(api, a.deal, a.deck, [2], 'replace the chart with a table');
  const vs1 = await versionsOf(api, a.deal, a.deck);
  const [f0, f1] = [await get(vs0[vs0.length - 1]), await get(vs1[vs1.length - 1])];
  for (const s of [1, 3, 4]) {
    const e = `ppt/slides/slide${s}.xml`;
    expect(sha(pyZip(f1, 'read', e)), `slide ${s} XML byte-identical`).toBe(sha(pyZip(f0, 'read', e)));
  }
});
t(39, 'version compare and rollback', async ({ page }) => {
  const api = await setup(page);
  const a = await artifacts(api);
  await page.goto(`/deals/${a.deal}/decks/${enc(a.deck)}`);
  await page.getByTestId('version-compare').click();
  await expect(page.getByTestId('diff-view')).toBeVisible();
  await page.getByTestId('nav-library').click();
  await page.getByTestId('deliverable-row').filter({ hasText: a.deck }).first().click();
  await expect(page.getByTestId('restore-button').first()).toBeVisible();
});
t(40, 'template slides refresh when Matrix data updates', async ({ page }) => {
  const api = await setup(page);
  const a = await artifacts(api);
  await page.goto(`/deals/${a.deal}/decks/${enc(a.deck)}`);
  await expect(page.getByRole('button', { name: /refresh|sync|update from (matrix|model|grid)/i }).first()).toBeVisible();
});
t(41, 'tables are native and editable in the exported deck', async ({ page }) => {
  const api = await setup(page);
  const a = await artifacts(api);
  await page.goto(`/deals/${a.deal}/decks/${enc(a.deck)}`);
  const d = await saveDownload(page, () => page.getByTestId('deck-download').click(), 'deck.pptx');
  const xml = pyZip(d.file, 'list').split('\n').filter((f) => /^ppt\/slides\/slide\d+\.xml$/.test(f)).map((f) => pyZip(d.file, 'read', f)).join('');
  expect(xml).toContain('<a:tbl>');
});

// ---------------------------------------------------------------- Excel (44), Chat (47-50)
t(44, 'a tab audit lists links and errors', async ({ page }) => {
  const api = await setup(page);
  const a = await artifacts(api);
  await page.goto(`/deals/${a.deal}/models/${enc(a.model)}`);
  await page.getByTestId('audit-overlay-toggle').click();
  const m = page.getByTestId('model-view');
  await expect(m).toContainText(/links?/i);
  await expect(m).toContainText(/errors?/i);
});
t(47, 'editing an earlier message regenerates from that point', async ({ page }) => {
  const api = await setup(page);
  await gridWithCells(page, api);
  const inp = page.getByTestId('grid-chat-input');
  await inp.fill('List the documents');
  await page.keyboard.press('Enter');
  await inp.fill('Which are legal agreements?');
  await page.keyboard.press('Enter');
  await page.getByText('List the documents').first().hover();
  await page.getByRole('button', { name: /edit/i }).first().click();
  await expect(page.getByRole('textbox', { name: /edit|message/i }).first()).toBeVisible();
});
t(48, 'tables in answers are collapsible', async ({ page }) => {
  const api = await setup(page);
  await gridWithCells(page, api);
  await page.getByTestId('grid-chat-input').fill('Show a table of documents by folder');
  await page.keyboard.press('Enter');
  await expect(page.getByRole('button', { name: /collapse|expand|hide table/i }).first()).toBeVisible({ timeout: 60_000 });
});
t(49, 'inline charts: candlestick, dual-axis, debt-maturity tower', async ({ page }) => {
  const api = await setup(page);
  await page.goto(`/runs/${await compsRun(api)}`);
  await expect(page.getByRole('img', { name: /chart|football|maturity|candlestick/i }).first()).toBeVisible();
});
t(50, 'a CSV upload joins other sources', async ({ page }) => {
  await setup(page);
  await page.goto('/');
  const f = page.locator('input[type="file"]').first();
  await expect(f).toBeAttached();
  await f.setInputFiles(path.join(fixtures(), 'peers.csv'));
  await expect(page.getByText(/peers\.csv/).first()).toBeVisible();
});

// ---------------------------------------------------------------- Library, memory, projects (52-57)
t(52, 'the Library lists every artifact', async ({ page }) => {
  const api = await setup(page);
  await artifacts(api);
  let total = 0;
  for (const d of items((await api.get('/deals?limit=200')).json)) total += (await deliverables(api, d.id)).length;
  await page.getByTestId('nav-library').click();
  await expect(page.getByTestId('library-table')).toBeVisible();
  await expect.poll(async () => page.getByTestId('deliverable-row').count(), { timeout: 20_000 }).toBeGreaterThanOrEqual(total);
});
t(53, 'memory entries show their source and can be edited or deleted', async ({ page }) => {
  await setup(page);
  await page.getByTestId('nav-settings').click();
  await page.getByRole('link', { name: /memory/i }).first().click();
  const row = page.getByTestId('memory-entry').or(page.getByRole('listitem')).first();
  await expect(row).toBeVisible();
  await expect(row.getByRole('button', { name: /edit/i })).toBeVisible();
  await expect(row.getByRole('button', { name: /delete|remove/i })).toBeVisible();
  await expect(row).toContainText(/source/i);
});
t(54, 'chats published to a project are forkable snapshots', async ({ page }) => {
  const api = await setup(page);
  await page.goto(`/runs/${await compsRun(api)}`);
  await page.getByRole('button', { name: /publish/i }).first().click();
  await expect(page.getByRole('button', { name: /fork/i }).first()).toBeVisible();
});
t(55, 'a published Matrix inherits project permissions (viewer cannot edit)', async ({ page, browser }) => {
  const api = await setup(page);
  const ctx = await browser.newContext({ baseURL: process.env.ACRETIA_BASE_URL });
  const vp = await ctx.newPage();
  await signIn(vp, 'viewer', `/deals/${S.deal}`);
  await vp.getByTestId('deal-tab-grid').click();
  await expect(vp.getByTestId('grid')).toBeVisible();
  const add = vp.getByTestId('grid-add-column');
  if (await add.count()) await expect(add).toBeDisabled();
  else await expect(add).toHaveCount(0);
  await ctx.close();
  void api;
});
t(56, 'teammates added to a project see everything shared in it', async ({ page, browser }) => {
  const api = await setup(page);
  const name = `Shared ${Date.now()}`;
  const r = await api.post('/deals', { name });
  expect(r.status).toBeLessThan(300);
  const ctx = await browser.newContext({ baseURL: process.env.ACRETIA_BASE_URL });
  const mp = await ctx.newPage();
  await signIn(mp, 'member', '/');
  await mp.getByTestId('nav-deals').click();
  await expect(mp.getByTestId('deal-row').filter({ hasText: name })).toBeVisible();
  await ctx.close();
});
t(57, 'the Activity tab lists what happened in the deal', async ({ page }) => {
  const api = await setup(page);
  await artifacts(api);
  await page.goto(`/deals/${S.deal}`);
  await page.getByTestId('deal-tab-activity').click();
  await expect(page.getByRole('listitem').or(page.getByRole('row')).nth(1)).toBeVisible();
});

// ---------------------------------------------------------------- Admin (58, 60, 61, 63)
t(58, 'admins can toggle agents; members cannot', async ({ page, browser }) => {
  await setup(page);
  await page.goto('/agents');
  await expect(page.getByTestId('agent-enabled-toggle').first()).toBeVisible();
  const ctx = await browser.newContext({ baseURL: process.env.ACRETIA_BASE_URL });
  const mp = await ctx.newPage();
  await signIn(mp, 'member', '/agents');
  await expect(mp.getByTestId('agent-card').first()).toBeVisible();
  await expect(mp.getByTestId('agent-enabled-toggle')).toHaveCount(0);
  await ctx.close();
});
t(60, 'a sources dashboard lists connectors with status', async ({ page }) => {
  await setup(page);
  await page.goto('/settings/connectors');
  await expect(page.locator('main')).toContainText(/status/i);
  await expect(page.locator('main')).toContainText(/last sync|synced/i);
});
t(61, 'spend limits by team or deal', async ({ page }) => {
  await setup(page);
  await page.goto('/settings/firm');
  await expect(page.getByText(/spend limit|budget/i).first()).toBeVisible();
});
t(63, 'custom MCP tools can be connected', async ({ page }) => {
  await setup(page);
  await page.goto('/settings/connectors');
  await page.getByTestId('connector-add').click();
  await expect(page.getByRole('dialog').getByText(/mcp/i).first()).toBeVisible();
});

// ---------------------------------------------------------------- Performance and polish (64-67, 69, 70)
t(64, 'the shell is interactive within 3 s', async ({ page, browser }) => {
  await setup(page);
  const ctx = page.context();
  const p2 = await ctx.newPage();
  await p2.goto('/', { waitUntil: 'commit' });
  await expect(p2.getByTestId('app-shell')).toBeVisible({ timeout: 3_000 });
  const ms = await p2.evaluate(() => performance.now());
  expect(ms, `app-shell visible ${Math.round(ms)} ms after navigation start`).toBeLessThan(3_000);
  await p2.close();
  void browser;
});
t(65, 'dark mode is complete', async ({ page }) => {
  const api = await setup(page);
  const deal = S.deal;
  const urls = ['/', '/deals', '/agents', '/notifications', '/settings/firm', `/deals/${deal}`];
  expect(await setTheme(page, 'dark')).toBe(true);
  const bad: string[] = [];
  for (const u of urls) {
    await page.goto(u);
    await expect(page.getByTestId('app-shell')).toBeVisible();
    await setTheme(page, 'dark');
    await page.waitForTimeout(200);
    const light = await page.evaluate(() => {
      const L = (c: string) => {
        const m = c.match(/rgba?\(([^)]+)\)/);
        if (!m) return 0;
        const p = m[1].split(/[,\s/]+/).map(parseFloat);
        if (p.length > 3 && p[3] === 0) return -1;
        return (0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2]) / 255;
      };
      const out: string[] = [];
      for (const id of ['app-shell', 'sidebar']) {
        const e = document.querySelector(`[data-testid="${id}"]`);
        if (e && L(getComputedStyle(e).backgroundColor) > 0.6) out.push(id);
      }
      for (const e of document.querySelectorAll('main, table, [role=table], [data-testid$="-table"], [role=dialog]')) {
        if (L(getComputedStyle(e).backgroundColor) > 0.6) out.push(e.tagName.toLowerCase() + (e.getAttribute('data-testid') ? `[${e.getAttribute('data-testid')}]` : ''));
      }
      return out;
    });
    if (light.length) bad.push(`${u}: still light ${light.slice(0, 4).join(',')}`);
    await shoot(page, J, 65, `dark-${u.replace(/\W+/g, '_') || 'home'}`);
  }
  expect(bad, bad.join('; ')).toEqual([]);
  void api;
});
t(66, 'a notifications centre', async ({ page }) => {
  const api = await setup(page);
  await artifacts(api);
  await page.keyboard.press('g');
  await page.keyboard.press('n');
  await expect(page).toHaveURL(/\/notifications/);
  await expect(page.getByTestId('notif-item').first()).toBeVisible();
  await expect(page.getByRole('button', { name: /mark all|read all/i })).toBeVisible();
});
t(67, 'a mobile query and source view', async ({ page }) => {
  await setup(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.getByTestId('ask-input')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), 'no horizontal scroll on mobile').toBe(true);
  await page.getByTestId('ask-input').fill('Spread trading comps for Apple vs peers');
  await page.getByTestId('ask-submit').click();
  await expect(page.getByTestId('run-view')).toBeVisible();
  await driveRunUI(page, 300_000);
  await page.getByTestId('source-chip').first().click();
  await expect(page.getByTestId('inspector-panel').or(page.getByTestId('pdf-viewer')).first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await snap(page, J, 67, 'mobile-source');
});
t(69, 'in-app feedback on any answer', async ({ page }) => {
  const api = await setup(page);
  await page.goto(`/runs/${await compsRun(api)}`);
  await page.getByTestId('feedback-up').click();
  await expect(page.getByTestId('feedback-up')).toHaveAttribute('aria-pressed', 'true');
  await page.getByTestId('feedback-down').click();
  await expect(page.getByTestId('toast').or(page.getByRole('status')).first()).toBeVisible();
});
t(70, 'a starter state, never a blank page', async ({ page }) => {
  await setup(page);
  await page.goto('/');
  expect(await page.getByTestId('starter-task').count()).toBeGreaterThanOrEqual(4);
  await newDealUI(page, `Empty ${Date.now()}`);
  for (const tab of ['documents', 'grid', 'models', 'decks', 'library', 'activity']) {
    await page.getByTestId(`deal-tab-${tab}`).click();
    const action = page.locator('main').getByRole('button').or(page.locator('main').getByRole('link')).or(page.locator('main [data-testid="upload-dropzone"]'));
    expect(await action.count(), `empty ${tab} tab offers a next action`).toBeGreaterThan(0);
    expect(((await page.locator('main').innerText()) || '').trim().length, `empty ${tab} tab is not blank`).toBeGreaterThan(10);
  }
});
