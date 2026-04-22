import { CLUSTER_KEYS, clusterColor, clusterLabel } from '../../theme';

export default function ClusterLegend() {
  return (
    <div
      style={{
        position: 'fixed',
        bottom: 20,
        left: 20,
        padding: '16px 18px',
        background: 'var(--panel-surface)',
        backdropFilter: 'blur(12px)',
        border: '1px solid var(--panel-border)',
        borderRadius: 12,
        fontSize: 14,
        color: 'var(--text-secondary)',
        zIndex: 10,
      }}
    >
      <div style={{ fontWeight: 700, fontSize: 13, color: 'var(--text-primary)', marginBottom: 10, textTransform: 'uppercase', letterSpacing: 0.6 }}>Clusters</div>
      {CLUSTER_KEYS.map((key) => (
        <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '3px 0' }}>
          <span
            style={{
              display: 'inline-block',
              width: 13,
              height: 13,
              borderRadius: 3,
              background: clusterColor[key],
            }}
          />
          <span>{clusterLabel[key]}</span>
        </div>
      ))}
    </div>
  );
}
