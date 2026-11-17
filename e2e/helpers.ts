import { test as base, expect, Page, APIRequestContext, Locator } from '@playwright/test';
import { execFileSync } from 'child_process';
import * as crypto from 'crypto';
import * as fs from 'fs';
import * as path from 'path';

export { expect };
export type { Page } from '@playwright/test';

export const DEMO_PW = process.env.ACRETIA_DEMO_PASSWORD || 'demo-password-123';
export const USERS = {
  owner: 'owner@meridian.example',
  member: 'member@meridian.example',
  viewer: 'viewer@meridian.example',
} as const;
export type Role = keyof typeof USERS;
export const API = '/api/v1';
export const TERMINAL = new Set(['done', 'failed', 'cancelled']);

// the real server's base URL is only known after globalSetup, so the fixture reads it from the environment
export const test = base.extend<{}>({
  baseURL: async ({}: any, use: (v: string) => Promise<void>) => {
    await use(process.env.ACRETIA_BASE_URL as string);
  },
} as any) as typeof base;

export const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
export const fixtures = () => process.env.E2E_FIXTURES as string;
export const base_url = () => process.env.ACRETIA_BASE_URL as string;

// ------------------------------------------------------------------------------------------------ API
export interface Res {
  status: number;
  json: any;
  body: Buffer;
  headers: Record<string, string>;
}

export class Api {
  constructor(public req: APIRequestContext, public base: string, public csrf: string) {}

  private async call(method: string, p: string, data?: any, extra?: Record<string, string>): Promise<Res> {
    const headers: Record<string, string> = { Origin: this.base, 'X-CSRF-Token': this.csrf, ...(extra || {}) };
    const opts: any = { headers, failOnStatusCode: false, maxRedirects: 0 };
    if (data !== undefined) opts.data = data;
    const r = await (this.req as any)[method.toLowerCase()](this.base + (p.startsWith('/api') ? p : API + p), opts);
    const body: Buffer = await r.body();
    let json: any = null;
    try {
      json = JSON.parse(body.toString('utf8'));
    } catch {
      /* not json */
    }
    return { status: r.status(), json, body, headers: r.headers() };
  }
  get = (p: string) => this.call('GET', p);
  post = (p: string, d: any = {}) => this.call('POST', p, d);
  put = (p: string, d: any = {}) => this.call('PUT', p, d);
  patch = (p: string, d: any = {}) => this.call('PATCH', p, d);
  del = (p: string) => this.call('DELETE', p);

  async cookieHeader(): Promise<string> {
    const cs = await (this.req as any).storageState().then((s: any) => s.cookies as { name: string; value: string }[]);
    return cs.map((c: { name: string; value: string }) => `${c.name}=${c.value}`).join('; ');
  }
}

export const items = (j: any): any[] => (Array.isArray(j) ? j : j?.items ?? j?.data ?? []);
export const jobOf = (j: any) => j?.job ?? j;

/** Log in through the API (shares cookies with the page), returns an Api helper. */
export async function signIn(page: Page, role: Role = 'owner', go = '/'): Promise<Api> {
  const base = base_url();
  const req = page.context().request;
  const r = await req.post(base + API + '/auth/login', {
    data: { email: USERS[role], password: DEMO_PW },
    headers: { Origin: base },
    failOnStatusCode: false,
  });
  expect(r.status(), `login as ${role} (${USERS[role]}) must succeed`).toBe(200);
  const j = await r.json();
  let csrf = j.csrf_token;
  if (!csrf) csrf = (await (await req.get(base + API + '/auth/me')).json()).csrf_token;
  if (go) await page.goto(go);
  return new Api(req, base, csrf);
}

/** Log in through the real login form. */
export async function loginUI(page: Page, role: Role = 'owner') {
  await page.goto('/login');
  await page.getByTestId('login-email').fill(USERS[role]);
  await page.getByTestId('login-password').fill(DEMO_PW);
  await page.getByTestId('login-submit').click();
  await expect(page.getByTestId('app-shell')).toBeVisible({ timeout: 20_000 });
}

