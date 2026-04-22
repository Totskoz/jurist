import { clusterColor, color, type ClusterKey } from '../../theme';
import type { EdgeState } from '../../state/runStore';

export interface RenderableEdge {
  source: { x?: number; y?: number };
  target: { x?: number; y?: number };
  targetCluster: ClusterKey;
  state: EdgeState;
  sweepProgress: number; // 0 = not sweeping, 1 = full sweep complete; animation only
}

export function drawEdge(edge: RenderableEdge, ctx: CanvasRenderingContext2D, globalScale: number): void {
  const sx = edge.source.x, sy = edge.source.y, tx = edge.target.x, ty = edge.target.y;
  if (sx === undefined || sy === undefined || tx === undefined || ty === undefined) return;

  const isTraversed = edge.state === 'traversed';
  const stroke = isTraversed ? hexToRgba(clusterColor[edge.targetCluster], 0.4) : color.edgeDefault;
  const width = (isTraversed ? 1.5 : 1) / globalScale;

  ctx.beginPath();
  ctx.strokeStyle = stroke;
  ctx.lineWidth = width;
  ctx.moveTo(sx, sy);
  ctx.lineTo(tx, ty);
  ctx.stroke();

  // Sweep overlay (drawn on top during animation).
  if (edge.sweepProgress > 0 && edge.sweepProgress < 1) {
    const t = edge.sweepProgress;
    const hx = sx + (tx - sx) * t;
    const hy = sy + (ty - sy) * t;
    ctx.beginPath();
    ctx.strokeStyle = color.accent;
    ctx.lineWidth = 2.5 / globalScale;
    ctx.moveTo(sx, sy);
    ctx.lineTo(hx, hy);
    ctx.stroke();
  }
}

function hexToRgba(hex: string, alpha: number): string {
  if (hex.startsWith('rgba')) return hex;
  const h = hex.replace('#', '');
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}
