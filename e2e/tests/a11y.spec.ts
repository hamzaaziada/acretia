import { test, expect, signIn, setTheme, setLocale, findDeal, Page } from '../helpers';

// SPEC section 8 check 17: axe-free accessibility checks computed from the real DOM and computed styles.

const PAGES = ['/', '/deals', '/agents', '/notifications', '/library', '/settings/firm', '/settings/users', '/settings/audit'];

async function pagesFor(page: Page, api: any): Promise<string[]> {
  const deal = await findDeal(api, /apple/i);
  return [...PAGES, `/deals/${deal}`];
}

const inPage = {
  structure: () => {
    const named = (el: Element) => {
      const e = el as HTMLInputElement;
      if (e.getAttribute('aria-label')?.trim()) return true;
      const lb = e.getAttribute('aria-labelledby');
      if (lb && lb.split(/\s+/).some((id) => document.getElementById(id)?.textContent?.trim())) return true;
      if (e.id && document.querySelector(`label[for="${CSS.escape(e.id)}"]`)) return true;
      if (e.closest('label')) return true;
      if (e.getAttribute('title')?.trim()) return true;
      return false;
    };
    const unlabeled = [...document.querySelectorAll('input, select, textarea')]
      .filter((e) => {
        const t = (e as HTMLInputElement).type;
        if (t === 'hidden') return false;
        const cs = getComputedStyle(e);
        return cs.display !== 'none' && cs.visibility !== 'hidden';
      })
      .filter((e) => !named(e))
      .map((e) => e.outerHTML.slice(0, 100));
    return {
      lang: document.documentElement.lang,
      h1: document.querySelectorAll('h1').length,
      unlabeled,
      imgNoAlt: [...document.querySelectorAll('img:not([alt])')].map((e) => (e as HTMLImageElement).src.slice(0, 60)),
      buttonsNoName: [...document.querySelectorAll('button, [role=button]')].filter((b) => !(b.textContent || '').trim() && !b.getAttribute('aria-label') && !b.getAttribute('aria-labelledby') && !b.getAttribute('title')).map((b) => b.outerHTML.slice(0, 100)),
    };
  },
  contrast: () => {
    const parse = (c: string) => {
      const m = c.match(/rgba?\(([^)]+)\)/);
      if (!m) return [0, 0, 0, 1];
      const p = m[1].split(/[,\s/]+/).filter(Boolean).map(parseFloat);
      return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
    };
    const over = (top: number[], bottom: number[]) => {
      const a = top[3];
      return [top[0] * a + bottom[0] * (1 - a), top[1] * a + bottom[1] * (1 - a), top[2] * a + bottom[2] * (1 - a), 1];
    };
    const bgOf = (el: Element) => {
      const stack: number[][] = [];
      let n: Element | null = el;
      while (n) {
        const c = parse(getComputedStyle(n).backgroundColor);
        if (c[3] > 0) stack.push(c);
        if (c[3] >= 1) break;
        n = n.parentElement;
      }
      let acc = [255, 255, 255, 1];
      for (let i = stack.length - 1; i >= 0; i--) acc = over(stack[i], acc);
      return acc;
    };
    const lum = (c: number[]) => {
      const f = (v: number) => ((v /= 255) <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4));
      return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
    };
    const bad: string[] = [];
    let n = 0;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const seen = new Set<Element>();
    for (let t = walker.nextNode(); t; t = walker.nextNode()) {
      const el = t.parentElement;
      if (!el || seen.has(el) || !(t.textContent || '').trim()) continue;
      seen.add(el);
      const cs = getComputedStyle(el);
      if (cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity) === 0) continue;
      const r = el.getBoundingClientRect();
      if (r.width < 1 || r.height < 1) continue;
      if (el.closest('[disabled], [aria-disabled=true], script, style, canvas, svg')) continue;
      const fg = over(parse(cs.color), bgOf(el));
      const [l1, l2] = [lum(fg), lum(bgOf(el))].sort((a, b) => b - a);
      const ratio = (l1 + 0.05) / (l2 + 0.05);
      const size = parseFloat(cs.fontSize);
      const large = size >= 24 || (size >= 18.66 && parseInt(cs.fontWeight) >= 700);
      n++;
      if (ratio < (large ? 3 : 4.5)) bad.push(`${ratio.toFixed(2)} "${(t.textContent || '').trim().slice(0, 30)}" <${el.tagName.toLowerCase()}${el.getAttribute('data-testid') ? ' ' + el.getAttribute('data-testid') : ''}>`);
    }
    return { n, bad: bad.slice(0, 12), badCount: bad.length };
  },
  focusStyle: () => {
    const el = document.activeElement as HTMLElement | null;
    if (!el || el === document.body) return { ok: true, tag: 'body' };
    const cs = getComputedStyle(el);
    const outline = cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0;
    const shadow = cs.boxShadow && cs.boxShadow !== 'none';
    const border = el.matches(':focus-visible') ? true : false;
    return { ok: outline || !!shadow, tag: el.tagName.toLowerCase() + (el.getAttribute('data-testid') ? '[' + el.getAttribute('data-testid') + ']' : ''), border };
  },
};

