import type { ClusterKey } from '../../theme';

export interface KgNodeLike {
  article_id: string;
  bwb_id: string;
  label: string;
  title: string;
}

const TITLE_TO_CLUSTER: Record<string, ClusterKey> = {
  'De verplichtingen van de huurder': 'verplichtingen',
  'Verplichtingen van de verhuurder': 'verplichtingen',
  'Algemeen': 'algemeen',
  'Algemene bepalingen': 'algemeen',
  'Huur van bedrijfsruimte': 'bedrijfsruimte',
  'Instelling, inrichting en samenstelling van de huurcommissie': 'huurcommissie',
  'De uitspraak en verdere bepalingen': 'huurcommissie',
  'Het eindigen van de huur': 'eindigen',
  'Huurprijzen': 'huurprijzen',
};

const UHW_BWB = 'BWBR0014315';

export function clusterOf(node: KgNodeLike): ClusterKey {
  const direct = TITLE_TO_CLUSTER[node.title];
  if (direct) return direct;
  if (node.bwb_id === UHW_BWB) return 'huurcommissie';
  return 'overig';
}

const BW_ARTICLE_RE = /\/Boek(\d+)\/.*Artikel([\w]+)$/;
const UHW_ARTICLE_RE = /Artikel([\w]+)$/;

export function shortLabelFor(node: KgNodeLike): string {
  if (node.bwb_id === 'BWBR0005290') {
    const m = BW_ARTICLE_RE.exec(node.article_id);
    if (m) return `${m[1]}:${m[2]}`;
  }
  if (node.bwb_id === UHW_BWB) {
    const m = UHW_ARTICLE_RE.exec(node.article_id);
    if (m) return `Uhw ${m[1]}`;
  }
  return node.label;
}
