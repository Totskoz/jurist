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

describe('runStore — history slice (Task 7)', () => {
  beforeEach(() => {
    useRunStore.getState().reset();
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
