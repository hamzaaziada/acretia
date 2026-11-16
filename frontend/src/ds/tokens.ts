/**
 * Design tokens, mirrored from tokens.css so tests and the gate can compute WCAG contrast
 * without a browser. Keep the two files in sync (scripts/check-tokens.mjs verifies it).
 */
export type ThemeTokens = Record<string, string>;

export const lightTokens: ThemeTokens = {
  bg: '#F3F5F8',
  surface: '#FFFFFF',
  surface2: '#ECF0F5',
  surfaceHover: '#E4E9F0',
  border: '#D5DCE5',
  borderStrong: '#B7C2D0',
  text: '#0E1A29',
  text2: '#42536A',
  text3: '#586A82',
  accent: '#0B6B63',
  accentHover: '#085650',
  accentContrast: '#FFFFFF',
  accentSubtle: '#E1F2F0',
  accentText: '#0B6B63',
  positive: '#14632F',
  positiveBg: '#E4F4EA',
  warning: '#8A3D07',
  warningBg: '#FDF0DC',
  negative: '#B01E1E',
  negativeBg: '#FCE9E9',
  info: '#1F4FA8',
  infoBg: '#E6EEFB',
  chrome: '#0B1F33',
  chromeText: '#C6D2E1',
  chromeTextMuted: '#93A5BC',
  chromeActive: '#FFFFFF',
  chromeActiveBg: '#16314D',
  chromeBorder: '#1C3652',
  chromeAccent: '#3CC9BA',
};

export const darkTokens: ThemeTokens = {
  bg: '#08121C',
  surface: '#0E1B2A',
  surface2: '#142536',
  surfaceHover: '#1A2E43',
  border: '#22364A',
  borderStrong: '#35506B',
  text: '#E8EEF5',
  text2: '#AEBCCD',
  text3: '#8D9FB4',
  accent: '#2DC5B5',
  accentHover: '#52D6C8',
  accentContrast: '#032320',
  accentSubtle: '#0F2E2D',
  accentText: '#4FD8CA',
  positive: '#4CD48A',
  positiveBg: '#10301F',
  warning: '#F2B347',
  warningBg: '#35260C',
  negative: '#FF8A8A',
  negativeBg: '#3A1618',
  info: '#8FB4F5',
  infoBg: '#14264A',
  chrome: '#060E17',
  chromeText: '#B3C2D4',
  chromeTextMuted: '#8496AD',
  chromeActive: '#FFFFFF',
  chromeActiveBg: '#13293E',
  chromeBorder: '#16293C',
  chromeAccent: '#3CC9BA',
};

export function luminance(hex: string): number {
  const h = hex.replace('#', '');
  const ch = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  const [r, g, b] = ch.map((c) => (c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrast(a: string, b: string): number {
  const la = luminance(a);
  const lb = luminance(b);
  const [hi, lo] = la > lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

/** Foreground/background pairs that carry text and must reach 4.5:1. */
export const textPairs: Array<[string, string]> = [
  ['text', 'bg'],
  ['text', 'surface'],
  ['text', 'surface2'],
  ['text2', 'surface'],
  ['text2', 'bg'],
  ['text2', 'surface2'],
  ['text3', 'surface'],
  ['text3', 'bg'],
  ['text3', 'surface2'],
  ['accentText', 'surface'],
  ['accentText', 'bg'],
  ['accentContrast', 'accent'],
  ['accentContrast', 'accentHover'],
  ['accentText', 'accentSubtle'],
  ['positive', 'surface'],
  ['positive', 'positiveBg'],
  ['warning', 'surface'],
  ['warning', 'warningBg'],
  ['negative', 'surface'],
  ['negative', 'negativeBg'],
  ['info', 'surface'],
  ['info', 'infoBg'],
  ['chromeText', 'chrome'],
  ['chromeTextMuted', 'chrome'],
  ['chromeActive', 'chromeActiveBg'],
  ['chromeText', 'chromeActiveBg'],
  ['chromeAccent', 'chrome'],
];
