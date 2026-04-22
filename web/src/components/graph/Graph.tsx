import { useEffect, useMemo, useRef, useState } from 'react';
// eslint-disable-next-line @typescript-eslint/no-explicit-any
import ForceGraph2D from 'react-force-graph-2d';
// @ts-expect-error — transitive dep shipped with react-force-graph-2d; no bundled types
import { forceCenter, forceX, forceY } from 'd3-force-3d';
import { useRunStore } from '../../state/runStore';
import { useKgData } from '../../hooks/useKgData';
import { clusterOf, shortLabelFor } from './clusters';
import { FORCE_CONFIG } from './forceConfig';
import { drawNode, type RenderableNode } from './nodeRender';
import { drawEdge, type RenderableEdge } from './edgeRender';
import type { ClusterKey } from '../../theme';
import type { EdgeState, NodeState } from '../../state/runStore';
import NodeTooltip from './NodeTooltip';

interface GraphNode {
  id: string;
  bwb_id: string;
  cluster: ClusterKey;
  degree: number;
  rank: number;
  label: string;
  title: string;
  isBookRoot?: boolean;
}

interface GraphLink {
  source: string;
  target: string;
  targetCluster: ClusterKey;
}

// Book-level clustering: pull BW articles left, Uhw articles right.
const BW_BWB = 'BWBR0005290';
const UHW_BWB = 'BWBR0014315';
const BOOK_ROOT_ID: Record<string, string> = {
  [BW_BWB]: '__book__BW',
  [UHW_BWB]: '__book__UHW',
};
const BOOK_ROOT_LABEL: Record<string, string> = {
  __book__BW: 'BW — Boek 7',
  __book__UHW: 'Uhw',
};
const BOOK_ROOT_TITLE: Record<string, string> = {
  __book__BW: 'Burgerlijk Wetboek, Boek 7 (Huur)',
  __book__UHW: 'Uitvoeringswet huurcommissie',
};
// Tuned for two clusters filling the screen side-by-side.
const BOOK_X_STRENGTH = 0.22;
const BOOK_Y_STRENGTH = 0.18;
// Visual area excludes the 560px right panel + 16px margin.
const PANEL_RESERVE = 560 + 32;

// Edge sweeps in-flight: key = "from::to", value = start-timestamp (ms).
const SWEEP_DURATION_MS = 200;
const SWEEP_THROTTLE_MS = 80;