export async function sseRead(api: Api, p: string, until: (ev: any) => boolean, ms = 60_000): Promise<any[]> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), ms);
  const out: any[] = [];
  try {
    const r = await fetch(api.base + API + p, { headers: { Cookie: await api.cookieHeader(), Accept: 'text/event-stream' }, signal: ctl.signal });
    if (!r.ok || !r.body) throw new Error(`SSE ${p} -> ${r.status}`);
    const rd = (r.body as any).getReader();
    const dec = new TextDecoder();
    let buf = '';
    for (;;) {
      const { value, done } = await rd.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i: number;
      while ((i = buf.indexOf('\n\n')) >= 0) {
        const block = buf.slice(0, i);
        buf = buf.slice(i + 2);
        const ev: any = {};
        for (const line of block.split('\n')) {
          if (line.startsWith(':')) continue;
          const k = line.slice(0, line.indexOf(':'));
          const v = line.slice(line.indexOf(':') + 1).replace(/^ /, '');
          ev[k] = k === 'data' && ev[k] ? ev[k] + '\n' + v : v;
        }
        try {
          ev.json = JSON.parse(ev.data);
        } catch {
          ev.json = null;
        }
        ev.type = ev.event || ev.json?.type;
        ev.d = ev.json && ev.json.data && ev.json.type ? ev.json.data : ev.json || {};
        out.push(ev);
        if (until(ev)) {
          ctl.abort();
          return out;
        }
      }
    }
  } catch (e) {
    if (!ctl.signal.aborted) throw e;
  } finally {
    clearTimeout(timer);
  }
  return out;
}

export async function approveJob(api: Api, jobId: string, edit?: (payload: any) => any) {
  const evs = await sseRead(api, `/jobs/${jobId}/events`, (e) => e.type === 'approval' || (e.type === 'status' && TERMINAL.has(e.d.status)), 30_000);
  const ap = [...evs].reverse().find((e) => e.type === 'approval');
  if (!ap) return false;
  const payload = edit ? edit(ap.d.payload) : ap.d.payload;
  const r = await api.post(`/jobs/${jobId}/approve`, { step: ap.d.step_id, payload });
  expect(r.status, `approve ${jobId}: ${r.body.toString().slice(0, 200)}`).toBeLessThan(300);
  return true;
}

export async function waitJob(api: Api, id: string, o: { timeout?: number; approve?: boolean } = {}) {
  const end = Date.now() + (o.timeout ?? 300_000);
  let last: any = {};
  while (Date.now() < end) {
    const r = await api.get(`/jobs/${id}`);
    expect(r.status, `GET job ${id}`).toBe(200);
    last = jobOf(r.json);
    if (TERMINAL.has(last.status)) return last;
    if (last.status === 'awaiting_approval' && o.approve !== false) await approveJob(api, id);
    await sleep(500);
  }
  throw new Error(`job ${id} not terminal after timeout (status ${last.status})`);
}

export async function findDeal(api: Api, needle: RegExp): Promise<string> {
  const r = await api.get('/deals?limit=200');
  expect(r.status).toBe(200);
  const d = items(r.json).find((x) => needle.test(JSON.stringify(x)));
  expect(d, `deal matching ${needle}`).toBeTruthy();
  return d.id ?? d.deal_id;
}

export async function agentFor(api: Api, task: string): Promise<string | undefined> {
  const r = await api.get('/agents');
  const a = items(r.json).find((x) => x.task_id === task || x.id === task);
  return a?.id;
}

export async function startJob(api: Api, prompt: string, dealId?: string, task?: string): Promise<string> {
  const body: any = { prompt };
  if (dealId) body.deal_id = dealId;
  if (task) {
    const a = await agentFor(api, task);
    if (a) body.agent_id = a;
  }
  const r = await api.post('/jobs', body);
  expect(r.status, `POST /jobs ${r.body.toString().slice(0, 200)}`).toBeLessThan(300);
  const id = jobOf(r.json)?.id;
  expect(id).toBeTruthy();
  return id;
}

