import { useState } from 'react';
import { Badge, Button, IconCheck, IconDoc, IconExternal, IconLink } from '../../ds';
import { useI18n } from '../../i18n';
import { copyText } from '../shared/util';
import type { CitationPreview, DocInspect } from '../shared/api';

interface Props {
  info: DocInspect;
  current: CitationPreview | null;
  onSelect: (c: CitationPreview) => void;
  page: number;
  onJump: (page: number) => void;
}

function safeUrl(u: string | null): string | null {
  return u && /^https?:\/\//i.test(u) ? u : null;
}

/** Right-hand inspector: what the highlighted span says, where it comes from, and the rest of this document's citations. */
export function Inspector({ info, current, onSelect, page, onJump }: Props) {
  const { t, fmt } = useI18n();
  const [copied, setCopied] = useState(false);
  const c = current;
  const url = safeUrl(c?.url ?? null);

  async function copy() {
    if (!c) return;
    const parts = [`"${c.quote}"`, `${info.doc.name}${c.page ? `, ${t('viewers.cite.page', { n: c.page })}` : ''}`];
    if (c.as_of) parts.push(t('viewers.cite.asof', { date: c.as_of }));
    if (url) parts.push(url);
    if (await copyText(parts.join(' — '))) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    }
  }

  return (
    <aside className="pdfv__inspector" data-testid="inspector-panel" aria-label={t('viewers.pdf.inspector')}>
      <header className="pdfv__ihead">
        <span className="pdfv__idoc" aria-hidden="true">
          <IconDoc size={16} />
        </span>
        <div className="pdfv__iname">
          <h2 dir="auto" title={info.doc.name}>
            {info.doc.name}
          </h2>
          <p>
            {info.doc.pages != null && t('viewers.pdf.pages', { n: fmt.integer(info.doc.pages) })}
            {info.doc.lang ? ` · ${info.doc.lang.toUpperCase()}` : ''}
          </p>
        </div>
        {info.doc.status && !['ready', 'indexed'].includes(info.doc.status) && <Badge tone="warning">{info.doc.status}</Badge>}
      </header>

      {c ? (
        <section className="pdfv__cite" aria-labelledby="pdfv-cite-h">
          <h3 id="pdfv-cite-h" className="pdfv__label">
            {t('viewers.pdf.citation')}
          </h3>
          <blockquote className="pdfv__quote" data-testid="inspector-quote" dir="auto">
            {c.context_before && <span className="pdfv__dim">{c.context_before} </span>}
            <mark>{c.quote}</mark>
            {c.context_after && <span className="pdfv__dim"> {c.context_after}</span>}
          </blockquote>
          <dl className="pdfv__facts">
            <div>
              <dt>{t('viewers.pdf.page')}</dt>
              <dd data-testid="inspector-page" className="acr-num">
                {c.page ?? '–'}
              </dd>
            </div>
            <div>
              <dt>{t('viewers.pdf.asof')}</dt>
              <dd data-testid="inspector-asof" className="acr-num" dir="ltr">
                {c.as_of ? fmt.date(c.as_of) : '–'}
              </dd>
            </div>
            {c.xbrl_concept && (
              <div className="is-wide">
                <dt>{t('viewers.pdf.concept')}</dt>
                <dd className="acr-mono" dir="ltr">
                  {c.xbrl_concept}
                </dd>
              </div>
            )}
            <div className="is-wide">
              <dt>{t('viewers.pdf.source')}</dt>
              <dd>
                {url ? (
                  <a href={url} target="_blank" rel="noopener noreferrer" data-testid="inspector-source-link" className="pdfv__ext">
                    <span dir="ltr">{url.replace(/^https?:\/\//, '').slice(0, 56)}</span>
                    <IconExternal size={12} />
                  </a>
                ) : (
                  <span className="pdfv__dim" data-testid="inspector-source-link">
                    {t('viewers.pdf.nosource')}
                  </span>
                )}
              </dd>
            </div>
          </dl>
          <Button variant="secondary" size="sm" icon={copied ? <IconCheck size={14} /> : <IconLink size={14} />} onClick={copy} data-testid="copy-citation">
            {copied ? t('viewers.pdf.copied') : t('viewers.pdf.copy')}
          </Button>
        </section>
      ) : (
        <section className="pdfv__cite pdfv__cite--none">
          <h3 className="pdfv__label">{t('viewers.pdf.citation')}</h3>
          <p data-testid="inspector-quote" className="pdfv__dim">
            {info.citations.length ? t('viewers.pdf.pick') : t('viewers.pdf.nocurrent')}
          </p>
          <dl className="pdfv__facts">
            <div>
              <dt>{t('viewers.pdf.page')}</dt>
              <dd data-testid="inspector-page" className="acr-num">
                {page}
              </dd>
            </div>
            <div>
              <dt>{t('viewers.pdf.asof')}</dt>
              <dd data-testid="inspector-asof">{'–'}</dd>
            </div>
          </dl>
        </section>
      )}

      <section className="pdfv__list" aria-labelledby="pdfv-list-h">
        <h3 id="pdfv-list-h" className="pdfv__label">
          {t('viewers.pdf.others')} <span className="pdfv__count acr-num">{fmt.integer(info.citations.length)}</span>
        </h3>
        {info.citations.length === 0 ? (
          <p className="pdfv__dim">{t('viewers.pdf.nocites')}</p>
        ) : (
          <ul>
            {info.citations.map((x) => (
              <li key={x.token}>
                <button
                  type="button"
                  className={`pdfv__item${c?.token === x.token ? ' is-active' : ''}`}
                  aria-current={c?.token === x.token ? 'true' : undefined}
                  onClick={() => (x.bbox_norm ? onSelect(x) : x.page && onJump(x.page))}
                >
                  <span className="pdfv__pg acr-num">{x.page ?? '–'}</span>
                  <span className="pdfv__txt" dir="auto">
                    {x.quote || x.xbrl_concept || x.token}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </aside>
  );
}
