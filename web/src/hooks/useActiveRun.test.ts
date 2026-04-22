import { describe, expect, it } from 'vitest';
import { selectActiveRun } from './useActiveRun';
import type { RunSnapshot } from '../state/snapshot';
import type { HistoryEntry } from '../state/historyApi';

function makeSnapshot(overrides: Partial<RunSnapshot> = {}): RunSnapshot {
  return {
    kgState: [['SNAP_A', 'cited']],
    edgeState: [],
    traceLog: [],
    thinkingByAgent: {},
    answerText: 'snapshot-answer',
    finalAnswer: null,
    cases: [],
    resolutions: [],
    citedSet: ['SNAP_A'],
    ...overrides,
  };
}

function makeEntry(id: string, snap: RunSnapshot, question = 'snapshot-question'): HistoryEntry {
  return { id, question, timestamp: 0, status: 'finished', snapshot: snap };
}

describe('selectActiveRun', () => {
  const liveView = {
    question: 'live-question',
    kgState: new Map([['LIVE_A', 'current' as const]]),
    edgeState: new Map(),
    traceLog: [],
    thinkingByAgent: { decomposer: 'thinking live' },
    answerText: 'live-answer',
    finalAnswer: null,
    cases: [],
    resolutions: [],
    citedSet: new Set<string>(),
  };

  it('returns live view when viewingHistoryId is null', () => {
    const out = selectActiveRun(liveView, null, []);
    expect(out.question).toBe('live-question');
    expect(out.answerText).toBe('live-answer');
    expect(out.kgState.get('LIVE_A')).toBe('current');
  });

  it('returns rehydrated snapshot when viewingHistoryId matches an entry', () => {
    const entry = makeEntry('run_1', makeSnapshot());
    const out = selectActiveRun(liveView, 'run_1', [entry]);
    expect(out.question).toBe('snapshot-question');
    expect(out.answerText).toBe('snapshot-answer');
    expect(out.kgState.get('SNAP_A')).toBe('cited');
    expect(out.kgState.has('LIVE_A')).toBe(false);
  });

  it('falls back to live view when viewingHistoryId does not match any entry', () => {
    const out = selectActiveRun(liveView, 'nonexistent', []);
    expect(out.question).toBe('live-question');
    expect(out.answerText).toBe('live-answer');
  });
});