/** Run a task through the API end to end (approving gates) and return the finished job. */
export async function runTask(api: Api, task: string, dealId?: string, prompt?: string) {
  const id = await startJob(api, prompt ?? TASKS.find((t) => t.id === task)!.prompt, dealId, task);
  const j = await waitJob(api, id);
  return { id, job: j };
}

export async function deliverables(api: Api, dealId: string): Promise<any[]> {
  const r = await api.get(`/deals/${dealId}/deliverables`);
  expect(r.status).toBe(200);
  return items(r.json);
}

export const enc = (s: string) => encodeURIComponent(s);

export async function versionsOf(api: Api, dealId: string, name: string): Promise<number[]> {
  const r = await api.get(`/deals/${dealId}/deliverables/${enc(name)}/versions`);
  expect(r.status).toBe(200);
  return items(r.json)
    .map((x) => Number(x.version ?? x.v ?? x.number))
    .filter((n) => !Number.isNaN(n))
    .sort((a, b) => a - b);
}

export const sha = (b: Buffer | string) => crypto.createHash('sha256').update(b).digest('hex');

// ------------------------------------------------------------------------------------------------ catalogue
export const TASKS: { id: string; prompt: string; deal: 'apple' | 'nile' }[] = [
  { id: 'comps', prompt: 'Spread trading comps for Apple vs peers and add a football field', deal: 'apple' },
  { id: 'precedents', prompt: 'Spread precedent transactions for ElSewedy Electric', deal: 'nile' },
  { id: 'three_statement', prompt: 'Build a 3-statement model for Apple', deal: 'apple' },
  { id: 'dcf', prompt: 'Build a 3-statement model and DCF for Apple', deal: 'apple' },
  { id: 'lbo', prompt: 'Build an LBO model for ElSewedy Electric', deal: 'nile' },
  { id: 'merger', prompt: 'Build a merger model for Apple acquiring a small software company', deal: 'apple' },
  { id: 'vdr_review', prompt: 'Do a first-pass review of the data room for Project Nile', deal: 'nile' },
  { id: 'profile', prompt: 'Create a company profile one-pager for Apple', deal: 'apple' },
  { id: 'pitchbook_section', prompt: 'Draft a pitch book valuation section for Apple', deal: 'apple' },
  { id: 'teaser', prompt: 'Write a teaser for Project Nile', deal: 'nile' },
  { id: 'ic_memo', prompt: 'Write an IC memo for Project Nile', deal: 'nile' },
  { id: 'earnings_update', prompt: 'Roll the Apple model forward for the latest earnings', deal: 'apple' },
  { id: 'earnings_recap', prompt: 'Write an earnings recap for Apple', deal: 'apple' },
  { id: 'buyer_list', prompt: 'Build a buyer list for Project Nile', deal: 'nile' },
];

// ------------------------------------------------------------------------------------------------ UI helpers
export async function openCmdk(page: Page) {
  await page.keyboard.press('Control+k');
  if (!(await page.getByTestId('cmdk').isVisible().catch(() => false))) await page.keyboard.press('Meta+k');
  await expect(page.getByTestId('cmdk')).toBeVisible();
}

export async function askViaCmdk(page: Page, prompt: string) {
  await openCmdk(page);
  await page.getByTestId('cmdk-input').fill(prompt);
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('run-view')).toBeVisible({ timeout: 30_000 });
}

export async function askViaHome(page: Page, prompt: string) {
  await page.goto('/');
  await page.getByTestId('ask-input').fill(prompt);
  await page.getByTestId('ask-submit').click();
  await expect(page.getByTestId('run-view')).toBeVisible({ timeout: 30_000 });
}

