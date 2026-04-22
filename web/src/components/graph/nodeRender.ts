export function radiusFromDegree(degree: number): number {
  return 4 + 1.8 * Math.sqrt(Math.max(0, degree));
}

const DEFAULT_LABEL_FRACTION = 0.15;

export function shouldShowLabel(
  rankByDegree: number,
  totalNodes: number,
  fraction = DEFAULT_LABEL_FRACTION
): boolean {
  if (totalNodes <= 0) return false;
  const cutoff = Math.floor(totalNodes * fraction);
  return rankByDegree <= cutoff;
}

import { clusterColor, color, type ClusterKey } from '../../theme';
import type { NodeState } from '../../state/runStore';

export interface RenderableNode {
  article_id: string;
  cluster: ClusterKey;
  degree: number;
  rank: number;
  label: string;
  state: NodeState;
  x?: number;
  y?: number;
  isInspected: boolean;
  totalNodes: number;
}

export function drawNode(
  node: RenderableNode,
  ctx: CanvasRenderingContext2D,
  globalScale: number,
  pulseT: number
): void {
  if (node.x === undefined || node.y === undefined) return;
  const r = radiusFromDegree(node.degree);
  const fill = clusterColor[node.cluster];

  // Halo (current pulse OR cited persistent glow).
  if (node.state === 'current') {
    const haloR = r * 2 + pulseT * 4;
    const haloAlpha = 0.4 * (1 - pulseT);
    ctx.beginPath();
    ctx.fillStyle = hexToRgba(color.accent, haloAlpha);
    ctx.arc(node.x, node.y, haloR, 0, Math.PI * 2);
    ctx.fill();
  } else if (node.state === 'cited') {
    ctx.beginPath();
    ctx.fillStyle = hexToRgba(fill, 0.35);
    ctx.arc(node.x, node.y, r * 1.8, 0, Math.PI * 2);
    ctx.fill();
  }

  // Core fill.
  ctx.beginPath();
  const coreAlpha = node.state === 'default' ? 0.55 : 1.0;
  ctx.fillStyle = hexToRgba(fill, coreAlpha);
  ctx.arc(node.x, node.y, r, 0, Math.PI * 2);
  ctx.fill();

  // Stroke.
  let strokeColor: string | null = null;
  let strokeWidth = 0;
  if (node.isInspected) {
    strokeColor = 'rgba(255,255,255,0.7)';
    strokeWidth = 1.5;
  } else if (node.state === 'current') {
    strokeColor = color.accent;
    strokeWidth = 2;
  } else if (node.state === 'visited') {
    strokeColor = fill;
    strokeWidth = 1;
  }
  if (strokeColor) {
    ctx.beginPath();
    ctx.strokeStyle = strokeColor;
    ctx.lineWidth = strokeWidth / globalScale;
    ctx.arc(node.x, node.y, r, 0, Math.PI * 2);
    ctx.stroke();
  }

  // Label for top ~15%.
  if (shouldShowLabel(node.rank, node.totalNodes)) {
    const fontSize = 10 / globalScale;
    ctx.font = `${fontSize}px ui-sans-serif, system-ui, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.lineWidth = 3 / globalScale;
    ctx.strokeStyle = 'rgba(10, 11, 15, 0.9)';
    ctx.strokeText(node.label, node.x, node.y + r + 2);
    ctx.fillStyle = color.textPrimary;
    ctx.fillText(node.label, node.x, node.y + r + 2);
  }
}

function hexToRgba(hex: string, alpha: number): string {
  // Accepts #rrggbb OR rgba(...) passthrough.
  if (hex.startsWith('rgba')) return hex;
  const h = hex.replace('#', '');
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}
