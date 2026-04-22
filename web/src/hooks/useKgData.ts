import { useEffect, useState } from 'react';

export interface KgNode {
  article_id: string;
  bwb_id: string;
  label: string;
  title: string;
  body_text: string;
  outgoing_refs: string[];
}

export interface KgEdge {
  from_id: string;
  to_id: string;
  kind: 'explicit' | 'regex';
}

export interface ValidatedKg {
  nodes: KgNode[];
  edges: KgEdge[];
  degree: Map<string, number>;
  rankByDegree: Map<string, number>;
}

export function validateKgData(raw: { nodes: KgNode[]; edges: KgEdge[] }): ValidatedKg {
  const ids = new Set(raw.nodes.map((n) => n.article_id));
  const edges = raw.edges.filter((e) => ids.has(e.from_id) && ids.has(e.to_id));

  const degree = new Map<string, number>();
  for (const n of raw.nodes) degree.set(n.article_id, 0);
  for (const e of edges) {
    degree.set(e.from_id, (degree.get(e.from_id) ?? 0) + 1);
    degree.set(e.to_id, (degree.get(e.to_id) ?? 0) + 1);
  }

  const sorted = [...raw.nodes].sort((a, b) => {
    const dDiff = (degree.get(b.article_id) ?? 0) - (degree.get(a.article_id) ?? 0);
    if (dDiff !== 0) return dDiff;
    return a.article_id.localeCompare(b.article_id);
  });
  const rankByDegree = new Map<string, number>();
  sorted.forEach((n, i) => rankByDegree.set(n.article_id, i));

  return { nodes: raw.nodes, edges, degree, rankByDegree };
}

export type KgDataStatus = 'loading' | 'ready' | 'error';

export function useKgData(): { status: KgDataStatus; data: ValidatedKg | null; retry: () => void } {
  const [status, setStatus] = useState<KgDataStatus>('loading');
  const [data, setData] = useState<ValidatedKg | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setStatus('loading');
    fetch('/api/kg')
      .then((r) => {
        if (!r.ok) throw new Error(`KG fetch failed: ${r.status}`);
        return r.json();
      })
      .then((raw: { nodes: KgNode[]; edges: KgEdge[] }) => {
        if (cancelled) return;
        setData(validateKgData(raw));
        setStatus('ready');
      })
      .catch(() => {
        if (cancelled) return;
        setStatus('error');
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  return { status, data, retry: () => setAttempt((a) => a + 1) };
}
