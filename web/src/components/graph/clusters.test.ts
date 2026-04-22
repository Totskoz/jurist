import { describe, expect, it } from 'vitest';
import { clusterOf, shortLabelFor, type KgNodeLike } from './clusters';

const n = (article_id: string, bwb_id: string, label: string, title: string): KgNodeLike =>
  ({ article_id, bwb_id, label, title });

describe('clusterOf', () => {
  it('maps De verplichtingen van de huurder → verplichtingen', () => {
    expect(clusterOf(n('BWBR0005290/Boek7/Titeldeel4/Afdeling3/Artikel212', 'BWBR0005290', 'Boek 7, Artikel 212', 'De verplichtingen van de huurder'))).toBe('verplichtingen');
  });

  it('maps Verplichtingen van de verhuurder → verplichtingen', () => {
    expect(clusterOf(n('BWBR0005290/Boek7/Titeldeel4/Afdeling2/Artikel203', 'BWBR0005290', 'Boek 7, Artikel 203', 'Verplichtingen van de verhuurder'))).toBe('verplichtingen');
  });

  it('maps Algemeen → algemeen', () => {
    expect(clusterOf(n('BWBR0005290/Boek7/Titeldeel4/Afdeling5/Artikel232', 'BWBR0005290', 'Boek 7, Artikel 232', 'Algemeen'))).toBe('algemeen');
  });

  it('maps Algemene bepalingen → algemeen', () => {
    expect(clusterOf(n('BWBR0005290/Boek7/Titeldeel4/Afdeling1/Artikel201', 'BWBR0005290', 'Boek 7, Artikel 201', 'Algemene bepalingen'))).toBe('algemeen');
  });

  it('maps Huur van bedrijfsruimte → bedrijfsruimte', () => {
    expect(clusterOf(n('BWBR0005290/Boek7/Titeldeel4/Afdeling6/Artikel290', 'BWBR0005290', 'Boek 7, Artikel 290', 'Huur van bedrijfsruimte'))).toBe('bedrijfsruimte');
  });

  it('maps Instelling... huurcommissie → huurcommissie', () => {
    expect(clusterOf(n('BWBR0014315/Paragraaf1/Artikel2', 'BWBR0014315', 'Uhw, Artikel 2', 'Instelling, inrichting en samenstelling van de huurcommissie'))).toBe('huurcommissie');
  });

  it('maps De uitspraak en verdere bepalingen → huurcommissie', () => {
    expect(clusterOf(n('BWBR0014315/Paragraaf3/Artikel20', 'BWBR0014315', 'Uhw, Artikel 20', 'De uitspraak en verdere bepalingen'))).toBe('huurcommissie');
  });

  it('maps any unmatched Uhw title → huurcommissie (bwb_id fallback)', () => {
    expect(clusterOf(n('BWBR0014315/Paragraaf5/Artikel36', 'BWBR0014315', 'Uhw, Artikel 36', 'Taken van de huurcommissie'))).toBe('huurcommissie');
  });

  it('maps Het eindigen van de huur → eindigen', () => {
    expect(clusterOf(n('BWBR0005290/Boek7/Titeldeel4/Afdeling4/Artikel271', 'BWBR0005290', 'Boek 7, Artikel 271', 'Het eindigen van de huur'))).toBe('eindigen');
  });

  it('maps Huurprijzen → huurprijzen', () => {
    expect(clusterOf(n('BWBR0005290/Boek7/Titeldeel4/Afdeling5/Artikel247', 'BWBR0005290', 'Boek 7, Artikel 247', 'Huurprijzen'))).toBe('huurprijzen');
  });

  it('maps Overgangs- en slotbepalingen → overig', () => {
    expect(clusterOf(n('BWBR0005290/Boek7/Titeldeel4/Afdeling5/Artikel270a', 'BWBR0005290', 'Boek 7, Artikel 270a', 'Overgangs- en slotbepalingen'))).toBe('overig');
  });

  it('defaults unknown BW titles to overig', () => {
    expect(clusterOf(n('BWBR0005290/Boek7/Titeldeel4/Afdeling5/Artikel999', 'BWBR0005290', 'Boek 7, Artikel 999', 'Some Unknown Title'))).toBe('overig');
  });
});

describe('shortLabelFor', () => {
  it('formats BW article as Boek:Artikel', () => {
    expect(shortLabelFor({ article_id: 'BWBR0005290/Boek7/Titeldeel4/Afdeling5/Artikel247', bwb_id: 'BWBR0005290', label: 'Boek 7, Artikel 247', title: '' })).toBe('7:247');
  });

  it('formats BW sub-article variant (Artikel270a)', () => {
    expect(shortLabelFor({ article_id: 'BWBR0005290/Boek7/Titeldeel4/Afdeling5/Artikel270a', bwb_id: 'BWBR0005290', label: 'Boek 7, Artikel 270a', title: '' })).toBe('7:270a');
  });

  it('formats Uhw article as "Uhw N"', () => {
    expect(shortLabelFor({ article_id: 'BWBR0014315/Artikel10', bwb_id: 'BWBR0014315', label: 'Uhw, Artikel 10', title: '' })).toBe('Uhw 10');
  });

  it('formats Uhw sub-article variant as "Uhw 4a"', () => {
    expect(shortLabelFor({ article_id: 'BWBR0014315/Paragraaf1/Artikel4a', bwb_id: 'BWBR0014315', label: 'Uhw, Artikel 4a', title: '' })).toBe('Uhw 4a');
  });

  it('falls back to node.label for unrecognised patterns', () => {
    expect(shortLabelFor({ article_id: 'BWBR0099999/Weird/Path', bwb_id: 'BWBR0099999', label: 'Fallback Label', title: '' })).toBe('Fallback Label');
  });
});

import kgData from '../../../../data/kg/huurrecht.json';

describe('clusterOf — real data coverage', () => {
  it('every KG node maps to exactly one cluster', () => {
    const kg = kgData as { nodes: KgNodeLike[] };
    const seen = new Set<string>();
    for (const node of kg.nodes) {
      const key = clusterOf(node);
      expect(['verplichtingen', 'algemeen', 'bedrijfsruimte', 'huurcommissie', 'eindigen', 'huurprijzen', 'overig']).toContain(key);
      seen.add(key);
    }
    // Sanity: all 7 clusters are non-empty on the current corpus.
    expect(seen.size).toBe(7);
  });
});
