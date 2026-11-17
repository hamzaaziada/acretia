import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';

export default async function globalTeardown() {
  const f = path.join(os.tmpdir(), 'acretia-e2e-state.json');
  if (!fs.existsSync(f)) return;
  try {
    const s = JSON.parse(fs.readFileSync(f, 'utf8'));
    if (s.pid) {
      try {
        process.kill(-s.pid, 'SIGTERM');
      } catch {
        try {
          process.kill(s.pid, 'SIGTERM');
        } catch {
          /* already gone */
        }
      }
    }
    if (s.tmp && !process.env.E2E_KEEP) fs.rmSync(s.tmp, { recursive: true, force: true });
  } finally {
    fs.rmSync(f, { force: true });
  }
}
