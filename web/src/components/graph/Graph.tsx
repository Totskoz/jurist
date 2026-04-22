import { useEffect, useMemo, useRef, useState } from 'react';
// eslint-disable-next-line @typescript-eslint/no-explicit-any
import ForceGraph2D from 'react-force-graph-2d';
import { useRunStore } from '../../state/runStore';
import { useKgData } from '../../hooks/useKgData';
import { clusterOf, shortLabelFor } from './clusters';
import { FORCE_CONFIG } from './forceConfig';
import { drawNode, type RenderableNode } from './nodeRender';
import { drawEdge, type RenderableEdge } from './edgeRender';
import type { ClusterKey } from '../../theme';
import type { EdgeState, NodeState } from '../../state/runStore';

interface GraphNode {
  id: string;
  cluster: ClusterKey;
  degree: number;
  rank: number;
  label: string;
  title: string;
}

interface GraphLink {
  source: string;
  target: string;
  targetCluster: ClusterKey;
}

// Edge sweeps in-flight: key = "from::to", value = start-timestamp (ms).
const SWEEP_DURATION_MS = 200;
const SWEEP_THROTTLE_MS = 80;

export default function Graph() {
  const { status, data, retry } = useKgData();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const fgRef = useRef<any>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });

  // Subscribe narrowly.
  const kgState = useRunStore((s) => s.kgState);
  const edgeState = useRunStore((s) => s.edgeState);
  const inspectedNode = useRunStore((s) => s.inspectedNode);
  const inspectNode = useRunStore((s) => s.inspectNode);

  // Active sweeps: key = "from::to", value = start-timestamp (ms).
  const sweeps = useRef<Map<string, number>>(new Map());
  // Queue of edge keys waiting to start sweeping (throttled by SWEEP_THROTTLE_MS).
  const sweepQueue = useRef<string[]>([]);
  const lastSweepStart = useRef<number>(0);
  const prevEdgeState = useRef<typeof edgeState>(new Map());

  // Enqueue a sweep whenever an edge transitions to "traversed".
  useEffect(() => {
    for (const [k, v] of edgeState) {
      if (v === 'traversed' && prevEdgeState.current.get(k) !== 'traversed') {
        if (!sweeps.current.has(k) && !sweepQueue.current.includes(k)) {
          sweepQueue.current.push(k);
        }
      }
    }
    prevEdgeState.current = edgeState;
  }, [edgeState]);

  // Animate pulse + sweep queue via rAF.
  const pulseRef = useRef(0);
  useEffect(() => {
    let frameId = 0;
    const tick = () => {
      const now = performance.now();
      pulseRef.current = (now / 666) % 1; // 1.5 Hz

      // Pop queue at most one per SWEEP_THROTTLE_MS.
      while (sweepQueue.current.length > 0 && now - lastSweepStart.current >= SWEEP_THROTTLE_MS) {
        const key = sweepQueue.current.shift()!;
        sweeps.current.set(key, now);
        lastSweepStart.current = now;
      }

      // Clean up expired sweeps.
      for (const [k, start] of sweeps.current) {
        if (now - start >= SWEEP_DURATION_MS) sweeps.current.delete(k);
      }

      fgRef.current?.refresh();
      frameId = requestAnimationFrame(tick);
    };
    frameId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frameId);
  }, []);

  // Resize observer for full-viewport sizing.
  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver((entries) => {
      const rect = entries[0].contentRect;
      setSize({ w: rect.width, h: rect.height });
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  const graphData = useMemo(() => {
    if (!data) return { nodes: [], links: [] };
    const nodeMap = new Map<string, ClusterKey>();
    const nodes: GraphNode[] = data.nodes.map((n) => {
      const cl = clusterOf(n);
      nodeMap.set(n.article_id, cl);
      return {
        id: n.article_id,
        cluster: cl,
        degree: data.degree.get(n.article_id) ?? 0,
        rank: data.rankByDegree.get(n.article_id) ?? 999,
        label: shortLabelFor(n),
        title: n.title,
      };
    });
    const links: GraphLink[] = data.edges.map((e) => ({
      source: e.from_id,
      target: e.to_id,
      targetCluster: nodeMap.get(e.to_id) ?? 'overig',
    }));
    return { nodes, links };
  }, [data]);

  if (status === 'loading') {
    return <div style={{ color: 'var(--text-secondary)', padding: 24 }}>Kennisgraaf laden…</div>;
  }
  if (status === 'error' || !data) {
    return (
      <div style={{ color: 'var(--text-primary)', padding: 24, textAlign: 'center' }}>
        <p style={{ marginBottom: 12 }}>Kon de kennisgraaf niet laden.</p>
        <button onClick={retry} style={{
          padding: '8px 16px',
          background: 'var(--accent)',
          color: '#000',
          border: 'none',
          borderRadius: 6,
          cursor: 'pointer',
        }}>Opnieuw proberen</button>
      </div>
    );
  }

  const totalNodes = graphData.nodes.length;

  return (
    <div ref={containerRef} style={{ position: 'fixed', inset: 0, background: 'transparent' }}>
      <ForceGraph2D
        ref={fgRef}
        graphData={graphData as any}
        width={size.w}
        height={size.h}
        cooldownTicks={FORCE_CONFIG.cooldownTicks}
        d3AlphaDecay={0.02}
        linkDirectionalArrowLength={0}
        enableNodeDrag={false}
        backgroundColor="rgba(0,0,0,0)"
        nodeRelSize={1}
        linkCanvasObjectMode={() => 'replace'}
        nodeCanvasObject={(node: any, ctx, globalScale) => {
          const state: NodeState = kgState.get(node.id) ?? 'default';
          const renderable: RenderableNode = {
            article_id: node.id,
            cluster: node.cluster,
            degree: node.degree,
            rank: node.rank,
            label: node.label,
            state,
            x: node.x,
            y: node.y,
            isInspected: inspectedNode === node.id,
            totalNodes,
          };
          drawNode(renderable, ctx, globalScale, pulseRef.current);
        }}
        nodePointerAreaPaint={(node: any, paintColor, ctx) => {
          // Hit-test area — larger than visual for easier clicking.
          ctx.fillStyle = paintColor;
          ctx.beginPath();
          ctx.arc(node.x, node.y, Math.max(8, 4 + 1.8 * Math.sqrt(node.degree)), 0, Math.PI * 2);
          ctx.fill();
        }}
        onNodeClick={(node: any) => inspectNode(node.id)}
        linkCanvasObject={(link: any, ctx, globalScale) => {
          const key = `${link.source.id ?? link.source}::${link.target.id ?? link.target}`;
          const state: EdgeState = edgeState.get(key) ?? 'default';
          const sweepStart = sweeps.current.get(key);
          const sweepProgress = sweepStart ? Math.min(1, (performance.now() - sweepStart) / SWEEP_DURATION_MS) : 0;
          const renderable: RenderableEdge = {
            source: link.source,
            target: link.target,
            targetCluster: link.targetCluster,
            state,
            sweepProgress,
          };
          drawEdge(renderable, ctx, globalScale);
        }}
      />
    </div>
  );
}
