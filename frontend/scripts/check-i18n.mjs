// Fails when ar.json is missing keys that en.json has (or vice versa), when a {placeholder} differs,
// or when the source uses a translation key that the catalogues do not define.
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', 'src');
const en = JSON.parse(readFileSync(join(root, 'i18n', 'en.json'), 'utf8'));
const ar = JSON.parse(readFileSync(join(root, 'i18n', 'ar.json'), 'utf8'));

let bad = 0;
const fail = (m) => {
  console.error('FAIL ' + m);
  bad++;
};

for (const k of Object.keys(en)) if (!(k in ar)) fail(`ar.json is missing key: ${k}`);
for (const k of Object.keys(ar)) if (!(k in en)) fail(`en.json is missing key (present in ar): ${k}`);
const ph = (s) => (s.match(/\{\w+\}/g) ?? []).sort().join(',');
for (const k of Object.keys(en)) {
  if (typeof en[k] !== 'string' || en[k].trim() === '') fail(`en.json empty value: ${k}`);
  if (k in ar) {
    if (typeof ar[k] !== 'string' || ar[k].trim() === '') fail(`ar.json empty value: ${k}`);
    else if (ph(en[k]) !== ph(ar[k])) fail(`placeholder mismatch in ${k}: en ${ph(en[k])} vs ar ${ph(ar[k])}`);
    else if (!/[؀-ۿ]/.test(ar[k]) && !/^[^A-Za-z]*$/.test(ar[k]) && !/^(EN|IP|USD|SEC|Acretia|PDF|CSV)/.test(ar[k])) fail(`ar.json value has no Arabic text (untranslated?): ${k}`);
  }
}

function walk(dir, out = []) {
  for (const f of readdirSync(dir)) {
    const p = join(dir, f);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.(tsx?|ts)$/.test(f)) out.push(p);
  }
  return out;
}

const namespaces = new Set(Object.keys(en).map((k) => k.split('.')[0]));
const used = new Set();
for (const file of walk(root)) {
  const src = readFileSync(file, 'utf8');
  // Any string literal shaped like a catalogue key in a known namespace counts as a use (covers ternaries and key tables).
  for (const m of src.matchAll(/'([a-z][A-Za-z]*(?:\.[A-Za-z_0-9]+)+)'/g)) if (namespaces.has(m[1].split('.')[0])) used.add(m[1]);
}
// Keys built from a variable. Each entry lists the full set the code can produce.
const dynamic = {
  'status.': ['queued', 'planning', 'running', 'awaiting_approval', 'done', 'failed', 'cancelled'],
  'step.': ['queued', 'running', 'done', 'failed', 'skipped'],
  'role.': ['owner', 'member', 'viewer'],
  'deal.status.': ['active', 'on_hold', 'closed', 'archived'],
  'deal.tab.': ['overview', 'documents', 'grid', 'models', 'decks', 'library', 'activity'],
  'docs.status.': ['queued', 'indexing', 'ready', 'failed'],
  'docs.upload.': ['queued', 'uploading', 'done', 'failed'],
  'source.via.': ['email', 'schedule', 'api', 'app'],
  'viewer.': ['doc.title', 'model.title', 'deck.title', 'grid.title'],
  'approval.': ['source_review.title', 'source_review.lead', 'ghost_deck.title', 'ghost_deck.lead', 'assumptions.title', 'assumptions.lead'],
  'deal.empty.': ['grid', 'model', 'deck'].flatMap((k) => ['title', 'body', 'cta', 'prompt'].map((s) => `${k}.${s}`)),
  'settings.': ['firm', 'definitions', 'templates', 'users', 'connectors', 'mailbox', 'audit', 'preferences'].concat(
    ['firm', 'definitions', 'templates', 'connectors', 'mailbox'].flatMap((k) => ['title', 'body', 'cta'].map((s) => `${k}.${s}`)),
  ),
  'login.': ['p1', 'p2', 'p3'].flatMap((k) => ['title', 'body'].map((s) => `${k}.${s}`)),
};
for (const [prefix, tails] of Object.entries(dynamic)) for (const t of tails) used.add(prefix + t);

for (const k of used) if (!(k in en)) fail(`key used in source but missing from en.json: ${k}`);
const unused = Object.keys(en).filter((k) => !used.has(k));
if (unused.length) console.warn(`note: ${unused.length} catalogue keys are not referenced statically (dynamic or spare).`);

if (bad) process.exit(1);
console.log(`i18n ok: ${Object.keys(en).length} keys in en and ar, ${used.size} keys used in source`);
