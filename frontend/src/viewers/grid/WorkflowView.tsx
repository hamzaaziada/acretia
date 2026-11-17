import { useEffect, useMemo, useState } from 'react';
import { api } from '../../api/client';
import { Dialog, useToast } from '../../ds';
import { useT } from '../../i18n';
import { errText } from './common';
import type { WorkflowEdge, WorkflowNode } from './types';

interface Props {
  open: boolean;
  gridId: string;
  version: number;
  onClose: () => void;
}

const NW = 176;
const NH = 46;
const GX = 92;
const GY = 22;

/** Column dependency graph as an SVG DAG: inputs, then the columns that read them, level by level (parity item 6). */
export function WorkflowView({ open, gridId, version, onClose }: Props) {
  const t = useT();
  const toast = useToast();
  const [data, setData] = useState<{ nodes: WorkflowNode[]; edges: WorkflowEdge[] } | null>(null);

  useEffect(() => {
    if (!open) return;
    api.get<{ nodes: WorkflowNode[]; edges: WorkflowEdge[] }>(`/grids/${gridId}/workflow`).then(setData).catch((e) => toast.push({ kind: 'error', ...errText(e) }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, gridId, version]);

  const rtl = typeof document !== 'undefined' && document.documentElement.dir === 'rtl';
  const layout = useMemo(() => {
    if (!data) return null;
    const levels = new Map<number, WorkflowNode[]>();
    for (const n of data.nodes) levels.set(n.level ?? 1, [...(levels.get(n.level ?? 1) ?? []), n]);
    const maxLevel = Math.max(0, ...levels.keys());
    const rows = Math.max(1, ...[...levels.values()].map((l) => l.length));
    const W = (maxLevel + 1) * NW + maxLevel * GX + 32;
    const H = rows * NH + (rows - 1) * GY + 32;
    const pos = new Map<string, { x: number; y: number }>();
    for (const [lv, list] of levels) {
      const colH = list.length * NH + (list.length - 1) * GY;
      list.forEach((n, i) => {
        const x0 = 16 + lv * (NW + GX);
        pos.set(n.id, { x: rtl ? W - x0 - NW : x0, y: 16 + (H - 32 - colH) / 2 + i * (NH + GY) });
      });
    }
    return { W, H, pos };
  }, [data, rtl]);

  const label = (id: string) => data?.nodes.find((n) => n.id === id)?.label ?? id;
  return (
    <Dialog open={open} onClose={onClose} size="lg" title={t('viewers2.workflow.title')} closeLabel={t('viewers2.common.close')} description={t('viewers2.workflow.desc')}>
      <div data-testid="workflow-view" className="vw-workflow">
        {data && data.edges.length === 0 && <p className="vw-muted">{t('viewers2.workflow.none')}</p>}
        {layout && data && (
          <div className="vw-workflow__scroll">
            <svg width={layout.W} height={layout.H} viewBox={`0 0 ${layout.W} ${layout.H}`} role="img" aria-label={t('viewers2.workflow.title')}>
              <defs>
                <marker id="vw-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                  <path d="M0 0L10 5L0 10z" className="vw-wf__arrow" />
                </marker>
              </defs>
              {data.edges.map((e, i) => {
                const a = layout.pos.get(e.from);
                const b = layout.pos.get(e.to);
                if (!a || !b) return null;
                const ax = rtl ? a.x : a.x + NW;
                const bx = rtl ? b.x + NW : b.x;
                const ay = a.y + NH / 2;
                const by = b.y + NH / 2;
                const dx = (bx - ax) / 2;
                return <path key={i} d={`M${ax} ${ay} C${ax + dx} ${ay} ${bx - dx} ${by} ${bx} ${by}`} className={`vw-wf__edge is-${e.kind}`} markerEnd="url(#vw-arrow)" fill="none" />;
              })}
              {data.nodes.map((n) => {
                const p = layout.pos.get(n.id)!;
                return (
                  <g key={n.id} transform={`translate(${p.x} ${p.y})`} className={`vw-wf__node is-${n.kind}`}>
                    <rect width={NW} height={NH} rx={6} />
                    <text x={NW / 2} y={NH / 2 - 3} textAnchor="middle" className="vw-wf__label">
                      {n.label.length > 22 ? `${n.label.slice(0, 21)}…` : n.label}
                    </text>
                    <text x={NW / 2} y={NH / 2 + 12} textAnchor="middle" className="vw-wf__sub">
                      {n.kind === 'input' ? t('viewers2.workflow.input') : t(`viewers2.grid.type.${n.type ?? 'text'}`)}
                    </text>
                  </g>
                );
              })}
            </svg>
          </div>
        )}
        {data && data.edges.length > 0 && (
          <ul className="acr-sr-only" aria-label={t('viewers2.workflow.title')}>
            {data.edges.map((e, i) => (
              <li key={i}>{t('viewers2.workflow.edge', { from: label(e.from), to: label(e.to), kind: t(`viewers2.workflow.kind.${e.kind}`) })}</li>
            ))}
          </ul>
        )}
        <div className="vw-workflow__legend" aria-hidden="true">
          <span className="vw-leg is-reference">{t('viewers2.workflow.kind.reference')}</span>
          <span className="vw-leg is-condition">{t('viewers2.workflow.kind.condition')}</span>
          <span className="vw-leg is-input">{t('viewers2.workflow.kind.input')}</span>
        </div>
      </div>
    </Dialog>
  );
}
