import { forwardRef, useEffect, useId, useMemo, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { Button, IconArrowUp, IconSlash, IconX, Kbd, cx } from '../ds';
import { useT } from '../i18n';
import type { Agent, Deal, JobCreate } from '../api/types';
import { SOURCE_INPUT, SOURCE_KEYS } from '../app/lib';
import type { SourceKey } from '../app/lib';

export interface PromptBoxProps {
  prompt: string;
  onPrompt: (v: string) => void;
  deals: Deal[];
  agents: Agent[];
  dealId: string;
  onDeal: (id: string) => void;
  onSubmit: (body: JobCreate) => void;
  busy?: boolean;
}

/** The "Ask anything" box: multiline prompt, "/" skill picker with combinable chips, source toggle, deal chip. */
export const PromptBox = forwardRef<HTMLTextAreaElement, PromptBoxProps>(function PromptBox({ prompt, onPrompt, deals, agents, dealId, onDeal, onSubmit, busy }, ref) {
  const t = useT();
  const uid = useId();
  const [chips, setChips] = useState<Agent[]>([]);
  const [sources, setSources] = useState<Set<SourceKey>>(new Set<SourceKey>(['deal', 'filings']));
  const [active, setActive] = useState(0);
  const [dismissed, setDismissed] = useState(false);

  const slash = /(?:^|\s)\/(\S*)$/.exec(prompt);
  const query = slash ? slash[1].toLowerCase() : null;
  const matches = useMemo(() => {
    if (query === null) return [];
    return agents.filter((a) => a.enabled !== false && !chips.some((c) => c.id === a.id) && (a.name + ' ' + a.description).toLowerCase().includes(query)).slice(0, 8);
  }, [agents, chips, query]);
  const pickerOpen = query !== null && !dismissed;

  useEffect(() => {
    setActive(0);
    setDismissed(false);
  }, [query]);

  function pick(a: Agent) {
    setChips((c) => [...c, a]);
    onPrompt(prompt.replace(/(^|\s)\/\S*$/, '$1'));
  }

  function toggleSource(k: SourceKey) {
    setSources((s) => {
      const n = new Set(s);
      if (n.has(k)) n.delete(k);
      else n.add(k);
      return n;
    });
  }

  function submit() {
    const text = prompt.trim();
    if (!text && chips.length === 0) return;
    const inputs: Record<string, string> = { sources: SOURCE_KEYS.filter((k) => sources.has(k)).map((k) => SOURCE_INPUT[k]).join(',') };
    if (chips.length) inputs.skills = chips.map((c) => c.id).join(',');
    onSubmit({ prompt: text || chips.map((c) => c.name).join(' + '), deal_id: dealId || null, agent_id: chips[0]?.id ?? null, inputs });
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.nativeEvent.isComposing) return;
    if (pickerOpen && matches.length) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setActive((a) => Math.min(matches.length - 1, a + 1));
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setActive((a) => Math.max(0, a - 1));
        return;
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault();
        pick(matches[active]);
        return;
      }
    }
    if (e.key === 'Escape' && pickerOpen) {
      e.preventDefault();
      setDismissed(true);
      return;
    }
    if (e.key === 'Backspace' && prompt === '' && chips.length) {
      setChips((c) => c.slice(0, -1));
      return;
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  const srcLabel: Record<SourceKey, string> = { deal: t('source.deal'), filings: t('source.filings'), firm: t('source.firm'), web: t('source.web') };

  return (
    <div className="acr-ask">
      <div className="acr-ask__body">
        {chips.length > 0 && (
          <div className="acr-ask__chips">
            {chips.map((c) => (
              <span key={c.id} className="acr-chip acr-chip--accent" data-testid="skill-chip" data-id={c.id}>
                <IconSlash size={12} />
                {c.name}
                <button type="button" className="acr-chip__x" aria-label={t('ask.removeSkill', { name: c.name })} onClick={() => setChips((x) => x.filter((y) => y.id !== c.id))}>
                  <IconX size={11} />
                </button>
              </span>
            ))}
          </div>
        )}
        <textarea
          ref={ref}
          className="acr-ask__input"
          data-testid="ask-input"
          rows={3}
          value={prompt}
          placeholder={t('ask.placeholder')}
          aria-label={t('ask.label')}
          aria-autocomplete="list"
          aria-controls={pickerOpen ? `${uid}-skills` : undefined}
          aria-expanded={pickerOpen}
          onChange={(e) => onPrompt(e.target.value)}
          onKeyDown={onKey}
        />
        {pickerOpen && (
          <div className="acr-ask__picker" id={`${uid}-skills`} role="listbox" aria-label={t('ask.skills')} data-testid="skill-picker">
            <div className="acr-section-label acr-ask__picker-label">{t('ask.skills')}</div>
            {matches.length === 0 && <div className="acr-ask__picker-empty">{t('ask.noSkills')}</div>}
            {matches.map((a, i) => (
              <div
                key={a.id}
                role="option"
                aria-selected={i === active}
                className={cx('acr-ask__opt', i === active && 'is-active')}
                data-id={a.id}
                onMouseEnter={() => setActive(i)}
                onMouseDown={(e) => {
                  e.preventDefault();
                  pick(a);
                }}
              >
                <span className="acr-ask__opt-name">{a.name}</span>
                <span className="acr-ask__opt-desc acr-truncate">{a.description}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="acr-ask__bar">
        <label className="acr-chip acr-ask__deal">
          <span className="acr-sr-only">{t('ask.deal')}</span>
          <select data-testid="deal-chip" aria-label={t('ask.deal')} value={dealId} onChange={(e) => onDeal(e.target.value)}>
            <option value="">{t('ask.noDeal')}</option>
            {deals.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </label>
        <div className="acr-ask__sources" role="group" aria-label={t('source.label')}>
          {SOURCE_KEYS.map((k) => (
            <button key={k} type="button" className="acr-chip" aria-pressed={sources.has(k)} data-testid={`source-toggle-${k === 'deal' ? 'deal' : k}`} onClick={() => toggleSource(k)}>
              {srcLabel[k]}
            </button>
          ))}
        </div>
        <span className="acr-spacer-flex" />
        <span className="acr-ask__hint acr-faint">
          <Kbd>/</Kbd> {t('ask.slashHint')}
        </span>
        <Button variant="primary" size="md" icon={<IconArrowUp size={14} />} data-testid="ask-submit" loading={busy} onClick={submit}>
          {t('ask.run')}
        </Button>
      </div>
    </div>
  );
});
