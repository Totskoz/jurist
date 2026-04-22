import { useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useRunStore } from '../../state/runStore';
import { formatRelativeNl } from '../../util/relativeTime';

export default function HistoryDrawer() {
  const open = useRunStore((s) => s.historyDrawerOpen);
  const toggle = useRunStore((s) => s.toggleHistoryDrawer);
  const history = useRunStore((s) => s.history);
  const viewHistory = useRunStore((s) => s.viewHistory);
  const deleteHistory = useRunStore((s) => s.deleteHistory);
  const clearHistory = useRunStore((s) => s.clearHistory);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') toggle();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, toggle]);

  const onClear = () => {
    if (history.length === 0) return;
    if (window.confirm('Alle geschiedenis wissen?')) clearHistory();
  };

  const onDelete = (id: string, question: string) => {
    const preview = question.length > 50 ? question.slice(0, 47) + '…' : question;
    if (window.confirm(`Verwijder "${preview}"?`)) deleteHistory(id);
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ x: '-100%' }}
          animate={{ x: 0 }}
          exit={{ x: '-100%' }}
          transition={{ type: 'spring', stiffness: 220, damping: 26 }}
          style={{
            position: 'absolute',
            top: 56,  // below CollapseHandle/HistoryIcon row
            left: 0,
            right: 0,
            bottom: 0,
            background: 'var(--panel-surface)',
            backdropFilter: 'blur(20px)',
            borderRight: '1px solid var(--panel-border)',
            display: 'flex',
            flexDirection: 'column',
            zIndex: 3,
          }}
        >
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '16px 20px',
            borderBottom: '1px solid var(--panel-border)',
          }}>
            <h3 style={{
              margin: 0,
              fontSize: 15,
              fontWeight: 700,
              color: 'var(--text-primary)',
              textTransform: 'uppercase',
              letterSpacing: 0.6,
            }}>
              Historie ({history.length})
            </h3>
            <div style={{ display: 'flex', gap: 8 }}>
              {history.length > 0 && (
                <button
                  onClick={onClear}
                  style={{
                    background: 'none',
                    border: 'none',
                    color: 'var(--text-tertiary)',
                    fontSize: 12,
                    cursor: 'pointer',
                  }}
                >
                  Wis alles
                </button>
              )}
              <button
                onClick={toggle}
                aria-label="Sluit historie"
                style={{
                  background: 'none',
                  border: 'none',
                  color: 'var(--text-secondary)',
                  fontSize: 18,
                  cursor: 'pointer',
                  padding: 0,
                  lineHeight: 1,
                }}
              >
                ×
              </button>
            </div>
          </div>

          <div style={{ flex: 1, overflowY: 'auto', padding: 12 }}>
            {history.length === 0 ? (
              <p style={{
                color: 'var(--text-tertiary)',
                fontSize: 13,
                textAlign: 'center',
                padding: 40,
                margin: 0,
              }}>
                Nog geen eerdere vragen
              </p>
            ) : (
              <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
                {history.map((entry) => (
                  <li
                    key={entry.id}
                    style={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: 10,
                      padding: '10px 12px',
                      marginBottom: 4,
                      borderRadius: 8,
                      cursor: 'pointer',
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(255,255,255,0.05)'; }}
                    onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
                    onClick={() => viewHistory(entry.id)}
                  >
                    <span
                      aria-label={entry.status === 'finished' ? 'geslaagd' : 'mislukt'}
                      style={{
                        width: 8,
                        height: 8,
                        borderRadius: 4,
                        background: entry.status === 'finished' ? '#4ade80' : '#f87171',
                        flexShrink: 0,
                        marginTop: 7,
                      }}
                    />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{
                        fontSize: 13,
                        lineHeight: 1.4,
                        color: 'var(--text-primary)',
                        display: '-webkit-box',
                        WebkitLineClamp: 2,
                        WebkitBoxOrient: 'vertical',
                        overflow: 'hidden',
                      }}>
                        {entry.question}
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 2 }}>
                        {formatRelativeNl(entry.timestamp)}
                      </div>
                    </div>
                    <button
                      onClick={(e) => { e.stopPropagation(); onDelete(entry.id, entry.question); }}
                      aria-label="Verwijder"
                      style={{
                        background: 'none',
                        border: 'none',
                        color: 'var(--text-tertiary)',
                        fontSize: 16,
                        cursor: 'pointer',
                        padding: '0 4px',
                        lineHeight: 1,
                      }}
                    >
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
