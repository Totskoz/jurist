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

  it('preserves decomposition_done, reranked picks, and citation_resolved enrichment fields', () => {
    const view1 = {
      question: 'Mag de huur met 15% omhoog?',
      kgState: new Map<string, 'default' | 'current' | 'visited' | 'cited'>(),
      edgeState: new Map<string, 'default' | 'traversed'>(),
      traceLog: [
        ev('decomposition_done', {
          sub_questions: ['Is 15% toegestaan?', 'Wat is het maximum?'],
          concepts: ['huurverhoging', 'sociale huur'],
          intent: 'legality_check',
          huurtype_hypothese: 'onbekend',
        }, 'decomposer'),
        ev('reranked', {
          picks: [
            { ecli: 'ECLI:NL:A:1', reason: 'Feitelijk vergelijkbaar met de vraag.' },
            { ecli: 'ECLI:NL:B:2', reason: 'Relevante juridische context.' },
            { ecli: 'ECLI:NL:C:3', reason: 'Toepassing van art. 7:248 BW.' },
          ],
          kept: ['ECLI:NL:A:1', 'ECLI:NL:B:2', 'ECLI:NL:C:3'],
        }, 'case_retriever'),
        ev('citation_resolved', {
          kind: 'artikel',
          id: 'BWBR0005290',
          resolved_url: 'https://wetten.overheid.nl/BWBR0005290',
          label: 'Boek 7, Artikel 248',
          quote: 'De verhuurder kan tot aan het tijdstip waarop drie jaren zijn verstreken',
          explanation: 'Regelt de bevoegdheid tot huurverhoging.',
        }, 'synthesizer'),
        ev('citation_resolved', {
          kind: 'uitspraak',
          id: 'ECLI:NL:RBAMS:2022:5678',
          resolved_url: 'https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:RBAMS:2022:5678',
          quote: 'Huurverhoging van 15% acht de rechtbank in dit geval buitensporig.',
          explanation: 'Rechtbank wijst 15% af.',
        }, 'synthesizer'),
      ],
      thinkingByAgent: {},
      answerText: '',
      finalAnswer: null,
      cases: [],
      resolutions: [],
      citedSet: new Set<string>(),
    };

    const view2 = fromSnapshot(toSnapshot(view1), view1.question);

    expect(view2.traceLog).toEqual(view1.traceLog);
    // Spot-check the enrichment fields survive as-is.
    const done = view2.traceLog[0];
    expect(done.data.sub_questions).toEqual(['Is 15% toegestaan?', 'Wat is het maximum?']);
    expect(done.data.huurtype_hypothese).toBe('onbekend');
    const reranked = view2.traceLog[1];
    expect((reranked.data.picks as Array<{ reason: string }>)[0].reason)
      .toBe('Feitelijk vergelijkbaar met de vraag.');
    const artikel = view2.traceLog[2];
    expect(artikel.data.label).toBe('Boek 7, Artikel 248');
    expect(artikel.data.quote).toContain('drie jaren');
    const uitspraak = view2.traceLog[3];
    expect(uitspraak.data.label).toBeUndefined();
    expect(uitspraak.data.explanation).toBe('Rechtbank wijst 15% af.');
  });
});
