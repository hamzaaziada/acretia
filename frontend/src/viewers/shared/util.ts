import { useToast } from '../../ds';
import type { ToastInput } from '../../ds';

/** Toast when the shell provides one; a silent no-op in isolation (the viewer then relies on inline status text). */
export function useSafeToast(): (t: ToastInput) => void {
  try {
    const { push } = useToast();
    return push;
  } catch {
    return () => undefined;
  }
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.insetBlockStart = '-1000px';
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand('copy');
      ta.remove();
      return ok;
    } catch {
      return false;
    }
  }
}
