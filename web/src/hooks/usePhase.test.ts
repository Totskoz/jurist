import { describe, expect, it } from 'vitest';
import { derivePhase } from './usePhase';
import type { RunStatus } from '../state/runStore';

describe('derivePhase', () => {
  const table: Array<[RunStatus, string | null, string | null, string]> = [
    ['idle', null, null, 'idle'],
    ['running', null, null, 'running'],
    ['finished', null, null, 'answer-ready'],
    ['failed', null, null, 'answer-ready'],
    ['idle', 'some-id', null, 'inspecting-node'],
    ['running', 'some-id', null, 'inspecting-node'],
    ['finished', 'some-id', null, 'inspecting-node'],
    ['failed', 'some-id', null, 'inspecting-node'],
    // Viewing history forces answer-ready regardless of live status.
    ['idle', null, 'run_past', 'answer-ready'],
    ['running', null, 'run_past', 'answer-ready'],
    ['finished', null, 'run_past', 'answer-ready'],
    ['failed', null, 'run_past', 'answer-ready'],
    // Inspected node still wins over historic view.
    ['idle', 'some-id', 'run_past', 'inspecting-node'],
  ];

  for (const [status, inspected, viewingId, expected] of table) {
    it(`${status} + inspected=${inspected ?? 'null'} + viewing=${viewingId ?? 'null'} → ${expected}`, () => {
      expect(derivePhase(status, inspected, viewingId)).toBe(expected);
    });
  }
});
