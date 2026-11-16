// Verifies tokens.ts contrast (WCAG AA 4.5:1 for text pairs) and that tokens.css mirrors tokens.ts.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', 'src', 'ds');
const ts = readFileSync(join(root, 'tokens.ts'), 'utf8');
const css = readFileSync(join(root, 'tokens.css'), 'utf8');

function block(name) {
  const m = ts.match(new RegExp(`export const ${name}[^=]*= \\{([\\s\\S]*?)\\n\\};`));
  const out = {};
  for (const line of m[1].split('\n')) {
    const k = line.match(/^\s*(\w+):\s*'(#[0-9A-Fa-f]{6})'/);
    if (k) out[k[1]] = k[2].toUpperCase();
  }
  return out;
}
const light = block('lightTokens');
const dark = block('darkTokens');
const pairs = [...ts.matchAll(/\['(\w+)', '(\w+)'\]/g)].map((m) => [m[1], m[2]]);

function lum(hex) {
  const h = hex.replace('#', '');
  const c = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  const [r, g, b] = c.map((x) => (x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
const ratio = (a, b) => {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
};
const kebab = (s) => s.replace(/[A-Z0-9]/g, (c) => '-' + c.toLowerCase());

let bad = 0;
for (const [name, t] of [['light', light], ['dark', dark]]) {
  for (const [f, b] of pairs) {
    const r = ratio(t[f], t[b]);
    if (r < 4.5) {
      console.error(`FAIL contrast ${name} ${f} on ${b}: ${r.toFixed(2)}`);
      bad++;
    }
  }
}
// css mirror: light values appear in :root, dark values in the dark blocks
const rootBlock = css.split('/* @dark */')[0];
const darkBlock = css.split('/* @dark */').slice(1).join('');
for (const [k, v] of Object.entries(light)) {
  if (!rootBlock.toUpperCase().includes(`--ACR-${kebab(k).slice(0).toUpperCase()}: ${v};`.replace('--ACR--', '--ACR-'))) {
    console.error(`FAIL css light token missing/mismatch: ${k} ${v}`);
    bad++;
  }
}
for (const [k, v] of Object.entries(dark)) {
  if (!darkBlock.toUpperCase().includes(`--ACR-${kebab(k).toUpperCase()}: ${v};`)) {
    console.error(`FAIL css dark token missing/mismatch: ${k} ${v}`);
    bad++;
  }
}
if (bad) process.exit(1);
console.log(`tokens ok: ${pairs.length} text pairs x 2 themes >= 4.5:1, css mirrors ts`);
