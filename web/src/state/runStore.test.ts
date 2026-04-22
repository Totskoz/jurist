import { beforeEach, describe, expect, it } from 'vitest';
import { useRunStore } from './runStore';
import type { TraceEvent } from '../types/events';

const ev = (type: string, data: Record<string, unknown> = {}, agent = 'synthesizer'): TraceEvent =>
  ({ type, data, agent, run_id: 'r1', ts: '2026-04-22T00:00:00Z' } as TraceEvent);

describe('runStore — new UI fields', () => {
  beforeEach(() => {
    useRunStore.getState().reset();
  });

  it('initializes inspectedNode=null, panelCollapsed=false, citedSet empty', () => {
    const s = useRunStore.getState();
    expect(s.inspectedNode).toBeNull();
    expect(s.panelCollapsed).toBe(false);
    expect(s.citedSet.size).toBe(0);
  });

  it('inspectNode sets inspectedNode', () => {
    useRunStore.getState().inspectNode('BWBR0005290/.../Artikel247');
    expect(useRunStore.getState().inspectedNode).toBe('BWBR0005290/.../Artikel247');
  });

  it('closeInspector clears inspectedNode', () => {
    useRunStore.getState().inspectNode('some-id');
    useRunStore.getState().closeInspector();
    expect(useRunStore.getState().inspectedNode).toBeNull();
  });

  it('toggleCollapse flips panelCollapsed', () => {
    expect(useRunStore.getState().panelCollapsed).toBe(false);
    useRunStore.getState().toggleCollapse();
    expect(useRunStore.getState().panelCollapsed).toBe(true);
    useRunStore.getState().toggleCollapse();
    expect(useRunStore.getState().panelCollapsed).toBe(false);
  });
});

describe('runStore — run_finished populates citedSet', () => {
  beforeEach(() => {
    useRunStore.getState().reset();
    useRunStore.setState({ history: [] });  // isolation — reset() preserves history by design
  });

  it('populates citedSet from final_answer.relevante_wetsartikelen', () => {
    const store = useRunStore.getState();
    store.start('r1', 'q');

    // Pretend the retriever visited 4 nodes.
    for (const aid of ['A', 'B', 'C', 'D']) {
      store.apply(ev('node_visited', { article_id: aid }));
    }

    const finishEv = ev('run_finished', {
      final_answer: {
        kind: 'answer',
        korte_conclusie: '',
        relevante_wetsartikelen: [
          { article_id: 'A', bwb_id: 'BWB-A', article_label: '', quote: '', explanation: '' },
          { article_id: 'C', bwb_id: 'BWB-C', article_label: '', quote: '', explanation: '' },
        ],
        vergelijkbare_uitspraken: [],
        aanbeveling: '',
      },
    });
    store.apply(finishEv);

    const s = useRunStore.getState();
    expect(s.citedSet.has('A')).toBe(true);
    expect(s.citedSet.has('C')).toBe(true);
    expect(s.citedSet.has('B')).toBe(false);
    expect(s.citedSet.has('D')).toBe(false);

    // Only cited nodes flip to `cited`; others stay visited.
    expect(s.kgState.get('A')).toBe('cited');
    expect(s.kgState.get('C')).toBe('cited');
    expect(s.kgState.get('B')).toBe('visited');
    expect(s.kgState.get('D')).toBe('visited');
  });

  it('handles insufficient_context answers with empty citations', () => {
    const store = useRunStore.getState();
    store.start('r1', 'q');
    store.apply(ev('node_visited', { article_id: 'X' }));
    store.apply(ev('run_finished', {
      final_answer: {
        kind: 'insufficient_context',
        reason: 'out-of-scope',
      },
    }));
    expect(useRunStore.getState().citedSet.size).toBe(0);
    // Visited stays visited, not promoted to cited.
    expect(useRunStore.getState().kgState.get('X')).toBe('visited');
  });
});

import type { HistoryEntry } from './historyApi';
import { vi } from 'vitest';

