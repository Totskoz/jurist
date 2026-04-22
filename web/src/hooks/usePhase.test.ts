import { describe, expect, it } from 'vitest';
import { derivePhase } from './usePhase';
import type { RunStatus } from '../state/runStore';

describe('derivePhase', () => {
  const table: Array<[RunStatus, string | null, string]> = [
    ['idle', null, 'idle'],
    ['running', null, 'running'],
    ['finished', null, 'answer-ready'],
    ['failed', null, 'answer-ready'],
    ['idle', 'some-id', 'inspecting-node'],
    ['running', 'some-id', 'inspecting-node'],
    ['finished', 'some-id', 'inspecting-node'],
    ['failed', 'some-id', 'inspecting-node'],
  ];

  for (const [status, inspected, expected] of table) {
    it(`${status} + inspected=${inspected ?? 'null'} → ${expected}`, () => {
      expect(derivePhase(status, inspected)).toBe(expected);
    });
  }
});
