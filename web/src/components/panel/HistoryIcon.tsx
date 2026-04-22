import { useRunStore } from '../../state/runStore';

export default function HistoryIcon() {
  const count = useRunStore((s) => s.history.length);
  const toggle = useRunStore((s) => s.toggleHistoryDrawer);

  return (
    <button
      onClick={toggle}
      aria-label={`Historie (${count} eerdere vragen)`}
      title="Historie"
      style={{
        position: 'absolute',
        top: 12,
        left: 12,
        width: 32,
        height: 32,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'transparent',
        border: 'none',
        color: 'var(--text-secondary)',
        cursor: 'pointer',
        zIndex: 2,
      }}
    >
      {/* Clock SVG */}
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <polyline points="12 6 12 12 16 14" />
      </svg>
      {count > 0 && (
        <span
          style={{
            position: 'absolute',
            top: 4,
            right: 4,
            background: 'var(--accent)',
            color: '#0a0b0f',
            borderRadius: 8,
            fontSize: 10,
            fontWeight: 700,
            padding: '0 5px',
            minWidth: 14,
            height: 14,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          {count}
        </span>
      )}
    </button>
  );
}