describe('runStore — history slice (Task 7)', () => {
  beforeEach(() => {
    useRunStore.getState().reset();
    useRunStore.setState({ history: [] });  // isolation — reset() preserves history by design
  });

  it('initializes history=[], viewingHistoryId=null, drawer closed', () => {
    const s = useRunStore.getState();
    expect(s.history).toEqual([]);
    expect(s.viewingHistoryId).toBeNull();
    expect(s.historyDrawerOpen).toBe(false);
  });

  it('toggleHistoryDrawer flips open state', () => {
    useRunStore.getState().toggleHistoryDrawer();
    expect(useRunStore.getState().historyDrawerOpen).toBe(true);
    useRunStore.getState().toggleHistoryDrawer();
    expect(useRunStore.getState().historyDrawerOpen).toBe(false);
  });

  it('viewHistory sets id and closes drawer', () => {
    useRunStore.getState().toggleHistoryDrawer();
    useRunStore.getState().viewHistory('run_1');
    const s = useRunStore.getState();
    expect(s.viewingHistoryId).toBe('run_1');
    expect(s.historyDrawerOpen).toBe(false);
  });

  it('exitHistory clears viewingHistoryId', () => {
    useRunStore.getState().viewHistory('run_1');
    useRunStore.getState().exitHistory();
    expect(useRunStore.getState().viewingHistoryId).toBeNull();
  });

  it('start() clears viewingHistoryId', () => {
    useRunStore.getState().viewHistory('run_1');
    useRunStore.getState().start('run_2', 'q2');
    expect(useRunStore.getState().viewingHistoryId).toBeNull();
  });

  it('reset() clears viewingHistoryId but preserves history array', () => {
    // Manually seed history (no public setter yet — direct setState).
    const entry: HistoryEntry = {
      id: 'run_1', question: 'q', timestamp: 0, status: 'finished',
      snapshot: {
        kgState: [], edgeState: [], traceLog: [], thinkingByAgent: {},
        answerText: '', finalAnswer: null, cases: [], resolutions: [], citedSet: [],
      },
    };
    useRunStore.setState({ history: [entry], viewingHistoryId: 'run_1' });
    useRunStore.getState().reset();
    const s = useRunStore.getState();
    expect(s.viewingHistoryId).toBeNull();
    expect(s.history).toEqual([entry]);  // preserved
  });
});

function mockFetchOk(): ReturnType<typeof vi.fn> {
  const fn = vi.fn(async () => new Response(
    JSON.stringify({ version: 1, entries: [] }),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  ));
  globalThis.fetch = fn as unknown as typeof fetch;
  return fn;
}