/** Wait for the run view to reach a terminal status, approving any gate through the UI. */
export async function driveRunUI(page: Page, timeout = 300_000): Promise<string> {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    const t = ((await page.getByTestId('run-status').first().textContent().catch(() => '')) || '').toLowerCase();
    for (const s of ['done', 'failed', 'cancelled']) if (t.includes(s)) return s;
    const ap = page.getByTestId('approval-approve').first();
    if (await ap.isVisible().catch(() => false)) await ap.click().catch(() => undefined);
    await page.waitForTimeout(400);
  }
  throw new Error('run did not reach a terminal status in the UI');
}

export const jobIdFromUrl = (page: Page) => (page.url().match(/\/runs\/([^/?#]+)/) || [])[1];

export function luminance(css: string): number {
  const m = css.match(/rgba?\(([^)]+)\)/);
  if (!m) return 1;
  const [r, g, b] = m[1].split(',').slice(0, 3).map((x) => parseFloat(x));
  const f = (v: number) => {
    v /= 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}

export async function pageBgLum(page: Page): Promise<number> {
  const bg = await page.evaluate(() => {
    for (const el of [document.body, document.documentElement]) {
      const c = getComputedStyle(el).backgroundColor;
      if (c && !/rgba\(.*,\s*0\)/.test(c) && c !== 'transparent') return c;
    }
    return 'rgb(255,255,255)';
  });
  return luminance(bg);
}

export async function setTheme(page: Page, mode: 'light' | 'dark'): Promise<boolean> {
  await page.emulateMedia({ colorScheme: mode });
  const ok = async () => {
    const l = await pageBgLum(page);
    return mode === 'dark' ? l < 0.25 : l > 0.5;
  };
  await page.waitForTimeout(150);
  for (let i = 0; i < 3 && !(await ok()); i++) {
    const t = page.getByTestId('theme-toggle');
    if (!(await t.isVisible().catch(() => false))) break;
    await t.click();
    await page.waitForTimeout(250);
  }
  return ok();
}

export async function setLocale(page: Page, lang: 'en' | 'ar'): Promise<boolean> {
  const cur = () => page.evaluate(() => document.documentElement.lang);
  for (let i = 0; i < 3 && !(await cur()).startsWith(lang); i++) {
    const t = page.getByTestId('locale-toggle');
    if (!(await t.isVisible().catch(() => false))) break;
    await t.click();
    await page.waitForTimeout(200);
    if (!(await cur()).startsWith(lang)) {
      const opt = page.getByRole('menuitem', { name: lang === 'ar' ? /العربية|arabic/i : /english/i }).or(
        page.getByRole('option', { name: lang === 'ar' ? /العربية|arabic/i : /english/i }));
      if (await opt.first().isVisible().catch(() => false)) await opt.first().click();
    }
    await page.waitForTimeout(300);
  }
  return (await cur()).startsWith(lang);
}

/** Save full-page screenshots of the current screen in light, dark and Arabic RTL (feeds the persona/UX graders). */
export async function shoot(page: Page, journey: string, n: number, name: string) {
  const dir = path.join(__dirname, 'artifacts', journey);
  fs.mkdirSync(dir, { recursive: true });
  const f = (t: string) => path.join(dir, `${String(n).padStart(2, '0')}-${name}-${t}.png`);
  const warn = (m: string) => test.info().annotations.push({ type: 'screenshot-warning', description: m });
  await page.waitForTimeout(250);
  await page.screenshot({ path: f('light'), fullPage: true });
  try {
    if (await setTheme(page, 'dark')) await page.screenshot({ path: f('dark'), fullPage: true });
    else warn(`${name}: dark theme did not apply`);
  } catch (e) {
    warn(`${name}: dark shot failed ${e}`);
  } finally {
    await setTheme(page, 'light').catch(() => undefined);
  }
  try {
    if (await setLocale(page, 'ar')) {
      await page.waitForTimeout(250);
      await page.screenshot({ path: f('ar'), fullPage: true });
    } else warn(`${name}: Arabic locale did not apply`);
  } catch (e) {
    warn(`${name}: Arabic shot failed ${e}`);
  } finally {
    await setLocale(page, 'en').catch(() => undefined);
  }
}

/** Single light screenshot (used inside loops where three variants would be wasteful). */
export async function snap(page: Page, journey: string, n: number, name: string) {
  const dir = path.join(__dirname, 'artifacts', journey);
  fs.mkdirSync(dir, { recursive: true });
  await page.screenshot({ path: path.join(dir, `${String(n).padStart(2, '0')}-${name}-light.png`), fullPage: true });
}

export async function textOf(l: Locator): Promise<string> {
  return ((await l.first().textContent().catch(() => '')) || '').trim();
}

// ------------------------------------------------------------------------------------------------ files
export function pyZip(file: string, op: 'list' | 'read', entry = ''): string {
  const code =
    op === 'list'
      ? 'import sys,zipfile;print("\\n".join(zipfile.ZipFile(sys.argv[1]).namelist()))'
      : 'import sys,zipfile,sys;sys.stdout.buffer.write(zipfile.ZipFile(sys.argv[1]).read(sys.argv[2]))';
  return execFileSync('python3', ['-c', code, file, entry], { maxBuffer: 64 * 1024 * 1024 }).toString('utf8');
}

export async function saveDownload(page: Page, click: () => Promise<void>, name: string): Promise<{ file: string; bytes: Buffer; suggested: string }> {
  const [dl] = await Promise.all([page.waitForEvent('download', { timeout: 60_000 }), click()]);
  const dir = path.join(__dirname, 'test-results', 'downloads');
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, `${Date.now()}-${name}`);
  await dl.saveAs(file);
  return { file, bytes: fs.readFileSync(file), suggested: dl.suggestedFilename() };
}

export const isZip = (b: Buffer) => b.length > 4 && b[0] === 0x50 && b[1] === 0x4b;

/** Upload files in a deal's Documents tab and wait until none is still processing. */
export async function uploadAndIndex(page: Page, files: string[], opts: { min?: number; timeout?: number } = {}) {
  await page.getByTestId('deal-tab-documents').click();
  await page.getByTestId('upload-input').setInputFiles(files);
  await expect(page.getByTestId('upload-progress').first()).toBeVisible({ timeout: 30_000 });
  const rows = page.getByTestId('doc-row');
  await expect.poll(async () => await rows.count(), { timeout: opts.timeout ?? 240_000 }).toBeGreaterThanOrEqual(opts.min ?? 1);
  await expect
    .poll(
      async () => {
        const st = await rows.evaluateAll((els) => els.map((e) => (e as HTMLElement).dataset.status || ''));
        return st.filter((s) => /queue|pend|process|index|upload|extract|run|wait/i.test(s) && !/indexed/i.test(s)).length;
      },
      { timeout: opts.timeout ?? 240_000, intervals: [1000] },
    )
    .toBe(0);
}

export async function newDealUI(page: Page, name: string) {
  await page.getByTestId('nav-deals').click();
  await page.getByTestId('new-deal').click();
  await page.getByTestId('new-deal-name').fill(name);
  await page.getByTestId('new-deal-submit').click();
  await expect(page.getByTestId('breadcrumbs')).toContainText(name, { timeout: 20_000 });
}

export async function openDeal(page: Page, nameRe: RegExp) {
  await page.getByTestId('nav-deals').click();
  await page.getByTestId('deal-row').filter({ hasText: nameRe }).first().click();
  await expect(page.getByTestId('breadcrumbs')).toBeVisible();
}

export async function dealUrl(api: Api, nameRe: RegExp) {
  const id = await findDeal(api, nameRe);
  return { id, url: `/deals/${id}` };
}

/** Time from `start()` until `ready()` resolves, in ms. */
export async function timed(fn: () => Promise<unknown>): Promise<number> {
  const t = Date.now();
  await fn();
  return Date.now() - t;
}
