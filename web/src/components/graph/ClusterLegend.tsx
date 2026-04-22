import { CLUSTER_KEYS, clusterColor, clusterLabel } from '../../theme';

export default function ClusterLegend() {
  return (
    <div
      style={{
        position: 'fixed',
        bottom: 16,
        left: 16,
        padding: '12px 14px',
        background: 'var(--panel-surface)',
        backdropFilter: 'blur(12px)',
        border: '1px solid var(--panel-border)',
        borderRadius: 10,
        fontSize: 12,
        color: 'var(--text-secondary)',
        zIndex: 10,
      }}
    >
      <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: 6 }}>Clusters</div>
      {CLUSTER_KEYS.map((key) => (
        <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '2px 0' }}>
          <span
            style={{
              display: 'inline-block',
              width: 10,
              height: 10,
              borderRadius: 2,
              background: clusterColor[key],
            }}
          />
          <span>{clusterLabel[key]}</span>
        </div>
      ))}
    </div>
  );
}
