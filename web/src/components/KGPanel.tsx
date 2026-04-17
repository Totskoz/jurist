import { useEffect, useMemo, useState } from 'react';
import {
  Background,
  Controls,
  ReactFlow,
  type Edge,
  type Node,
} from '@xyflow/react';
import dagre from 'dagre';
import { useRunStore } from '../state/runStore';

interface KgArticle {
  article_id: string;
  bwb_id: string;
  label: string;
  title: string;
  body_text: string;
  outgoing_refs: string[];
}
interface KgEdge {
  from_id: string;
  to_id: string;
  kind: 'explicit' | 'regex';
}

const NODE_W = 220;
const NODE_H = 64;

function layout(nodes: KgArticle[], edges: KgEdge[]): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'LR', nodesep: 30, ranksep: 60 });
  g.setDefaultEdgeLabel(() => ({}));
  for (const n of nodes) g.setNode(n.article_id, { width: NODE_W, height: NODE_H });
  for (const e of edges) g.setEdge(e.from_id, e.to_id);
  dagre.layout(g);

  const rfNodes: Node[] = nodes.map((n) => {
    const pos = g.node(n.article_id);
    return {
      id: n.article_id,
      position: { x: pos.x - NODE_W / 2, y: pos.y - NODE_H / 2 },
      data: { label: n.label, title: n.title },
      type: 'default',
      style: { width: NODE_W, height: NODE_H, padding: 8, fontSize: 12 },
    };
  });
  const rfEdges: Edge[] = edges.map((e) => ({
    id: `${e.from_id}__${e.to_id}`,
    source: e.from_id,
    target: e.to_id,
    animated: false,
  }));
  return { nodes: rfNodes, edges: rfEdges };
}

const stateStyle = {
  default: { background: '#fff', border: '1px solid #d1d5db' },
  current: { background: '#fde68a', border: '2px solid #d97706' },
  visited: { background: '#e5e7eb', border: '1px solid #6b7280' },
  cited: { background: '#bbf7d0', border: '2px solid #047857' },
} as const;

export default function KGPanel() {
  const [base, setBase] = useState<{ nodes: Node[]; edges: Edge[] } | null>(null);
  const kgState = useRunStore((s) => s.kgState);
  const edgeState = useRunStore((s) => s.edgeState);

  useEffect(() => {
    void fetch('/api/kg')
      .then((r) => r.json())
      .then((d: { nodes: KgArticle[]; edges: KgEdge[] }) => setBase(layout(d.nodes, d.edges)));
  }, []);

  const rfNodes = useMemo(() => {
    if (!base) return [];
    return base.nodes.map((n) => {
      const st = kgState.get(n.id) ?? 'default';
      return { ...n, style: { ...(n.style as object), ...stateStyle[st], transition: 'all 300ms' } };
    });
  }, [base, kgState]);

  const rfEdges = useMemo(() => {
    if (!base) return [];
    return base.edges.map((e) => {
      const traversed = edgeState.get(`${e.source}::${e.target}`) === 'traversed';
      return {
        ...e,
        animated: traversed,
        style: { stroke: traversed ? '#047857' : '#9ca3af', strokeWidth: traversed ? 2 : 1 },
      };
    });
  }, [base, edgeState]);

  if (!base) {
    return <div className="p-4 text-gray-500">Loading KG…</div>;
  }
  return (
    <div className="h-full w-full border rounded">
      <ReactFlow nodes={rfNodes} edges={rfEdges} fitView>
        <Background />
        <Controls />
      </ReactFlow>
    </div>
  );
}