describe('runStore — archive/hydrate/delete/clear (Task 8)', () => {
  beforeEach(() => {
    useRunStore.getState().reset();
    useRunStore.setState({ history: [] });  // explicit isolation — reset() preserves history by design
  });

  it('archiveCurrent prepends entry, caps at 15, strips answer_delta', async () => {
    const fetchMock = mockFetchOk();
    const store = useRunStore.getState();
    store.start('run_new', 'question?');
    store.apply(ev('answer_delta', { text: 'hello' }, 'synthesizer'));
    store.apply(ev('answer_delta', { text: ' world' }, 'synthesizer'));
    store.apply(ev('node_visited', { article_id: 'A' }, 'statute_retriever'));

    store.archiveCurrent('finished');

    const s = useRunStore.getState();
    expect(s.history).toHaveLength(1);
    expect(s.history[0].id).toBe('run_new');
    expect(s.history[0].question).toBe('question?');
    expect(s.history[0].status).toBe('finished');
    expect(s.history[0].snapshot.answerText).toBe('hello world');
    expect(s.history[0].snapshot.traceLog.map((e) => e.type))
      .toEqual(['node_visited']);  // answer_delta stripped

    // PUT fired (fire-and-forget; allow microtask).
    await Promise.resolve();
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/history',
      expect.objectContaining({ method: 'PUT' }),
    );
  });

  it('archiveCurrent FIFO-caps at 15', () => {
    mockFetchOk();
    const mkEntry = (id: string): HistoryEntry => ({
      id, question: id, timestamp: 0, status: 'finished',
      snapshot: {
        kgState: [], edgeState: [], traceLog: [], thinkingByAgent: {},
        answerText: '', finalAnswer: null, cases: [], resolutions: [], citedSet: [],
      },
    });
    // Seed 15 existing entries, newest-first (index 0 = newest = old_14, index 14 = oldest = old_0).
    useRunStore.setState({ history: Array.from({ length: 15 }, (_, i) => mkEntry(`old_${14 - i}`)) });

    const store = useRunStore.getState();
    store.start('run_new', 'q');
    store.archiveCurrent('finished');

    const s = useRunStore.getState();
    expect(s.history).toHaveLength(15);
    expect(s.history[0].id).toBe('run_new');  // newest first
    expect(s.history.some((e) => e.id === 'old_0')).toBe(false);  // oldest evicted
    expect(s.history.some((e) => e.id === 'old_14')).toBe(true);  // kept
  });

  it('archiveCurrent with status=failed sets status=failed', () => {
    mockFetchOk();
    const store = useRunStore.getState();
    store.start('run_f', 'q');
    store.archiveCurrent('failed');
    expect(useRunStore.getState().history[0].status).toBe('failed');
  });

  it('deleteHistory removes entry and exits history when id is active', () => {
    mockFetchOk();
    const e1 = { id: '1', question: 'a', timestamp: 0, status: 'finished' as const,
      snapshot: { kgState: [], edgeState: [], traceLog: [], thinkingByAgent: {},
        answerText: '', finalAnswer: null, cases: [], resolutions: [], citedSet: [] }};
    const e2 = { ...e1, id: '2' };
    useRunStore.setState({ history: [e1, e2], viewingHistoryId: '1' });

    useRunStore.getState().deleteHistory('1');
    const s = useRunStore.getState();
    expect(s.history.map((e) => e.id)).toEqual(['2']);
    expect(s.viewingHistoryId).toBeNull();  // auto-exited
  });

  it('clearHistory empties history and exits view', () => {
    mockFetchOk();
    const e1 = { id: '1', question: 'a', timestamp: 0, status: 'finished' as const,
      snapshot: { kgState: [], edgeState: [], traceLog: [], thinkingByAgent: {},
        answerText: '', finalAnswer: null, cases: [], resolutions: [], citedSet: [] }};
    useRunStore.setState({ history: [e1], viewingHistoryId: '1' });

    useRunStore.getState().clearHistory();
    const s = useRunStore.getState();
    expect(s.history).toEqual([]);
    expect(s.viewingHistoryId).toBeNull();
  });

  it('hydrateHistory populates history from GET /api/history', async () => {
    const e1 = { id: '1', question: 'a', timestamp: 0, status: 'finished',
      snapshot: { kgState: [], edgeState: [], traceLog: [], thinkingByAgent: {},
        answerText: '', finalAnswer: null, cases: [], resolutions: [], citedSet: [] }};
    globalThis.fetch = vi.fn(async () => new Response(
      JSON.stringify({ version: 1, entries: [e1] }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    )) as unknown as typeof fetch;

    await useRunStore.getState().hydrateHistory();
    expect(useRunStore.getState().history.map((e) => e.id)).toEqual(['1']);
  });

  it('hydrateHistory sets history=[] when API fails', async () => {
    globalThis.fetch = vi.fn(async () => new Response('nope', { status: 500 })) as unknown as typeof fetch;
    useRunStore.setState({ history: [/* junk */] as HistoryEntry[] });
    await useRunStore.getState().hydrateHistory();
    expect(useRunStore.getState().history).toEqual([]);
  });
});

describe('runStore — apply() archives on terminal events (Task 9)', () => {
  beforeEach(() => {
    useRunStore.getState().reset();
    useRunStore.setState({ history: [] });  // isolation
  });

  it('run_finished triggers archiveCurrent with status=finished', () => {
    mockFetchOk();
    const store = useRunStore.getState();
    store.start('run_x', 'question');
    store.apply(ev('run_finished', {
      final_answer: {
        kind: 'answer',
        korte_conclusie: '',
        relevante_wetsartikelen: [],
        vergelijkbare_uitspraken: [],
        aanbeveling: '',
      },
    }));
    const s = useRunStore.getState();
    expect(s.history).toHaveLength(1);
    expect(s.history[0].id).toBe('run_x');
    expect(s.history[0].status).toBe('finished');
  });

  it('run_failed triggers archiveCurrent with status=failed', () => {
    mockFetchOk();
    const store = useRunStore.getState();
    store.start('run_y', 'bad question');
    store.apply(ev('run_failed', { reason: 'rate_limit' }));
    const s = useRunStore.getState();
    expect(s.history).toHaveLength(1);
    expect(s.history[0].id).toBe('run_y');
    expect(s.history[0].status).toBe('failed');
  });
});
