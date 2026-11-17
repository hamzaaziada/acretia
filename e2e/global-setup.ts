import { spawn, execFileSync, ChildProcess } from 'child_process';
import * as fs from 'fs';
import * as net from 'net';
import * as os from 'os';
import * as path from 'path';

const ROOT = path.resolve(__dirname, '..');
export const STATE_FILE = path.join(os.tmpdir(), 'acretia-e2e-state.json');

function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const s = net.createServer();
    s.listen(0, '127.0.0.1', () => {
      const p = (s.address() as net.AddressInfo).port;
      s.close(() => resolve(p));
    });
    s.on('error', reject);
  });
}

async function waitHealthy(base: string, ms: number) {
  const end = Date.now() + ms;
  let last = '';
  while (Date.now() < end) {
    try {
      const r = await fetch(base + '/api/v1/healthz');
      if (r.ok) return;
      last = String(r.status);
    } catch (e) {
      last = String(e);
    }
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error(`server at ${base} not healthy: ${last}`);
}

export default async function globalSetup() {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'acretia-e2e-'));
  const fixtures = path.join(tmp, 'fixtures');
  execFileSync('python3', [path.join(__dirname, 'fixtures', 'make_fixtures.py'), fixtures], { cwd: ROOT, stdio: 'inherit' });
  process.env.E2E_FIXTURES = fixtures;
  process.env.E2E_MAILDIR = path.join(tmp, 'maildir');
  for (const s of ['new', 'cur', 'tmp']) fs.mkdirSync(path.join(process.env.E2E_MAILDIR, s), { recursive: true });
  const state: any = { tmp, fixtures, maildir: process.env.E2E_MAILDIR };

  if (process.env.E2E_BASE_URL) {
    process.env.ACRETIA_BASE_URL = process.env.E2E_BASE_URL;
    process.env.E2E_DATA_DIR = process.env.E2E_DATA_DIR || '';
    state.external = true;
  } else {
    const data = path.join(tmp, 'data');
    const port = await freePort();
    const env = {
      ...process.env,
      ACRETIA_LLM_MODE: 'replay',
      PYTHONPATH: ROOT + path.delimiter + (process.env.PYTHONPATH || ''),
      PYTHONUNBUFFERED: '1',
    };
    execFileSync('python3', ['-m', 'om.api', 'seed-demo', '--data', data], { cwd: ROOT, env, stdio: 'inherit' });
    const log = fs.openSync(path.join(tmp, 'server.log'), 'a');
    const child: ChildProcess = spawn('python3', ['-m', 'om.api', 'serve', '--data', data, '--port', String(port), '--demo'], {
      cwd: ROOT,
      env,
      stdio: ['ignore', log, log],
      detached: true,
    });
    state.pid = child.pid;
    state.data = data;
    process.env.ACRETIA_BASE_URL = `http://127.0.0.1:${port}`;
    process.env.E2E_DATA_DIR = data;
    fs.writeFileSync(STATE_FILE, JSON.stringify(state));
    try {
      await waitHealthy(process.env.ACRETIA_BASE_URL, 60_000);
    } catch (e) {
      const tail = fs.readFileSync(path.join(tmp, 'server.log'), 'utf8').slice(-800);
      throw new Error(`${e}\n--- server log ---\n${tail}`);
    }
  }
  fs.writeFileSync(STATE_FILE, JSON.stringify(state));
}
