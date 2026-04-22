import { describe, expect, it } from 'vitest';
import { formatRelativeNl } from './relativeTime';

describe('formatRelativeNl', () => {
  const NOW = 1_700_000_000_000;

  it('just now → "net nu"', () => {
    expect(formatRelativeNl(NOW - 10_000, NOW)).toBe('net nu');
  });

  it('seconds → "X seconden geleden"', () => {
    expect(formatRelativeNl(NOW - 45_000, NOW)).toBe('45 seconden geleden');
  });

  it('single minute → "1 minuut geleden"', () => {
    expect(formatRelativeNl(NOW - 60_000, NOW)).toBe('1 minuut geleden');
  });

  it('multiple minutes', () => {
    expect(formatRelativeNl(NOW - 10 * 60_000, NOW)).toBe('10 minuten geleden');
  });

  it('single hour', () => {
    expect(formatRelativeNl(NOW - 60 * 60_000, NOW)).toBe('1 uur geleden');
  });

  it('multiple hours', () => {
    expect(formatRelativeNl(NOW - 3 * 60 * 60_000, NOW)).toBe('3 uur geleden');
  });

  it('yesterday', () => {
    expect(formatRelativeNl(NOW - 25 * 60 * 60_000, NOW)).toBe('gisteren');
  });

  it('multiple days', () => {
    expect(formatRelativeNl(NOW - 4 * 24 * 60 * 60_000, NOW)).toBe('4 dagen geleden');
  });
});
