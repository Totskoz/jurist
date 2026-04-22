/**
 * Force simulation tuning for react-force-graph-2d.
 * Picked to produce a layout resembling the reference image for ~218 nodes.
 */
export const FORCE_CONFIG = {
  // How many ticks of simulation run before we freeze the layout.
  cooldownTicks: 350,
  // How warm the simulation starts (0..1). 0.3 = moderate shake-out.
  warmupTicks: 0,
  // Link distance (between linked nodes).
  linkDistance: 60,
  // Charge strength — negative = repulsion. Stronger repulsion spreads clusters.
  chargeStrength: -90,
  // Collision radius multiplier over rendered node radius.
  collisionFactor: 1.2,
} as const;
