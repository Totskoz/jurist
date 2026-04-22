export const CLUSTER_KEYS = [
  'verplichtingen',
  'algemeen',
  'bedrijfsruimte',
  'huurcommissie',
  'eindigen',
  'huurprijzen',
  'overig',
] as const;

export type ClusterKey = (typeof CLUSTER_KEYS)[number];

export const clusterColor: Record<ClusterKey, string> = {
  verplichtingen: '#7fa3e0',
  algemeen: '#7bcdc4',
  bedrijfsruimte: '#dece7b',
  huurcommissie: '#b397db',
  eindigen: '#e48fa8',
  huurprijzen: '#86cf9a',
  overig: '#6b7280',
};

export const clusterLabel: Record<ClusterKey, string> = {
  verplichtingen: 'Verplichtingen onder huur',
  algemeen: 'Algemeen',
  bedrijfsruimte: 'Huur van bedrijfsruimte',
  huurcommissie: 'Huurcommissie & procedure',
  eindigen: 'Eindigen van de huur',
  huurprijzen: 'Huurprijzen',
  overig: 'Overig',
};

export const color = {
  textPrimary: '#e7eaf0',
  // textSecondary/Tertiary collapsed to primary — no muted text per user preference.
  textSecondary: '#e7eaf0',
  textTertiary: '#e7eaf0',
  accent: '#f5c24a',
  error: '#f07178',
  edgeDefault: 'rgba(255, 255, 255, 0.08)',
} as const;
