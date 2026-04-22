import { useRunStore } from '../../state/runStore';
import { formatRelativeNl } from '../../util/relativeTime';

export default function ViewingHistoryPill() {
  const viewingId = useRunStore((s) => s.viewingHistoryId);
  const history = useRunStore((s) => s.history);
  const exit = useRunStore((s) => s.exitHistory);

  if (viewingId === null) return null;
  const entry = history.find((e) => e.id === viewingId);
  if (!entry) return null;

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12,
        padding: '10px 14px',
        marginBottom: 16,
        background: 'rgba(255,255,255,0.04)',
        border: '1px solid var(--panel-border)',
        borderRadius: 8,
        fontSize: 13,
        color: 'var(--text-secondary)',
      }}
    >
      <span>
        Je bekijkt een eerdere vraag &middot; {formatRelativeNl(entry.timestamp)}
      </span>
      <button
        onClick={exit}
        style={{
          background: 'var(--accent)',
          color: '#0a0b0f',
          border: 'none',
          borderRadius: 6,
          padding: '6px 10px',
          fontSize: 12,
          fontWeight: 600,
          cursor: 'pointer',
        }}
      >
        Terug naar live
      </button>
    </div>
  );
}
