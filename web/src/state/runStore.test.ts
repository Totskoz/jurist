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
          { bwb_id: 'A', article_label: '', quote: '', explanation: '' },
          { bwb_id: 'C', article_label: '', quote: '', explanation: '' },
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
