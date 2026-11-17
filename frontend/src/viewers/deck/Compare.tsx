import { useEffect, useState } from 'react';
import { api } from '../../api/client';
import { Badge, Button, Dialog, IconUndo, Select, SkeletonRows, cx, useToast } from '../../ds';
import { useI18n } from '../../i18n';
import { errText } from './util';
import type { ComparePayload, DeckPayload } from './types';

interface Props {
  open: boolean;
  deck: DeckPayload;
  canEdit: boolean;
  onClose: () => void;
  onRolledBack: (version: number) => void;
}

/** Side-by-side version compare: changed slides are highlighted, unchanged ones are marked identical (parity item 39). */
export function Compare({ open, deck, canEdit, onClose, onRolledBack }: Props) {
  const { t, fmt } = useI18n();
  const toast = useToast();
  const vs = deck.versions.map((v) => v.version);
  const latest = Math.max(...vs);
  const [a, setA] = useState(vs.length > 1 ? vs[vs.length - 2] : latest);
  const [b, setB] = useState(latest);
  const [data, setData] = useState<ComparePayload | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setA(vs.length > 1 ? vs[vs.length - 2] : latest);
    setB(latest);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, latest]);

  useEffect(() => {
    if (!open) return;
    setData(null);
    const ctl = new AbortController();
    api
      .get<ComparePayload>(`/decks/${deck.deal_id}/${encodeURIComponent(deck.name)}/compare`, { query: { a, b }, signal: ctl.signal })
      .then(setData)
      .catch((e) => !(e instanceof DOMException) && toast.push({ kind: 'error', ...errText(e) }));
    return () => ctl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, a, b, deck.name, deck.deal_id]);

  async function rollback(to: number) {
    setBusy(true);
    try {
      const r = await api.post<{ version: number }>(`/decks/${deck.deal_id}/${encodeURIComponent(deck.name)}/rollback`, { version: to });
      toast.push({ kind: 'success', title: t('viewers2.deck.rolledBack', { from: to, to: r.version }) });
      onRolledBack(r.version);
      onClose();
    } catch (e) {
      toast.push({ kind: 'error', ...errText(e) });
    } finally {
      setBusy(false);
    }
  }

  const opts = deck.versions.map((v) => ({ value: String(v.version), label: `v${v.version} · ${fmt.dateTime(v.created_at)}` }));
  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      title={t('viewers2.deck.compare')}
      closeLabel={t('viewers2.common.close')}
      footer={
        canEdit ? (
          <>
            <span className="dk-spacer" />
            <Button variant="secondary" icon={<IconUndo size={14} />} loading={busy} disabled={a === latest} onClick={() => void rollback(a)}>
              {t('viewers2.deck.rollbackTo', { version: a })}
            </Button>
          </>
        ) : undefined
      }
    >
      <div data-testid="version-compare" className="dk-compare">
        <div className="dk-compare__pick">
          <Select label={t('viewers2.deck.versionA')} value={String(a)} onChange={(e) => setA(Number(e.target.value))} options={opts} />
          <Select label={t('viewers2.deck.versionB')} value={String(b)} onChange={(e) => setB(Number(e.target.value))} options={opts} />
        </div>
        {!data ? (
          <SkeletonRows rows={4} label={t('viewers2.common.loading')} />
        ) : (
          <>
            <p className="dk-muted" role="status">
              {data.identical ? t('viewers2.deck.allIdentical') : t('viewers2.deck.changedCount', { count: data.changed.length, total: data.slides.length })}
            </p>
            <ol className="dk-compare__list">
              {data.slides.map((s) => (
                <li key={s.n} className={cx('dk-compare__row', s.status === 'changed' && 'is-changed', s.status === 'unchanged' && 'is-same')} data-status={s.status} data-slide={s.n}>
                  <div className="dk-compare__head">
                    <span className="dk-compare__n acr-num">{s.n}</span>
                    <span className="dk-compare__title">{s.title_b ?? s.title_a}</span>
                    <Badge tone={s.status === 'unchanged' ? 'neutral' : s.status === 'changed' ? 'warning' : 'info'} dot>
                      {t(`viewers2.deck.cmp.${s.status}`)}
                    </Badge>
                  </div>
                  {s.status !== 'unchanged' ? (
                    <div className="dk-compare__pair">
                      <figure>
                        {s.status !== 'added' && <img loading="lazy" src={`${data.png_a}${s.n}.png`} alt={t('viewers2.deck.slideAlt', { n: s.n, title: s.title_a ?? '' })} />}
                        <figcaption>v{data.a}</figcaption>
                      </figure>
                      <figure>
                        {s.status !== 'removed' && <img loading="lazy" src={`${data.png_b}${s.n}.png`} alt={t('viewers2.deck.slideAlt', { n: s.n, title: s.title_b ?? '' })} />}
                        <figcaption>v{data.b}</figcaption>
                      </figure>
                      {(s.text_diff.removed.length > 0 || s.text_diff.added.length > 0) && (
                        <ul className="dk-diff">
                          {s.text_diff.removed.map((x, i) => (
                            <li key={`r${i}`} className="is-del">
                              {x}
                            </li>
                          ))}
                          {s.text_diff.added.map((x, i) => (
                            <li key={`a${i}`} className="is-add">
                              {x}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  ) : (
                    <p className="dk-muted">{t('viewers2.deck.identical')}</p>
                  )}
                </li>
              ))}
            </ol>
          </>
        )}
      </div>
    </Dialog>
  );
}