export default function Graph() {
  const { status, data, retry } = useKgData();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const fgRef = useRef<any>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState(() => ({
    w: typeof window !== 'undefined' ? window.innerWidth : 0,
    h: typeof window !== 'undefined' ? window.innerHeight : 0,
  }));
  const [hover, setHover] = useState<{ label: string; title: string; x: number; y: number } | null>(null);

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
    const articleNodes: GraphNode[] = data.nodes.map((n) => {
      const cl = clusterOf(n);
      nodeMap.set(n.article_id, cl);
      return {
        id: n.article_id,
        bwb_id: n.bwb_id,
        cluster: cl,
        degree: data.degree.get(n.article_id) ?? 0,
        rank: data.rankByDegree.get(n.article_id) ?? 999,
        label: shortLabelFor(n),
        title: n.title,
      };
    });

    // Synthetic book root nodes — one per bwb_id present in the corpus.
    const bookBwbs = new Set(articleNodes.map((n) => n.bwb_id));
    const bookNodes: GraphNode[] = Array.from(bookBwbs)
      .filter((bwb) => BOOK_ROOT_ID[bwb])
      .map((bwb) => ({
        id: BOOK_ROOT_ID[bwb],
        bwb_id: bwb,
        cluster: 'overig' as ClusterKey,
        degree: 0,
        rank: 0,
        label: BOOK_ROOT_LABEL[BOOK_ROOT_ID[bwb]],
        title: BOOK_ROOT_TITLE[BOOK_ROOT_ID[bwb]],
        isBookRoot: true,
      }));

    const articleLinks: GraphLink[] = data.edges.map((e) => ({
      source: e.from_id,
      target: e.to_id,
      targetCluster: nodeMap.get(e.to_id) ?? 'overig',
    }));

    // Synthetic article→book edges so each article is attracted to its book root.
    const bookLinks: GraphLink[] = articleNodes
      .filter((n) => BOOK_ROOT_ID[n.bwb_id])
      .map((n) => ({
        source: n.id,
        target: BOOK_ROOT_ID[n.bwb_id],
        targetCluster: 'overig' as ClusterKey,
      }));

    return {
      nodes: [...articleNodes, ...bookNodes],
      links: [...articleLinks, ...bookLinks],
    };
  }, [data]);

  // Wire book-based x-clustering: BW left, Uhw right. Shift the whole simulation
  // leftward so the two clusters are visually centered in the area the side panel
  // leaves open. Strong y-centering keeps both clusters on the horizontal midline.
  useEffect(() => {
    if (!fgRef.current || !data || size.w === 0) return;
    // Cluster separation — each cluster sits ±this offset from the effective centerline.
    const clusterOffset = Math.min(size.w * 0.13, 360);
    const effectiveCenterX = -PANEL_RESERVE / 2;
    const leftX = effectiveCenterX - clusterOffset;
    const rightX = effectiveCenterX + clusterOffset;

    // Shift the built-in center force leftward so the whole simulation lives in
    // the open area instead of straddling the panel.
    fgRef.current.d3Force('center', forceCenter(effectiveCenterX, 0));

    fgRef.current.d3Force(
      'book-x',
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      forceX((node: any) => (node.bwb_id === BW_BWB ? leftX : rightX)).strength(BOOK_X_STRENGTH),
    );
    fgRef.current.d3Force('book-y', forceY(0).strength(BOOK_Y_STRENGTH));

    // Stronger repulsion + longer links → each cluster fills more space.
    const charge = fgRef.current.d3Force('charge');
    if (charge) charge.strength(-340);
    const linkF = fgRef.current.d3Force('link');
    if (linkF) {
      linkF.distance((l: { source: { isBookRoot?: boolean }; target: { isBookRoot?: boolean } }) =>
        l.source?.isBookRoot || l.target?.isBookRoot ? 140 : 70,
      );
      linkF.strength((l: { source: { isBookRoot?: boolean }; target: { isBookRoot?: boolean } }) =>
        l.source?.isBookRoot || l.target?.isBookRoot ? 0.08 : 0.32,
      );
    }
    // Reheat so the new forces take effect immediately instead of waiting for alpha decay.
    fgRef.current.d3ReheatSimulation?.();
  }, [data, size.w]);

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
    <div
      ref={containerRef}
      onMouseMove={(e) => {
        if (hover) setHover((h) => (h ? { ...h, x: e.clientX, y: e.clientY } : null));
      }}
      style={{ position: 'fixed', inset: 0, background: 'transparent' }}
    >
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
            isBookRoot: node.isBookRoot,
            totalNodes,
          };
          drawNode(renderable, ctx, globalScale, pulseRef.current);
        }}
        nodePointerAreaPaint={(node: any, paintColor, ctx) => {
          // Hit-test area — matches the visual radius with a padding floor so even
          // the smallest nodes are easy to click. Book roots use their bigger radius.
          ctx.fillStyle = paintColor;
          ctx.beginPath();
          const r = node.isBookRoot ? 36 : Math.max(12, 6 + 3 * Math.sqrt(node.degree) + 4);
          ctx.arc(node.x, node.y, r, 0, Math.PI * 2);
          ctx.fill();
        }}
        onNodeClick={(node: any) => {
          // Ignore clicks on synthetic book roots.
          if (node.isBookRoot) return;
          inspectNode(node.id);
        }}
        onNodeHover={(node: any, _prev: any) => {
          if (node) {
            setHover({ label: node.label, title: node.title, x: 0, y: 0 });
          } else {
            setHover(null);
          }
        }}
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
      {hover && <NodeTooltip label={hover.label} title={hover.title} x={hover.x} y={hover.y} />}
    </div>
  );
}
