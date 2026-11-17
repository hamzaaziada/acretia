import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { DragEvent, KeyboardEvent, MouseEvent } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { api } from '../../api/client';
import { useMe } from '../../api/hooks';
import {
  Badge,
  Button,
  Checkbox,
  EmptyState,
  IconAlert,
  IconCheck,
  IconComment,
  IconDiff,
  IconDownload,
  IconLink,
  IconLock,
  IconPlay,
  Input,
  Select,
  Skeleton,
  Textarea,
  cx,
  isTypingTarget,
  useToast,
} from '../../ds';
import type { Tone } from '../../ds';
import { useI18n } from '../../i18n';
import { Compare } from './Compare';
import { citeUrl, deckApi, errText } from './util';
import type { ApplyResult, Approval, DeckComment, DeckPayload, Slide, Status } from './types';
import './deck.css';

const TONE: Record<Status, Tone> = { pass: 'positive', warn: 'warning', fail: 'negative' };
const SEV_STATUS: Record<string, Status> = { critical: 'fail', major: 'warn', minor: 'pass' };

function StatusIcon({ status }: { status: Status }) {
  return status === 'pass' ? <IconCheck size={11} /> : <IconAlert size={11} />;
}

/** The slide as a PNG at the device pixel ratio; without a renderer (or when it fails) a text outline in a slide-shaped box. */
function SlideImage({ deck, slide, dpr, className }: { deck: DeckPayload; slide: Slide; dpr: number; className?: string }) {
  const { t } = useI18n();
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [slide.png_url]);
  if (!deck.renderer.available || failed) {
    return (
      <div className={cx('dk-outline', className)} role="img" aria-label={t('viewers2.deck.slideAlt', { n: slide.n, title: slide.title })}>
        <p className="dk-outline__title">{slide.title}</p>
        <ul>
          {slide.outline.slice(1, 8).map((o, i) => (
            <li key={i}>{o}</li>
          ))}
        </ul>
        <p className="dk-outline__note">{t('viewers2.deck.noRenderer')}</p>
      </div>
    );
  }
  return (
    <img
      className={className}
      src={dpr > 1 ? `${slide.png_url}?dpr=${dpr}` : slide.png_url}
      alt={t('viewers2.deck.slideAlt', { n: slide.n, title: slide.title })}
      draggable={false}
      loading={dpr > 1 ? 'eager' : 'lazy'}
      onError={() => setFailed(true)}
    />
  );
}

