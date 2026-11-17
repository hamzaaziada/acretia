import { useRef, useState } from 'react';
import type { DragEvent } from 'react';
import { Badge, Button, Dialog, EmptyState, IconDeck, IconDownload, IconUpload, ProgressBar, Select, SkeletonRows, useToast } from '../ds';
import { API_BASE, api, uploadFile } from '../api/client';
import { items, useResource } from '../api/hooks';
import type { Page } from '../api/types';
import { errorToast } from '../app/lib';
import { useI18n } from '../i18n';
import { LoadError, ReadOnlyNote, sizeLabel, useIsOwner } from './lib/shared';
import type { Asset, AssetKind, AssetStyle } from './lib/types';
import './lib/firm.css';

const KINDS: Array<{ value: AssetKind; label: string; accept: string }> = [
  { value: 'template', label: 'firm.tpl.kind.template', accept: '.pptx,.potx' },
  { value: 'sample_deck', label: 'firm.tpl.kind.sample_deck', accept: '.pptx' },
  { value: 'sample_model', label: 'firm.tpl.kind.sample_model', accept: '.xlsx' },
  { value: 'logo', label: 'firm.tpl.kind.logo', accept: '.png,.jpg,.jpeg' },
];

export default function Templates() {
  const { t } = useI18n();
  const toast = useToast();
  const owner = useIsOwner();
  const res = useResource<Asset[]>(async (signal) => items(await api.get<Page<Asset> | Asset[]>('/firm/assets', { signal })), []);
  const [kind, setKind] = useState<AssetKind>('template');
  const [over, setOver] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [uploading, setUploading] = useState('');
  const [removing, setRemoving] = useState<Asset | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const accept = KINDS.find((k) => k.value === kind)?.accept;

  async function send(file: File) {
    setUploading(file.name);
    setProgress(0);
    try {
      await uploadFile<Asset>(`/firm/assets?kind=${kind}`, file, setProgress);
      toast.push({ kind: 'success', title: t('firm.tpl.uploaded', { name: file.name }) });
      res.reload();
    } catch (e) {
      toast.push(errorToast(e, t('firm.tpl.uploadFailed', { name: file.name })));
    } finally {
      setProgress(null);
      setUploading('');
      if (input.current) input.current.value = '';
    }
  }
  function drop(e: DragEvent) {
    e.preventDefault();
    setOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f && owner) void send(f);
  }
  async function makeDefault(a: Asset) {
    try {
      await api.patch(`/firm/assets/${a.id}`, { is_default: true });
      res.reload();
    } catch (e) {
      toast.push(errorToast(e, t('firm.tpl.defaultFailed')));
    }
  }
  async function remove(a: Asset) {
    try {
      await api.del(`/firm/assets/${a.id}`);
      setRemoving(null);
      res.reload();
    } catch (e) {
      toast.push(errorToast(e, t('firm.tpl.removeFailed')));
    }
  }

  if (res.error) return <LoadError error={res.error} retry={res.reload} />;
  const list = res.data ?? [];
  return (
    <div className="acr-firm">
      <p className="acr-firm__intro">{t('firm.tpl.intro')}</p>
      {!owner && <ReadOnlyNote>{t('firm.ownerOnly')}</ReadOnlyNote>}
      {owner && (
        <div
          className={`acr-firm-drop${over ? ' is-over' : ''}`}
          onDragOver={(e) => {
            e.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={drop}
        >
          <IconUpload size={20} />
          <div className="acr-firm-drop__title">{t('firm.tpl.drop')}</div>
          <div className="acr-firm-drop__row">
            <Select label={t('firm.tpl.kind')} value={kind} onChange={(e) => setKind(e.target.value as AssetKind)} options={KINDS.map((k) => ({ value: k.value, label: t(k.label) }))} data-testid="template-kind" />
            <Button variant="primary" icon={<IconUpload size={14} />} onClick={() => input.current?.click()} disabled={progress !== null}>
              {t('firm.tpl.choose')}
            </Button>
          </div>
          <input
            ref={input}
            type="file"
            accept={accept}
            className="acr-sr-only"
            tabIndex={-1}
            aria-label={t('firm.tpl.choose')}
            data-testid="template-upload"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void send(f);
            }}
          />
          <span className="acr-firm__meta">{t('firm.tpl.accepts')}</span>
          {progress !== null && (
            <div style={{ inlineSize: 'min(360px, 100%)' }}>
              <ProgressBar value={progress} label={t('firm.tpl.uploading', { name: uploading })} />
            </div>
          )}
        </div>
      )}
      {res.loading && !res.data ? (
        <SkeletonRows rows={3} label={t('common.loading')} />
      ) : list.length === 0 ? (
        <EmptyState icon={<IconDeck size={22} />} title={t('firm.tpl.empty.title')} body={t('firm.tpl.empty.body')} action={{ label: t('firm.tpl.choose'), onClick: () => input.current?.click() }} />
      ) : (
        <div className="acr-firm__grid acr-firm__grid--wide" data-testid="template-list">
          {list.map((a) => (
            <AssetCard key={a.id} a={a} owner={owner} onDefault={() => makeDefault(a)} onRemove={() => setRemoving(a)} />
          ))}
        </div>
      )}
      <Dialog
        open={removing !== null}
        onClose={() => setRemoving(null)}
        title={t('firm.tpl.removeTitle')}
        description={removing ? t('firm.tpl.removeBody', { name: removing.name }) : ''}
        closeLabel={t('common.close')}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setRemoving(null)}>
              {t('common.cancel')}
            </Button>
            <Button variant="danger" onClick={() => removing && remove(removing)}>
              {t('firm.tpl.remove')}
            </Button>
          </>
        }
      >
        <p className="acr-muted">{t('firm.tpl.removeNote')}</p>
      </Dialog>
    </div>
  );
}

