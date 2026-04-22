import { useRunStore } from '../../state/runStore';

export default function CollapseHandle() {
  const collapsed = useRunStore((s) => s.panelCollapsed);
  const toggle = useRunStore((s) => s.toggleCollapse);
  return (
    <button
      onClick={toggle}
      aria-label={collapsed ? 'Paneel uitklappen' : 'Paneel inklappen'}
      style={{
        position: 'absolute',
        left: -32,
        top: '50%',
        transform: 'translateY(-50%)',
        width: 28,
        height: 48,
        background: 'var(--panel-surface)',
        backdropFilter: 'blur(12px)',
        border: '1px solid var(--panel-border)',
        borderRight: 'none',
        borderRadius: '8px 0 0 8px',
        color: 'var(--text-primary)',
        cursor: 'pointer',
        fontSize: 16,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      {collapsed ? '‹' : '›'}
    </button>
  );
}