function GhostApproval({ approval, onDone }: { approval: Approval; onDone: () => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const initial = approval.payload.titles ?? approval.payload.slides?.map((s) => s.title ?? '') ?? [];
  const [titles, setTitles] = useState<string[]>(initial);
  const [busy, setBusy] = useState(false);
  async function approve() {
    setBusy(true);
    try {
      await api.post(`/jobs/${approval.job_id}/approve`, { step: approval.step_id, payload: { ...approval.payload, titles } });
      toast.push({ kind: 'success', title: t('viewers2.deck.ghostApproved') });
      onDone();
    } catch (e) {
      toast.push({ kind: 'error', ...errText(e) });
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="dk-ghost" data-testid="approval-card" data-kind="ghost_deck" aria-label={t('viewers2.deck.ghostTitle')}>
      <div className="dk-ghost__head">
        <div>
          <h2 className="dk-h2">{t('viewers2.deck.ghostTitle')}</h2>
          <p className="dk-muted">{t('viewers2.deck.ghostBody')}</p>
        </div>
        <Button variant="primary" data-testid="approval-approve" loading={busy} disabled={titles.some((x) => !x.trim())} onClick={() => void approve()}>
          {t('viewers2.deck.ghostApprove')}
        </Button>
      </div>
      <ol className="dk-ghost__list">
        {titles.map((x, i) => (
          <li key={i}>
            <span className="dk-ghost__n acr-num">{i + 1}</span>
            <Input label={t('viewers2.deck.ghostSlide', { n: i + 1 })} hideLabel data-testid="ghost-title-input" value={x} onChange={(e) => setTitles((l) => l.map((v, k) => (k === i ? e.target.value : v)))} />
          </li>
        ))}
      </ol>
    </section>
  );
}

export default function DeckPage() {
  const { id: dealId = '', name: rawName = '' } = useParams<{ id: string; name: string }>();
  const name = decodeURIComponent(rawName);
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const vParam = params.get('v');
  const { t, fmt } = useI18n();
  const toast = useToast();
  const { me } = useMe();
  const canEdit = me?.role !== 'viewer';

  const [deck, setDeck] = useState<DeckPayload | null>(null);
  const [error, setError] = useState<{ title: string; hint?: string } | null>(null);
  const [cur, setCur] = useState(1);
  const [commenting, setCommenting] = useState(false);
  const [draft, setDraft] = useState<{ x: number; y: number; body: string } | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<string | null>(null);
  const [compare, setCompare] = useState(false);
  const [dragFrom, setDragFrom] = useState<number | null>(null);
  const stage = useRef<HTMLDivElement>(null);
  const dpr = Math.min(3, Math.max(1, Math.ceil(typeof window === 'undefined' ? 1 : window.devicePixelRatio || 1)));

  const load = useCallback(async () => {
    try {
      const d = await api.get<DeckPayload>(deckApi(dealId, name), { query: { version: vParam ?? undefined } });
      setDeck(d);
      setError(null);
      setChecked(new Set(d.comments.filter((c) => c.status === 'open').map((c) => c.id)));
    } catch (e) {
      setError(errText(e));
    }
  }, [dealId, name, vParam]);

  useEffect(() => {
    void load();
  }, [load]);

  const latest = deck ? Math.max(...deck.versions.map((v) => v.version)) : 0;
  const isLatest = !deck || deck.version === latest;
  const slide = deck?.slides.find((s) => s.n === cur) ?? deck?.slides[0] ?? null;

  useEffect(() => {
    if (deck && cur > deck.slides.length) setCur(1);
  }, [deck, cur]);

  const go = useCallback((n: number) => setCur((c) => (deck ? Math.max(1, Math.min(deck.slides.length, n === 0 ? c : n)) : c)), [deck]);

  useEffect(() => {
    function onKey(e: globalThis.KeyboardEvent) {
      if (isTypingTarget(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === 'c' && canEdit && isLatest) {
        e.preventDefault();
        setCommenting((v) => !v);
        setDraft(null);
      } else if (e.key === ']') go(cur + 1);
      else if (e.key === '[') go(cur - 1);
      else if (e.key === 'Escape') {
        setCommenting(false);
        setDraft(null);
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [canEdit, isLatest, cur, go]);

  const numbered = useMemo(() => (deck ? [...deck.comments].sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id)).map((c, i) => ({ ...c, no: i + 1 })) : []), [deck]);
  const open = numbered.filter((c) => c.status === 'open');
  const selectedOpen = open.filter((c) => checked.has(c.id));

  function onStageClick(e: MouseEvent<HTMLDivElement>) {
    if (!commenting || !stage.current || (e.target as HTMLElement).closest('.dk-pin, .dk-draft')) return;
    const r = stage.current.getBoundingClientRect();
    setDraft({ x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)), body: '' });
  }

  async function submitComment() {
    if (!draft || !slide || !draft.body.trim()) return;
    setBusy('comment');
    try {
      await api.post(`${deckApi(dealId, name)}/comments`, { slide: slide.n, x: draft.x, y: draft.y, body: draft.body.trim() });
      setDraft(null);
      setCommenting(false);
      await load();
    } catch (e) {
      toast.push({ kind: 'error', ...errText(e) });
    } finally {
      setBusy(null);
    }
  }

  async function deleteComment(id: string) {
    try {
      await api.del(`${deckApi(dealId, name)}/comments/${id}`);
      await load();
    } catch (e) {
      toast.push({ kind: 'error', ...errText(e) });
    }
  }

  async function apply() {
    setBusy('apply');
    try {
      const r = await api.post<ApplyResult>(`${deckApi(dealId, name)}/apply`, { comment_ids: selectedOpen.map((c) => c.id) });
      if (r.version) {
        toast.push({ kind: 'success', title: t('viewers2.deck.applied', { version: r.version, slides: r.slides_changed.join(', ') }), body: t('viewers2.deck.appliedBody') });
        setParams({});
      }
      if (r.jobs.length) {
        const j = r.jobs.find((x) => x.job_id);
        toast.push({
          kind: 'info',
          title: t('viewers2.deck.jobsStarted', { count: r.jobs.length }),
          action: j?.job_id ? { label: t('viewers2.deck.openRun'), onClick: () => nav(`/runs/${j.job_id}`) } : undefined,
        });
      }
      await load();
    } catch (e) {
      toast.push({ kind: 'error', ...errText(e) });
    } finally {
      setBusy(null);
    }
  }

  async function toggleAccept(s: Slide) {
    try {
      if (s.accepted) await api.del(`${deckApi(dealId, name)}/slides/${s.n}/accept`);
      else await api.post(`${deckApi(dealId, name)}/slides/${s.n}/accept`);
      await load();
    } catch (e) {
      toast.push({ kind: 'error', ...errText(e) });
    }
  }

  async function regenerate(s: Slide) {
    setBusy('regen');
    try {
      const r = await api.post<{ job_id: string }>(`${deckApi(dealId, name)}/slides/${s.n}/regenerate`, {});
      toast.push({ kind: 'info', title: t('viewers2.deck.regenStarted', { n: s.n }), action: { label: t('viewers2.deck.openRun'), onClick: () => nav(`/runs/${r.job_id}`) } });
    } catch (e) {
      toast.push({ kind: 'error', ...errText(e) });
    } finally {
      setBusy(null);
    }
  }

  async function reorder(from: number, to: number) {
    if (!deck || from === to || to < 1 || to > deck.slides.length) return;
    const order = deck.slides.map((s) => s.n);
    order.splice(to - 1, 0, order.splice(from - 1, 1)[0]);
    try {
      await api.post(`${deckApi(dealId, name)}/reorder`, { order });
      setCur(to);
      setParams({});
      await load();
    } catch (e) {
      toast.push({ kind: 'error', ...errText(e) });
    }
  }

  function onThumbKey(e: KeyboardEvent<HTMLElement>, n: number) {
    if (!deck) return;
    if (e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown') && canEdit && isLatest) {
      e.preventDefault();
      void reorder(n, n + (e.key === 'ArrowUp' ? -1 : 1));
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const next = Math.max(1, Math.min(deck.slides.length, n + (e.key === 'ArrowUp' ? -1 : 1)));
      setCur(next);
      requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-testid="slide-thumb"][data-n="${next}"]`)?.focus());
    }
  }
  function onThumbDrop(e: DragEvent, to: number) {
    e.preventDefault();
    if (dragFrom != null) void reorder(dragFrom, to);
    setDragFrom(null);
  }

  if (error && !deck) {
    return (
      <div className="dk-page">
        <EmptyState title={error.title} body={error.hint} icon={<IconAlert size={28} />} action={{ label: t('viewers2.common.retry'), onClick: () => void load() }} />
      </div>
    );
  }
  if (!deck || !slide) {
    return (
      <div className="dk-page" aria-busy="true">
        <Skeleton height={28} width="40%" />
        <div className="dk-skel">
          <Skeleton height={420} />
        </div>
      </div>
    );
  }

  const slideComments = numbered.filter((c) => c.slide === slide.n);
  const lockedSlide = slide.accepted;
  return (
    <div className="dk-page" data-testid="deck-view">
      <header className="dk-toolbar">
        <div className="dk-toolbar__title">
          <h1 className="dk-title">{deck.name}</h1>
          <Badge tone={TONE[deck.validator.status]} dot>
            {t(`viewers2.deck.validator.${deck.validator.status}`)}
          </Badge>
          {!isLatest && <Badge tone="warning">{t('viewers2.deck.oldVersion', { version: deck.version })}</Badge>}
        </div>
        <div className="dk-toolbar__tools">
          <Select
            label={t('viewers2.deck.version')}
            hideLabel
            value={String(deck.version)}
            onChange={(e) => setParams(Number(e.target.value) === latest ? {} : { v: e.target.value })}
            options={[...deck.versions].reverse().map((v) => ({ value: String(v.version), label: `v${v.version}${v.note ? ` · ${v.note.slice(0, 40)}` : ''}` }))}
            fieldClassName="dk-versel"
          />
          <Button variant="ghost" icon={<IconDiff size={14} />} data-testid="version-compare-open" disabled={deck.versions.length < 2} onClick={() => setCompare(true)}>
            {t('viewers2.deck.compare')}
          </Button>
          <a className="acr-btn acr-btn--secondary acr-btn--md" data-testid="deck-download" href={deck.download_url} download>
            <IconDownload size={14} />
            <span className="acr-btn__label">{t('viewers2.deck.download')}</span>
          </a>
          {canEdit && isLatest && (
            <Button variant={commenting ? 'primary' : 'secondary'} icon={<IconComment size={14} />} aria-pressed={commenting} onClick={() => { setCommenting((v) => !v); setDraft(null); }}>
              {t('viewers2.deck.commentMode')} <kbd className="acr-kbd">c</kbd>
            </Button>
          )}
        </div>
      </header>

      {deck.approval && canEdit && <GhostApproval approval={deck.approval} onDone={() => void load()} />}

      <div className="dk-layout">
        <nav className="dk-thumbs" aria-label={t('viewers2.deck.slides')}>
          {deck.slides.map((s) => {
            const pins = numbered.filter((c) => c.slide === s.n && c.status === 'open').length;
            return (
              <button
                key={s.key + s.n}
                type="button"
                data-testid="slide-thumb"
                data-n={s.n}
                data-status={s.status}
                aria-current={s.n === slide.n ? 'true' : undefined}
                className={cx('dk-thumb', s.n === slide.n && 'is-on', dragFrom === s.n && 'is-drag')}
                draggable={canEdit && isLatest}
                onClick={() => setCur(s.n)}
                onKeyDown={(e) => onThumbKey(e, s.n)}
                onDragStart={() => setDragFrom(s.n)}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => onThumbDrop(e, s.n)}
                onDragEnd={() => setDragFrom(null)}
                aria-label={t('viewers2.deck.thumbLabel', { n: s.n, title: s.title })}
              >
                <span className="dk-thumb__n acr-num">{s.n}</span>
                <span className="dk-thumb__img">
                  <SlideImage deck={deck} slide={s} dpr={1} />
                </span>
                <span className="dk-thumb__marks">
                  {s.accepted && (
                    <span className="dk-mark is-lock" title={t('viewers2.deck.accepted')}>
                      <IconLock size={11} />
                    </span>
                  )}
                  {s.status !== 'pass' && (
                    <span className={cx('dk-mark', `is-${s.status}`)} title={t(`viewers2.deck.validator.${s.status}`)}>
                      <StatusIcon status={s.status} />
                    </span>
                  )}
                  {pins > 0 && <span className="dk-mark is-pin acr-num">{pins}</span>}
                </span>
              </button>
            );
          })}
        </nav>

        <main className="dk-canvas">
          <div className="dk-canvas__bar">
            <button type="button" className="dk-iconbtn" onClick={() => go(cur - 1)} disabled={cur <= 1} aria-label={t('viewers2.deck.prev')}>
              ‹
            </button>
            <span className="dk-canvas__count acr-num">{t('viewers2.deck.of', { n: slide.n, total: deck.slides.length })}</span>
            <button type="button" className="dk-iconbtn" onClick={() => go(cur + 1)} disabled={cur >= deck.slides.length} aria-label={t('viewers2.deck.next')}>
              ›
            </button>
            <span className="dk-canvas__title">{slide.title}</span>
            {lockedSlide && (
              <Badge tone="accent">
                <IconLock size={11} /> {t('viewers2.deck.accepted')}
              </Badge>
            )}
          </div>
          <div className={cx('dk-stage-wrap', commenting && 'is-commenting')}>
            <div ref={stage} dir="ltr" className="dk-stage" data-testid="slide-canvas" data-slide={slide.n} onClick={onStageClick}>
              <SlideImage deck={deck} slide={slide} dpr={dpr} className="dk-stage__img" />
              {slideComments.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  data-testid="comment-pin"
                  data-id={c.id}
                  data-status={c.status}
                  className={cx('dk-pin', c.status !== 'open' && 'is-done')}
                  style={{ insetInlineStart: `${c.x * 100}%`, insetBlockStart: `${c.y * 100}%` }}
                  aria-label={t('viewers2.deck.pinLabel', { n: c.no, body: c.body })}
                  title={c.body}
                >
                  {c.no}
                </button>
              ))}
              {draft && (
                <div className="dk-draft" style={{ insetInlineStart: `${Math.min(draft.x * 100, 62)}%`, insetBlockStart: `${Math.min(draft.y * 100, 70)}%` }} dir={document.documentElement.dir}>
                  <Textarea
                    label={t('viewers2.deck.commentLabel')}
                    hideLabel
                    data-testid="comment-input"
                    data-autofocus
                    autoFocus
                    rows={3}
                    value={draft.body}
                    placeholder={t('viewers2.deck.commentPlaceholder')}
                    onChange={(e) => setDraft({ ...draft, body: e.target.value })}
                    onKeyDown={(e) => {
                      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') void submitComment();
                      if (e.key === 'Escape') setDraft(null);
                    }}
                  />
                  <p className="dk-muted">{t('viewers2.deck.commentHint')}</p>
                  <div className="dk-draft__foot">
                    <Button size="sm" variant="ghost" onClick={() => setDraft(null)}>
                      {t('viewers2.common.cancel')}
                    </Button>
                    <Button size="sm" variant="primary" data-testid="comment-submit" loading={busy === 'comment'} disabled={!draft.body.trim()} onClick={() => void submitComment()}>
                      {t('viewers2.deck.addComment')}
                    </Button>
                  </div>
                </div>
              )}
            </div>
          </div>
          {commenting && !draft && <p className="dk-hint" role="status">{t('viewers2.deck.clickToPin')}</p>}
        </main>

        <aside className="dk-panel" aria-label={t('viewers2.deck.panel')}>
          <section className="dk-sec">
            <h2 className="dk-h2">{t('viewers2.deck.validator.title')}</h2>
            <ul className="dk-badges">
              {slide.badges.length === 0 && (
                <li className="dk-vbadge is-pass" data-testid="validator-badge" data-status="pass">
                  <IconCheck size={13} />
                  <span>{t('viewers2.deck.validator.clean')}</span>
                </li>
              )}
              {slide.badges.map((b, i) => {
                const st = SEV_STATUS[b.severity] ?? 'warn';
                return (
                  <li key={i} className={cx('dk-vbadge', `is-${st}`)} data-testid="validator-badge" data-status={st}>
                    <StatusIcon status={st} />
                    <span>
                      <strong className="dk-vbadge__rule">{b.rule}</strong> {b.message}
                    </span>
                  </li>
                );
              })}
            </ul>
          </section>

          <section className="dk-sec">
            <h2 className="dk-h2">{t('viewers2.deck.sources')}</h2>
            {slide.sources.length === 0 ? (
              <p className="dk-muted">{t('viewers2.deck.noSources')}</p>
            ) : (
              <ul className="dk-sources">
                {slide.sources.map((s, i) => (
                  <li key={i} className="dk-source" data-testid="slide-source-line">
                    <span>{s.text}</span>
                    {s.citation_token ? (
                      <button
                        type="button"
                        className="dk-chip"
                        data-testid="source-chip"
                        data-cite={s.citation_token}
                        data-token={s.citation_token}
                        onClick={() => nav(citeUrl(dealId, { doc_id: s.doc_id, page: s.page, token: s.citation_token }))}
                      >
                        <IconLink size={11} />
                        {t('viewers2.deck.openSource')}
                      </button>
                    ) : (
                      <span className="dk-muted">{t('viewers2.deck.unlinked')}</span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="dk-sec dk-sec--grow">
            <div className="dk-sec__head">
              <h2 className="dk-h2">{t('viewers2.deck.comments', { count: numbered.length })}</h2>
            </div>
            {numbered.length === 0 ? (
              <p className="dk-muted">{isLatest && canEdit ? t('viewers2.deck.noCommentsHint') : t('viewers2.deck.noComments')}</p>
            ) : (
              <ul className="dk-comments">
                {numbered.map((c: DeckComment & { no: number }) => (
                  <li key={c.id} className={cx('dk-comment', c.slide === slide.n && 'is-here')} data-status={c.status}>
                    {c.status === 'open' && isLatest && canEdit ? (
                      <Checkbox
                        label={t('viewers2.deck.selectComment', { n: c.no })}
                        className="dk-comment__chk"
                        checked={checked.has(c.id)}
                        onChange={(e) => setChecked((s) => { const n = new Set(s); if (e.target.checked) n.add(c.id); else n.delete(c.id); return n; })}
                      />
                    ) : null}
                    <button type="button" className="dk-comment__main" onClick={() => setCur(c.slide)}>
                      <span className="dk-pin dk-pin--static">{c.no}</span>
                      <span className="dk-comment__body">
                        <span className="dk-comment__meta">
                          {t('viewers2.deck.slideN', { n: c.slide })} · {fmt.relative(c.created_at)}
                          {c.status !== 'open' && (
                            <Badge tone={c.status === 'applied' ? 'positive' : 'info'}>{c.status === 'applied' ? t('viewers2.deck.statusApplied', { version: c.applied_in_version ?? '' }) : t('viewers2.deck.statusJob')}</Badge>
                          )}
                        </span>
                        <span>{c.body}</span>
                      </span>
                    </button>
                    {c.status === 'open' && isLatest && canEdit && (
                      <button type="button" className="dk-iconbtn" aria-label={t('viewers2.deck.deleteComment')} onClick={() => void deleteComment(c.id)}>
                        ×
                      </button>
                    )}
                    {c.status === 'job' && c.job_id && (
                      <Link className="dk-chip" to={`/runs/${c.job_id}`}>
                        {t('viewers2.deck.openRun')}
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>

          {canEdit && isLatest && (
            <div className="dk-actions">
              <Button variant="primary" data-testid="apply-comments" loading={busy === 'apply'} disabled={selectedOpen.length === 0} onClick={() => void apply()}>
                {t('viewers2.deck.apply', { count: selectedOpen.length })}
              </Button>
              <div className="dk-actions__row">
                <Button variant="secondary" size="sm" icon={<IconLock size={12} />} data-testid="slide-accept" onClick={() => void toggleAccept(slide)}>
                  {slide.accepted ? t('viewers2.deck.unaccept') : t('viewers2.deck.accept')}
                </Button>
                <Button variant="secondary" size="sm" icon={<IconPlay size={12} />} disabled={lockedSlide} loading={busy === 'regen'} onClick={() => void regenerate(slide)}>
                  {t('viewers2.deck.regenerate')}
                </Button>
              </div>
              <p className="dk-muted">{t('viewers2.deck.applyHint')}</p>
            </div>
          )}
        </aside>
      </div>

      <Compare open={compare} deck={deck} canEdit={canEdit} onClose={() => setCompare(false)} onRolledBack={() => { setParams({}); void load(); }} />
    </div>
  );
}
