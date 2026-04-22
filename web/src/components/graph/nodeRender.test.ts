import { describe, expect, it } from 'vitest';
import { radiusFromDegree, shouldShowLabel } from './nodeRender';

describe('radiusFromDegree', () => {
  it('degree 0 → 4 px', () => {
    expect(radiusFromDegree(0)).toBe(4);
  });

  it('degree 1 → 5.8 px', () => {
    expect(radiusFromDegree(1)).toBeCloseTo(5.8, 2);
  });

  it('degree 16 → ~11.2 px', () => {
    expect(radiusFromDegree(16)).toBeCloseTo(11.2, 2);
  });

  it('is monotonic in degree', () => {
    for (let d = 0; d < 20; d++) {
      expect(radiusFromDegree(d + 1)).toBeGreaterThan(radiusFromDegree(d));
    }
  });
});

describe('shouldShowLabel', () => {
  it('shows labels for top ~15% (default threshold 0.15)', () => {
    // 218 nodes; top 15% = top 32.7 → rank 0..32 should be true, 33+ false.
    const total = 218;
    expect(shouldShowLabel(0, total)).toBe(true);
    expect(shouldShowLabel(30, total)).toBe(true);
    expect(shouldShowLabel(32, total)).toBe(true);
    expect(shouldShowLabel(33, total)).toBe(false);
    expect(shouldShowLabel(100, total)).toBe(false);
  });

  it('handles edge cases: 0 total, 1 total', () => {
    expect(shouldShowLabel(0, 0)).toBe(false);
    expect(shouldShowLabel(0, 1)).toBe(true);
  });
});
