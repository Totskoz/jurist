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