function AssetCard({ a, owner, onDefault, onRemove }: { a: Asset; owner: boolean; onDefault: () => void; onRemove: () => void }) {
  const { t, fmt } = useI18n();
  const canDefault = a.kind === 'template' || a.kind === 'logo';
  const kindLabel = KINDS.find((k) => k.value === a.kind)?.label ?? 'firm.tpl.kind.template';
  return (
    <article className={`acr-firm-asset${a.is_default ? ' is-default' : ''}`} data-testid="template-card" data-id={a.id}>
      <header className="acr-firm-asset__head">
        <div className="acr-firm-asset__title">
          <span className="acr-firm-asset__name acr-firm-ltr">{a.name}</span>
          <span className="acr-firm__meta">
            {t(kindLabel)} · <bdi>{sizeLabel(a.size, fmt)}</bdi> · <bdi>{fmt.date(a.created_at)}</bdi>
          </span>
        </div>
        {a.is_default && <Badge tone="accent">{t('firm.tpl.default')}</Badge>}
      </header>
      {a.kind === 'logo' && <img className="acr-firm-logo" src={`${API_BASE}/firm/assets/${a.id}/file`} alt={t('firm.tpl.logoAlt', { name: a.name })} />}
      {a.style_error && (
        <p className="acr-banner acr-banner--negative" role="alert">
          {a.style_error} {a.style_hint}
        </p>
      )}
      {a.style && <StylePreview s={a.style} />}
      <div className="acr-firm__actions">
        <a className="acr-btn acr-btn--ghost acr-btn--sm" href={`${API_BASE}/firm/assets/${a.id}/file`} download={a.name}>
          <IconDownload size={13} />
          <span className="acr-btn__label">{t('common.download')}</span>
        </a>
        {owner && canDefault && !a.is_default && (
          <Button size="sm" variant="secondary" onClick={onDefault} data-testid="template-set-default">
            {t('firm.tpl.setDefault')}
          </Button>
        )}
        {owner && (
          <Button size="sm" variant="ghost" onClick={onRemove}>
            {t('firm.tpl.remove')}
          </Button>
        )}
      </div>
    </article>
  );
}

function StylePreview({ s }: { s: AssetStyle }) {
  const { t, fmt } = useI18n();
  const colors = s.palette.filter((p) => p.token !== 'mute_bar').slice(0, 12);
  const [w, h] = s.slide_size_in;
  const shown = s.layouts.slice(0, 8);
  return (
    <div className="acr-stack" data-testid="template-style">
      <h3 className="acr-firm__sub">{t('firm.tpl.palette')}</h3>
      <div className="acr-firm-swatches" role="list" aria-label={t('firm.tpl.palette')}>
        {colors.map((c) => (
          <div key={c.token} className="acr-firm-swatch" role="listitem" title={`${c.token} ${c.hex}`}>
            <span className="acr-firm-swatch__chip" style={{ background: c.hex }} />
            <span className="acr-firm-swatch__hex">{c.hex}</span>
            <span className="acr-sr-only">{c.token}</span>
          </div>
        ))}
      </div>
      <dl className="acr-firm-kv">
        <dt>{t('firm.tpl.headingFont')}</dt>
        <dd className="acr-firm-ltr">{s.fonts.major ?? '—'}</dd>
        <dt>{t('firm.tpl.bodyFont')}</dt>
        <dd className="acr-firm-ltr">{s.fonts.minor ?? '—'}</dd>
        {w != null && h != null && (
          <>
            <dt>{t('firm.tpl.slideSize')}</dt>
            <dd className="acr-firm-ltr">{`${fmt.number(w, { maximumFractionDigits: 2 })} × ${fmt.number(h, { maximumFractionDigits: 2 })} in`}</dd>
          </>
        )}
        {s.sizes.title != null && (
          <>
            <dt>{t('firm.tpl.sizes')}</dt>
            <dd>{t('firm.tpl.sizesValue', { title: fmt.number(s.sizes.title, { maximumFractionDigits: 0 }), body: fmt.number(s.sizes.body ?? 0, { maximumFractionDigits: 0 }) })}</dd>
          </>
        )}
      </dl>
      {s.layouts.length > 0 && (
        <>
          <h3 className="acr-firm__sub">{t('firm.tpl.layouts', { n: fmt.integer(s.layouts.length) })}</h3>
          <div className="acr-firm-chips">
            {shown.map((l) => (
              <span key={l} className={`acr-chip${l === s.layout_used ? ' acr-chip--accent' : ''}`}>
                {l}
              </span>
            ))}
            {s.layouts.length > shown.length && <span className="acr-chip" dir="ltr">+{fmt.integer(s.layouts.length - shown.length)}</span>}
          </div>
        </>
      )}
      {s.evidence.length > 0 && (
        <details className="acr-firm-evidence">
          <summary>{t('firm.tpl.evidence')}</summary>
          <ul className="acr-firm-ltr">
            {s.evidence.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
