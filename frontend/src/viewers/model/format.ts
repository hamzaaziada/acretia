/** Excel number formats, rendered the way the workbook author meant them: (negatives), 0.0%, 0.0x, thousands, dashes for zero. */

type Tok = { k: 'lit'; s: string } | { k: 'num'; minFrac: number; maxFrac: number; group: boolean; scale: number; pct: boolean };
interface Section {
  toks: Tok[];
  pct: boolean;
  date: boolean;
  hasNum: boolean;
  text: boolean;
}

const cache = new Map<string, Section[]>();

function splitSections(fmt: string): string[] {
  const out: string[] = [];
  let cur = '';
  let q = false;
  for (let i = 0; i < fmt.length; i++) {
    const ch = fmt[i];
    if (ch === '"') q = !q;
    if (ch === ';' && !q) {
      out.push(cur);
      cur = '';
    } else cur += ch;
  }
  out.push(cur);
  return out;
}

function parseSection(src: string): Section {
  const toks: Tok[] = [];
  let lit = '';
  const flush = () => {
    if (lit) toks.push({ k: 'lit', s: lit });
    lit = '';
  };
  let date = false;
  let pct = false;
  let hasNum = false;
  let i = 0;
  while (i < src.length) {
    const ch = src[i];
    if (ch === '"') {
      const j = src.indexOf('"', i + 1);
      lit += src.slice(i + 1, j === -1 ? src.length : j);
      i = j === -1 ? src.length : j + 1;
    } else if (ch === '\\') {
      lit += src[i + 1] ?? '';
      i += 2;
    } else if (ch === '_') {
      lit += ' '; // figure space: keeps columns of numbers aligned despite the ")" of negatives
      i += 2;
    } else if (ch === '*') {
      i += 2;
    } else if (ch === '[') {
      const j = src.indexOf(']', i);
      i = j === -1 ? src.length : j + 1;
    } else if (/[0#?.,]/.test(ch) && !(ch === ',' && !/[0#?]/.test(src[i - 1] ?? ''))) {
      let j = i;
      while (j < src.length && /[0#?.,]/.test(src[j])) j++;
      const run = src.slice(i, j);
      const dot = run.indexOf('.');
      const intPart = dot === -1 ? run : run.slice(0, dot);
      const frac = dot === -1 ? '' : run.slice(dot + 1).replace(/,/g, '');
      let scale = 0;
      const trail = /,+$/.exec(intPart);
      if (trail && dot === -1) scale = trail[0].length;
      flush();
      toks.push({
        k: 'num',
        minFrac: (frac.match(/0/g) ?? []).length,
        maxFrac: frac.length,
        group: /[0#?],[0#?]/.test(intPart),
        scale,
        pct: false,
      });
      hasNum = true;
      i = j;
    } else if (ch === '%') {
      pct = true;
      lit += '%';
      i++;
    } else if (/[ymdhs]/i.test(ch) && !/^[xe]$/i.test(ch)) {
      date = true;
      lit += ch;
      i++;
    } else if (ch === '@') {
      lit += '\u0000';
      i++;
    } else {
      lit += ch;
      i++;
    }
  }
  flush();
  return { toks, pct, date, hasNum, text: src.includes('@') };
}

function sections(fmt: string): Section[] {
  let s = cache.get(fmt);
  if (!s) {
    s = splitSections(fmt).map(parseSection);
    cache.set(fmt, s);
  }
  return s;
}

const nfCache = new Map<string, Intl.NumberFormat>();
function nf(tag: string, min: number, max: number, group: boolean) {
  const k = `${tag}|${min}|${max}|${group}`;
  let f = nfCache.get(k);
  if (!f) {
    f = new Intl.NumberFormat(tag, { minimumFractionDigits: min, maximumFractionDigits: max, useGrouping: group });
    nfCache.set(k, f);
  }
  return f;
}

export interface FmtOpts {
  /** Arabic-Indic digits when the user has chosen them. */
  arabicDigits?: boolean;
}

function tagOf(o?: FmtOpts) {
  return o?.arabicDigits ? 'en-US-u-nu-arab' : 'en-US-u-nu-latn';
}

function serialToDate(v: number): Date {
  return new Date(Math.round((v - 25569) * 86400000));
}

function dateText(pattern: string, d: Date): string {
  const M = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  const p2 = (n: number) => String(n).padStart(2, '0');
  return pattern.replace(/yyyy|yy|mmmm|mmm|mm|m|dd|d/gi, (m) => {
    switch (m.toLowerCase()) {
      case 'yyyy':
        return String(d.getUTCFullYear());
      case 'yy':
        return p2(d.getUTCFullYear() % 100);
      case 'mmmm':
        return M[d.getUTCMonth()];
      case 'mmm':
        return M[d.getUTCMonth()].slice(0, 3);
      case 'mm':
        return p2(d.getUTCMonth() + 1);
      case 'm':
        return String(d.getUTCMonth() + 1);
      case 'dd':
        return p2(d.getUTCDate());
      default:
        return String(d.getUTCDate());
    }
  });
}

function render(sec: Section, v: number, o?: FmtOpts): string {
  const tag = tagOf(o);
  let out = '';
  for (const t of sec.toks) {
    if (t.k === 'lit') out += t.s;
    else {
      let x = v;
      if (sec.pct) x *= 100;
      if (t.scale) x /= 1000 ** t.scale;
      out += nf(tag, t.minFrac, Math.max(t.minFrac, t.maxFrac), t.group).format(x);
    }
  }
  return out;
}

/** Display text for a cell value under an Excel number-format code (General when absent). */
export function formatValue(v: unknown, fmt?: string | null, o?: FmtOpts): string {
  if (v === null || v === undefined || v === '') return '';
  if (typeof v === 'boolean') return v ? 'TRUE' : 'FALSE';
  if (typeof v === 'string') return v;
  if (typeof v !== 'number' || !Number.isFinite(v)) return String(v);
  if (!fmt || fmt === 'General') {
    const tag = tagOf(o);
    if (Number.isInteger(v)) return nf(tag, 0, 0, Math.abs(v) >= 10000).format(v);
    return nf(tag, 0, Math.abs(v) < 1 ? 4 : 2, true).format(v);
  }
  const secs = sections(fmt);
  if (secs[0].date) return dateText(secs[0].toks.map((t) => (t.k === 'lit' ? t.s : '')).join(''), serialToDate(v));
  let sec = secs[0];
  let x = v;
  let neg = false;
  if (v < 0) {
    if (secs.length >= 2) {
      sec = secs[1];
      x = -v;
    } else neg = true;
  } else if (v === 0 && secs.length >= 3) sec = secs[2];
  if (neg) x = -v;
  if (!sec.hasNum) return render(sec, x, o).replace(/\u0000/g, '');
  const s = render(sec, x, o);
  return neg ? `-${s}` : s;
}

/** Text a person edits: the number as typed in Excel ("10%" for a percent cell, never float noise). */
export function editText(v: unknown, fmt?: string | null): string {
  if (typeof v !== 'number') return v == null ? '' : String(v);
  if (fmt && fmt.includes('%')) return `${Number((v * 100).toPrecision(10))}%`;
  return String(Number(v.toPrecision(12)));
}

/** Parse what a person typed; percent-formatted cells read a bare 10 as 10%. Returns null when it is not a number. */
export function parseInput(text: string, fmt?: string | null): number | null {
  let s = text.trim().replace(/[\s ,$]/g, '');
  if (!s) return null;
  let neg = false;
  if (/^\(.*\)$/.test(s)) {
    neg = true;
    s = s.slice(1, -1);
  }
  let pct = false;
  if (s.endsWith('%')) {
    pct = true;
    s = s.slice(0, -1);
  } else if (/x$/i.test(s)) s = s.slice(0, -1);
  if (!/^[+-]?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?$/i.test(s)) return null;
  let n = Number(s);
  if (!Number.isFinite(n)) return null;
  if (neg) n = -n;
  if (pct || (fmt && fmt.includes('%'))) n /= 100;
  return n;
}

export function hasPercent(fmt?: string | null): boolean {
  return !!fmt && fmt.includes('%');
}
