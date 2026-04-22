import { describe, expect, it } from 'vitest';
import { validateKgData } from './useKgData';

describe('validateKgData', () => {
  it('filters out edges whose source or target is not a known node', () => {
    const raw = {
      nodes: [
        { article_id: 'A', bwb_id: 'BWBR1', label: 'A', title: 'Algemeen', body_text: '', outgoing_refs: [] },
        { article_id: 'B', bwb_id: 'BWBR1', label: 'B', title: 'Algemeen', body_text: '', outgoing_refs: [] },
      ],
      edges: [
        { from_id: 'A', to_id: 'B', kind: 'explicit' as const },
        { from_id: 'A', to_id: 'GHOST', kind: 'explicit' as const },
        { from_id: 'GHOST', to_id: 'B', kind: 'explicit' as const },
      ],
    };
    const result = validateKgData(raw);
    expect(result.edges).toHaveLength(1);
    expect(result.edges[0]).toMatchObject({ from_id: 'A', to_id: 'B' });
  });

  it('computes degree per node', () => {
    const raw = {
      nodes: [
        { article_id: 'A', bwb_id: 'BWBR1', label: 'A', title: 'Algemeen', body_text: '', outgoing_refs: [] },
        { article_id: 'B', bwb_id: 'BWBR1', label: 'B', title: 'Algemeen', body_text: '', outgoing_refs: [] },
        { article_id: 'C', bwb_id: 'BWBR1', label: 'C', title: 'Algemeen', body_text: '', outgoing_refs: [] },
      ],
      edges: [
        { from_id: 'A', to_id: 'B', kind: 'explicit' as const },
        { from_id: 'A', to_id: 'C', kind: 'explicit' as const },
      ],
    };
    const result = validateKgData(raw);
    expect(result.degree.get('A')).toBe(2);
    expect(result.degree.get('B')).toBe(1);
    expect(result.degree.get('C')).toBe(1);
  });

  it('ranks nodes by degree descending (ties broken by article_id)', () => {
    const raw = {
      nodes: [
        { article_id: 'A', bwb_id: 'BWBR1', label: 'A', title: 'Algemeen', body_text: '', outgoing_refs: [] },
        { article_id: 'B', bwb_id: 'BWBR1', label: 'B', title: 'Algemeen', body_text: '', outgoing_refs: [] },
        { article_id: 'C', bwb_id: 'BWBR1', label: 'C', title: 'Algemeen', body_text: '', outgoing_refs: [] },
      ],
      edges: [
        { from_id: 'A', to_id: 'B', kind: 'explicit' as const },
        { from_id: 'A', to_id: 'C', kind: 'explicit' as const },
      ],
    };
    const result = validateKgData(raw);
    expect(result.rankByDegree.get('A')).toBe(0); // highest
    // B and C tie; deterministic by article_id.
    expect(result.rankByDegree.get('B')).toBe(1);
    expect(result.rankByDegree.get('C')).toBe(2);
  });
});
