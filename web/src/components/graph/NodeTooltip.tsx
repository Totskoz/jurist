interface NodeTooltipProps {
  label: string;
  title: string;
  x: number;
  y: number;
}

export default function NodeTooltip({ label, title, x, y }: NodeTooltipProps) {
  return (
    <div
      style={{
        position: 'fixed',
        left: x + 12,
        top: y + 12,
        padding: '8px 10px',
        background: 'var(--panel-surface)',
        backdropFilter: 'blur(12px)',
        border: '1px solid var(--panel-border)',
        borderRadius: 6,
        fontSize: 12,
        color: 'var(--text-primary)',
        pointerEvents: 'none',
        zIndex: 20,
        maxWidth: 260,
      }}
    >
      <div style={{ fontWeight: 600 }}>{label}</div>
      <div style={{ color: 'var(--text-secondary)', fontSize: 11, marginTop: 2 }}>{title}</div>
    </div>
  );
}
