// Shared panel layout constants so Panel (DOM) and Graph (canvas reserve)
// stay in sync without a magic number living in two places.

export const PANEL_MIN_WIDTH = 420;
export const PANEL_MAX_WIDTH = 900;
export const PANEL_VIEWPORT_FRACTION = 0.4;
// Breathing space between the right edge of the cluster area and the panel.
export const PANEL_GUTTER = 32;
// How far the panel slides out when collapsed (width + a bit of overshoot).
export const PANEL_COLLAPSE_OVERSHOOT = 48;

export function computePanelWidth(viewportWidth: number): number {
  const target = Math.round(viewportWidth * PANEL_VIEWPORT_FRACTION);
  return Math.max(PANEL_MIN_WIDTH, Math.min(PANEL_MAX_WIDTH, target));
}
