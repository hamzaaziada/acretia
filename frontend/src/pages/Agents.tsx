import { useMemo, useState } from 'react';
import type { FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { Badge, Button, Checkbox, Dialog, EmptyState, IconAgent, IconButton, IconChevronDown, IconChevronUp, IconPin, IconPlay, IconPlus, IconSearch, IconX, Input, PageHeader, Select, SkeletonRows, Textarea, useToast, cx } from '../ds';
import { api } from '../api/client';
import { useDeals, useMe } from '../api/hooks';
import type { Agent, JobEnvelope } from '../api/types';
import { useI18n } from '../i18n';
import { errorToast, useAgents } from '../app/lib';

export default function Agents() {
  const { t } = useI18n();
  const { me } = useMe();
  const toast = useToast();
  const agents = useAgents();
  const [q, setQ] = useState('');
  const [tag, setTag] = useState('');
  const [runTarget, setRunTarget] = useState<Agent | null>(null);
  const [creating, setCreating] = useState(false);
  const owner = me?.role === 'owner';

  const all = agents.data ?? [];
  const tags = useMemo(() => Array.from(new Set(all.flatMap((a) => a.tags ?? []))).sort(), [all]);
  const rows = useMemo(() => {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    return all
      .filter((a) => (!tag || (a.tags ?? []).includes(tag)) && words.every((w) => `${a.name} ${a.description} ${(a.tags ?? []).join(' ')}`.toLowerCase().includes(w)))
      .sort((a, b) => Number(b.pinned === true) - Number(a.pinned === true) || a.name.localeCompare(b.name));
  }, [all, q, tag]);

  /** POST /agents/{id}/pin {pinned} keeps pins per user on the server, so they follow the person across browsers. */
  async function togglePin(a: Agent) {
    try {
      await api.post(`/agents/${a.id}/pin`, { pinned: a.pinned !== true });
      agents.reload();
    } catch (e) {
      toast.push(errorToast(e, t('agents.pinFailed')));
    }
  }
  async function toggleEnabled(a: Agent) {
    const enabled = a.enabled === false;
    try {
      // Owner-only org-wide switch: POST /agents/{id}/enabled {enabled}.
      await api.post(`/agents/${a.id}/enabled`, { enabled });
      agents.reload();
      toast.push({ kind: 'success', title: t(enabled ? 'agents.enabledToast' : 'agents.disabledToast', { name: a.name }) });
    } catch (e) {
      toast.push(errorToast(e, t('agents.toggleFailed')));
    }
  }

  return (
    <div className="acr-page">
      <PageHeader
        title={t('nav.agents')}
        subtitle={t('agents.subtitle')}
        actions={
          <Button variant="primary" icon={<IconPlus size={14} />} data-testid="new-agent" onClick={() => setCreating(true)}>
            {t('agents.new')}
          </Button>
        }
      />
      <div className="acr-toolbar">
        <Input hideLabel label={t('agents.search')} placeholder={t('agents.search')} startSlot={<IconSearch size={14} />} value={q} onChange={(e) => setQ(e.target.value)} fieldClassName="acr-toolbar__search" data-testid="agents-search" />
        <div className="acr-row acr-wrap" role="group" aria-label={t('agents.tags')}>
          {tags.map((x) => (
            <button key={x} type="button" className="acr-chip" aria-pressed={tag === x} onClick={() => setTag(tag === x ? '' : x)}>
              {x}
            </button>
          ))}
        </div>
      </div>
      {agents.loading && !agents.data ? (
        <SkeletonRows rows={6} label={t('common.loading')} />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<IconAgent size={22} />}
          title={all.length === 0 ? t('agents.empty.title') : t('agents.noMatch')}
          body={all.length === 0 ? t('agents.empty.body') : t('agents.noMatchBody')}
          action={all.length === 0 ? { label: t('agents.new'), onClick: () => setCreating(true) } : { label: t('common.clear'), onClick: () => { setQ(''); setTag(''); } }}
        />
      ) : (
        <ul className="acr-agentgrid">
          {rows.map((a) => {
            const pinned = a.pinned === true;
            const disabled = a.enabled === false;
            return (
              <li key={a.id} className={cx('acr-agent', disabled && 'is-disabled')} data-testid="agent-card" data-id={a.id} data-agent={a.task_id ?? (a.builtin ? a.kind : a.id)}>
                <div className="acr-agent__head">
                  <h2 className="acr-agent__name">{a.name}</h2>
                  <IconButton aria-label={pinned ? t('agents.unpin', { name: a.name }) : t('agents.pin', { name: a.name })} aria-pressed={pinned} className={cx(pinned && 'is-on')} data-testid="agent-pin" onClick={() => togglePin(a)}>
                    <IconPin size={14} />
                  </IconButton>
                </div>
                <p className="acr-agent__desc">{a.description}</p>
                <div className="acr-row acr-wrap">
                  {a.builtin ? <Badge tone="info">{t('agents.builtin')}</Badge> : a.shared ? <Badge tone="accent">{t('agents.shared')}</Badge> : <Badge>{t('agents.private')}</Badge>}
                  {disabled && <Badge tone="warning">{t('agents.disabled')}</Badge>}
                  {(a.tags ?? []).map((x) => (
                    <Badge key={x}>{x}</Badge>
                  ))}
                </div>
                <div className="acr-agent__foot">
                  {owner && (
                    <Checkbox label={t('agents.enabled')} checked={!disabled} data-testid="agent-enabled-toggle" onChange={() => toggleEnabled(a)} />
                  )}
                  <span className="acr-spacer-flex" />
                  <Button size="sm" variant="primary" icon={<IconPlay size={12} />} disabled={disabled} data-testid="agent-run" onClick={() => setRunTarget(a)}>
                    {t('agents.run')}
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      <RunDialog agent={runTarget} onClose={() => setRunTarget(null)} />
      <NewAgentDialog open={creating} onClose={() => setCreating(false)} onSaved={agents.reload} />
    </div>
  );
}

function RunDialog({ agent, onClose }: { agent: Agent | null; onClose: () => void }) {
  const { t } = useI18n();
  const nav = useNavigate();
  const toast = useToast();
  const deals = useDeals();
  const [prompt, setPrompt] = useState('');
  const [dealId, setDealId] = useState('');
  const [busy, setBusy] = useState(false);
  const [seed, setSeed] = useState<string | null>(null);
  if (agent && seed !== agent.id) {
    setSeed(agent.id);
    setPrompt(agent.prompt ?? agent.prompts?.[0] ?? '');
    setBusy(false);
  }
  if (!agent && seed) setSeed(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!agent) return;
    setBusy(true);
    try {
      const job = (await api.post<JobEnvelope>(`/agents/${agent.id}/run`, { prompt: prompt.trim(), deal_id: dealId || null })).job;
      onClose();
      nav(`/runs/${job.id}`);
    } catch (x) {
      setBusy(false);
      toast.push(errorToast(x, t('agents.runFailed')));
    }
  }
  return (
    <Dialog
      open={agent !== null}
      onClose={onClose}
      title={agent ? t('agents.runTitle', { name: agent.name }) : ''}
      description={agent?.description}
      closeLabel={t('common.close')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button variant="primary" type="submit" form="run-agent-form" loading={busy}>
            {t('agents.run')}
          </Button>
        </>
      }
    >
      <form id="run-agent-form" className="acr-stack" onSubmit={submit}>
        <Select
          label={t('ask.deal')}
          value={dealId}
          onChange={(e) => setDealId(e.target.value)}
          options={[{ value: '', label: t('ask.noDeal') }, ...(deals.data ?? []).map((d) => ({ value: d.id, label: d.name }))]}
        />
        <Textarea label={t('agents.prompt')} hint={t('agents.promptHint')} rows={4} value={prompt} onChange={(e) => setPrompt(e.target.value)} data-autofocus />
      </form>
    </Dialog>
  );
}

function NewAgentDialog({ open, onClose, onSaved }: { open: boolean; onClose: () => void; onSaved: () => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [chain, setChain] = useState<Array<{ k: number; v: string }>>([{ k: 0, v: '' }]);
  const [next, setNext] = useState(1);
  const [shared, setShared] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  function reset() {
    setName('');
    setDescription('');
    setChain([{ k: 0, v: '' }]);
    setNext(1);
    setShared(false);
    setErr('');
    setBusy(false);
  }
  function move(i: number, d: -1 | 1) {
    setChain((l) => {
      const j = i + d;
      if (j < 0 || j >= l.length) return l;
      const c = [...l];
      [c[i], c[j]] = [c[j], c[i]];
      return c;
    });
  }
  async function submit(e: FormEvent) {
    e.preventDefault();
    const prompts = chain.map((c) => c.v.trim()).filter(Boolean);
    if (!name.trim()) return setErr(t('agents.new.nameRequired'));
    if (prompts.length === 0) return setErr(t('agents.new.promptRequired'));
    setBusy(true);
    try {
      // One prompt is a "prompt" agent, several are a "chain" run in order (SPEC section 5).
      await api.post('/agents', {
        name: name.trim(),
        description: description.trim(),
        ...(prompts.length === 1 ? { kind: 'prompt', prompt: prompts[0] } : { kind: 'chain', prompts }),
        shared,
      });
      toast.push({ kind: 'success', title: t('agents.new.saved', { name: name.trim() }) });
      onSaved();
      onClose();
      reset();
    } catch (x) {
      setBusy(false);
      toast.push(errorToast(x, t('agents.new.failed')));
    }
  }
  return (
    <Dialog
      open={open}
      onClose={() => {
        onClose();
        reset();
      }}
      title={t('agents.new')}
      description={t('agents.new.desc')}
      closeLabel={t('common.close')}
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={() => { onClose(); reset(); }}>
            {t('common.cancel')}
          </Button>
          <Button variant="primary" type="submit" form="new-agent-form" loading={busy} data-testid="agent-save">
            {t('common.save')}
          </Button>
        </>
      }
    >
      <form id="new-agent-form" className="acr-stack" onSubmit={submit} noValidate>
        {err && (
          <div className="acr-formerror" role="alert">
            <strong>{err}</strong>
          </div>
        )}
        <Input label={t('agents.name')} value={name} onChange={(e) => setName(e.target.value)} data-testid="agent-name" data-autofocus required />
        <Input label={t('agents.description')} hint={t('agents.descriptionHint')} value={description} onChange={(e) => setDescription(e.target.value)} />
        <div className="acr-stack" data-testid="agent-prompts" role="group" aria-label={t('agents.chain')}>
          <div className="acr-section-label">{t('agents.chain')}</div>
          {chain.map((c, i) => (
            <div key={c.k} className="acr-chainrow">
              <span className="acr-approval__n acr-num">{i + 1}</span>
              <Textarea hideLabel label={t('agents.chainStep', { n: i + 1 })} rows={2} value={c.v} fieldClassName="acr-spacer-flex" placeholder={t('agents.chainPlaceholder')} onChange={(e) => setChain((l) => l.map((x) => (x.k === c.k ? { ...x, v: e.target.value } : x)))} />
              <div className="acr-chainrow__btns">
                <IconButton size="sm" aria-label={t('approval.moveUp')} disabled={i === 0} onClick={() => move(i, -1)}>
                  <IconChevronUp size={14} />
                </IconButton>
                <IconButton size="sm" aria-label={t('approval.moveDown')} disabled={i === chain.length - 1} onClick={() => move(i, 1)}>
                  <IconChevronDown size={14} />
                </IconButton>
                <IconButton size="sm" aria-label={t('approval.remove')} disabled={chain.length === 1} onClick={() => setChain((l) => l.filter((x) => x.k !== c.k))}>
                  <IconX size={14} />
                </IconButton>
              </div>
            </div>
          ))}
          <div>
            <Button
              size="sm"
              variant="secondary"
              icon={<IconPlus size={13} />}
              onClick={() => {
                setChain((l) => [...l, { k: next, v: '' }]);
                setNext((n) => n + 1);
              }}
            >
              {t('agents.addStep')}
            </Button>
          </div>
        </div>
        <Checkbox label={t('agents.shareToggle')} hint={t('agents.shareHint')} checked={shared} onChange={(e) => setShared(e.target.checked)} data-testid="agent-shared" />
      </form>
    </Dialog>
  );
}
