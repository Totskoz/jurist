import { describe, expect, it } from 'vitest';
import { toSnapshot, fromSnapshot } from './snapshot';
import type { RunSnapshot } from './snapshot';
import type { TraceEvent } from '../types/events';

const ev = (type: string, data: Record<string, unknown> = {}, agent: string = ''): TraceEvent =>
  ({ type, data, agent, run_id: 'r', ts: '2026-04-22T00:00:00Z' } as TraceEvent);

describe('toSnapshot', () => {
  it('flattens Maps and Sets to arrays', () => {
    const kgState = new Map([['A', 'cited' as const], ['B', 'visited' as const]]);
    const edgeState = new Map([['A::B', 'traversed' as const]]);
    const citedSet = new Set(['A', 'B']);

    const snap = toSnapshot({
      question: 'q',
      kgState,
      edgeState,
      traceLog: [],
      thinkingByAgent: {},
      answerText: '',
      finalAnswer: null,
      cases: [],
      resolutions: [],
      citedSet,
    });

    expect(snap.kgState).toEqual([['A', 'cited'], ['B', 'visited']]);
    expect(snap.edgeState).toEqual([['A::B', 'traversed']]);
    expect(snap.citedSet).toEqual(['A', 'B']);
  });

  it('strips answer_delta events from traceLog', () => {
    const trace: TraceEvent[] = [
      ev('agent_started', {}, 'synthesizer'),
      ev('answer_delta', { text: 'x' }, 'synthesizer'),
      ev('answer_delta', { text: 'y' }, 'synthesizer'),
      ev('agent_finished', {}, 'synthesizer'),
    ];
    const snap = toSnapshot({
      question: 'q',
      kgState: new Map(),
      edgeState: new Map(),
      traceLog: trace,
      thinkingByAgent: {},
      answerText: 'xy',
      finalAnswer: null,
      cases: [],
      resolutions: [],
      citedSet: new Set(),
    });
    expect(snap.traceLog.map((e) => e.type)).toEqual(['agent_started', 'agent_finished']);
  });
});

describe('fromSnapshot', () => {
  it('rehydrates arrays back to Maps and Sets', () => {
    const snap: RunSnapshot = {
      kgState: [['A', 'cited'], ['B', 'visited']],
      edgeState: [['A::B', 'traversed']],
      traceLog: [],
      thinkingByAgent: {},
      answerText: '',
      finalAnswer: null,
      cases: [],
      resolutions: [],
      citedSet: ['A', 'B'],
    };
    const view = fromSnapshot(snap, 'q');
    expect(view.question).toBe('q');
    expect(view.kgState instanceof Map).toBe(true);
    expect(view.kgState.get('A')).toBe('cited');
    expect(view.edgeState.get('A::B')).toBe('traversed');
    expect(view.citedSet instanceof Set).toBe(true);
    expect(view.citedSet.has('A')).toBe(true);
  });
});

describe('toSnapshot → fromSnapshot round-trip', () => {
  it('preserves all fields except question (sourced from HistoryEntry)', () => {
    const kgState = new Map([['A', 'current' as const]]);
    const edgeState = new Map([['A::B', 'traversed' as const]]);
    const citedSet = new Set(['A']);

    const view1 = {
      question: 'original question',
      kgState,
      edgeState,
      traceLog: [ev('agent_started', {}, 'decomposer')],
      thinkingByAgent: { decomposer: 'thinking...' },
      answerText: 'hello',
      finalAnswer: null,
      cases: [{ ecli: 'ECLI:X', similarity: 0.9 }],
      resolutions: [{ kind: 'artikel' as const, id: 'A', resolved_url: 'http://x' }],
      citedSet,
    };
    // question isn't part of RunSnapshot — it's sourced from HistoryEntry.question
    // by the caller (selectActiveRun). Pass it explicitly on the from side.
    const view2 = fromSnapshot(toSnapshot(view1), view1.question);

    expect(view2.question).toEqual(view1.question);
    expect([...view2.kgState.entries()]).toEqual([...kgState.entries()]);
    expect([...view2.edgeState.entries()]).toEqual([...edgeState.entries()]);
    expect([...view2.citedSet]).toEqual([...citedSet]);
    expect(view2.traceLog).toEqual(view1.traceLog);
    expect(view2.thinkingByAgent).toEqual(view1.thinkingByAgent);
    expect(view2.answerText).toEqual(view1.answerText);
    expect(view2.cases).toEqual(view1.cases);
    expect(view2.resolutions).toEqual(view1.resolutions);
  });
});