test.describe('a11y', () => {
  test('a11y: lang, single h1, labelled inputs, named buttons on every page', async ({ page }) => {
    const api = await signIn(page, 'owner', '/');
    const bad: string[] = [];
    for (const p of await pagesFor(page, api)) {
      await page.goto(p);
      await expect(page.getByTestId('app-shell')).toBeVisible();
      await page.waitForTimeout(400);
      const s = await page.evaluate(inPage.structure);
      if (!s.lang) bad.push(`${p}: no <html lang>`);
      if (s.h1 !== 1) bad.push(`${p}: ${s.h1} h1 elements`);
      if (s.unlabeled.length) bad.push(`${p}: unlabelled inputs ${s.unlabeled.slice(0, 2).join(' | ')}`);
      if (s.buttonsNoName.length) bad.push(`${p}: unnamed buttons ${s.buttonsNoName.slice(0, 2).join(' | ')}`);
    }
    await page.context().clearCookies();
    await page.goto('/login');
    const s = await page.evaluate(inPage.structure);
    if (!s.lang) bad.push('/login: no <html lang>');
    if (s.h1 !== 1) bad.push(`/login: ${s.h1} h1 elements`);
    if (s.unlabeled.length) bad.push(`/login: unlabelled inputs ${s.unlabeled.join(' | ')}`);
    expect(bad, bad.join('\n')).toEqual([]);
  });

  test('a11y: keyboard focus is visible on Tab', async ({ page }) => {
    const api = await signIn(page, 'owner', '/');
    const bad: string[] = [];
    for (const p of ['/login', '/', '/agents', '/settings/users', `/deals/${await findDeal(api, /apple/i)}`]) {
      if (p === '/login') await page.context().clearCookies();
      else if (!(await page.getByTestId('app-shell').isVisible().catch(() => false))) await signIn(page, 'owner', '');
      await page.goto(p);
      await page.waitForTimeout(400);
      for (let i = 0; i < 8; i++) {
        await page.keyboard.press('Tab');
        const f = await page.evaluate(inPage.focusStyle);
        if (!f.ok) bad.push(`${p}: no visible focus indicator on ${f.tag}`);
      }
    }
    expect(bad, bad.join('\n')).toEqual([]);
  });

  for (const mode of ['light', 'dark'] as const) {
    test(`a11y: text contrast >= 4.5:1 (3:1 large) in ${mode} mode`, async ({ page }) => {
      const api = await signIn(page, 'owner', '/');
      const bad: string[] = [];
      let total = 0;
      for (const p of await pagesFor(page, api)) {
        await page.goto(p);
        await expect(page.getByTestId('app-shell')).toBeVisible();
        expect(await setTheme(page, mode), `${mode} theme must apply`).toBe(true);
        await page.waitForTimeout(300);
        const c = await page.evaluate(inPage.contrast);
        total += c.n;
        if (c.badCount) bad.push(`${p}: ${c.badCount} low-contrast texts, e.g. ${c.bad.slice(0, 4).join('; ')}`);
      }
      expect(total, 'text elements were measured').toBeGreaterThan(50);
      expect(bad, bad.join('\n')).toEqual([]);
    });
  }

  test('a11y: Arabic sets lang=ar dir=rtl and the shell mirrors with logical (not physical) margins', async ({ page }) => {
    const api = await signIn(page, 'owner', '/');
    void api;
    const probe = () =>
      page.evaluate(() => {
        const out: Record<string, number[]> = {};
        const sels = ['sidebar', 'nav-home', 'nav-deals', 'nav-agents', 'user-menu', 'notif-bell', 'org-switcher', 'theme-toggle', 'locale-toggle'];
        for (const id of sels) {
          const e = document.querySelector(`[data-testid="${id}"]`);
          if (!e) continue;
          const cs = getComputedStyle(e);
          out[id] = [parseFloat(cs.marginLeft), parseFloat(cs.marginRight), parseFloat(cs.paddingLeft), parseFloat(cs.paddingRight)];
        }
        const sb = document.querySelector('[data-testid="sidebar"]')?.getBoundingClientRect();
        return { m: out, sidebarLeft: sb ? sb.left : -1, w: window.innerWidth, ta: getComputedStyle(document.body).textAlign };
      });
    const en = await probe();
    expect(await setLocale(page, 'ar'), 'Arabic locale applies').toBe(true);
    const html = await page.evaluate(() => ({ lang: document.documentElement.lang, dir: document.documentElement.dir }));
    expect(html.lang).toMatch(/^ar/);
    expect(html.dir).toBe('rtl');
    const ar = await probe();
    expect(ar.sidebarLeft, 'sidebar moves to the inline-start (right) edge in RTL').toBeGreaterThan(ar.w / 2);
    const wrong: string[] = [];
    for (const [k, v] of Object.entries(en.m)) {
      const a = ar.m[k];
      if (!a) continue;
      if (v[0] !== v[1] && !(a[0] === v[1] && a[1] === v[0])) wrong.push(`${k} margins ${v.slice(0, 2)} -> ${a.slice(0, 2)}`);
      if (v[2] !== v[3] && !(a[2] === v[3] && a[3] === v[2])) wrong.push(`${k} paddings ${v.slice(2)} -> ${a.slice(2)}`);
    }
    expect(wrong, `physical left/right spacing did not mirror: ${wrong.join('; ')}`).toEqual([]);
    // static: no physical left/right declarations in the app's own stylesheets
    const phys = await page.evaluate(() => {
      const bad: string[] = [];
      const props = ['margin-left', 'margin-right', 'padding-left', 'padding-right', 'border-left', 'border-right', 'float'];
      for (const ss of [...document.styleSheets]) {
        let rules: CSSRuleList;
        try {
          rules = ss.cssRules;
        } catch {
          continue;
        }
        for (const r of [...rules]) {
          const st = r as CSSStyleRule;
          if (!st.style || /pdf|textLayer|annotation|katex/i.test(st.selectorText || '')) continue;
          for (const p of props) if (st.style.getPropertyValue(p)) bad.push(`${st.selectorText}{${p}}`);
          const ta = st.style.getPropertyValue('text-align');
          if (ta === 'left' || ta === 'right') bad.push(`${st.selectorText}{text-align:${ta}}`);
        }
      }
      return bad;
    });
    expect(phys.slice(0, 8), `${phys.length} physical left/right declarations in app CSS`).toEqual([]);
    await setLocale(page, 'en');
  });
});
