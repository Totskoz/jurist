import { useRunStore } from '../../../state/runStore';
import { useActiveRun } from '../../../hooks/useActiveRun';
import { useKgData } from '../../../hooks/useKgData';
import { shortLabelFor } from '../../graph/clusters';

function sourceUrlFor(bwbId: string): string {
  return `https://wetten.overheid.nl/${bwbId}`;
}

export default function InspectNodePhase() {
  const inspectedNode = useRunStore((s) => s.inspectedNode);
  const closeInspector = useRunStore((s) => s.closeInspector);
  const inspectNode = useRunStore((s) => s.inspectNode);
  const { citedSet } = useActiveRun();
  const { data } = useKgData();

  if (!inspectedNode || !data) return null;
  const node = data.nodes.find((n) => n.article_id === inspectedNode);
  if (!node) {
    return (
      <div>
        <BackButton onBack={closeInspector} />
        <p style={{ color: 'var(--text-secondary)', fontSize: 14, marginTop: 12 }}>Artikel niet gevonden.</p>
      </div>
    );
  }

  const isCited = citedSet.has(node.article_id);

  return (
    <div>
      <BackButton onBack={closeInspector} />

      <div style={{ marginTop: 16, display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 12 }}>
        <h3 style={{ fontSize: 24, fontWeight: 700, margin: 0 }}>{shortLabelFor(node)}</h3>
        <a
          href={sourceUrlFor(node.bwb_id)}
          target="_blank"
          rel="noreferrer"
          style={{
            fontSize: 14,
            color: 'var(--accent)',
            textDecoration: 'none',
            borderBottom: '1px dashed rgba(245, 194, 74, 0.45)',
            whiteSpace: 'nowrap',
          }}
        >
          Bron ↗
        </a>
      </div>

      <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 4 }}>
        {node.title}
      </div>

      {isCited && (
        <div style={{
          display: 'inline-block',
          marginTop: 12,
          padding: '5px 12px',
          background: 'rgba(134, 207, 154, 0.15)',
          border: '1px solid rgba(134, 207, 154, 0.4)',
          borderRadius: 12,
          fontSize: 12,
          fontWeight: 600,
          color: '#86cf9a',
        }}>
          Geciteerd in dit antwoord
        </div>
      )}

      <div style={{
        marginTop: 20,
        fontSize: 15,
        lineHeight: 1.65,
        color: 'var(--text-primary)',
        whiteSpace: 'pre-wrap',
      }}>
        {node.body_text || '(geen tekst beschikbaar)'}
      </div>

      {node.outgoing_refs.length > 0 && (
        <div style={{ marginTop: 24 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: 0.6, marginBottom: 10 }}>
            Verwijst naar
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {node.outgoing_refs
              .filter((ref) => data.nodes.some((n) => n.article_id === ref))
              .map((ref) => {
                const target = data.nodes.find((n) => n.article_id === ref)!;
                return (
                  <button
                    key={ref}
                    onClick={() => inspectNode(ref)}
                    style={{
                      padding: '6px 14px',
                      background: 'rgba(255,255,255,0.05)',
                      border: '1px solid var(--panel-border)',
                      borderRadius: 14,
                      fontSize: 13,
                      color: 'var(--text-primary)',
                      cursor: 'pointer',
                    }}
                  >
                    {shortLabelFor(target)}
                  </button>
                );
              })}
          </div>
        </div>
      )}
    </div>
  );
}

function BackButton({ onBack }: { onBack: () => void }) {
  return (
    <button
      onClick={onBack}
      style={{
        background: 'none',
        border: 'none',
        color: 'var(--text-secondary)',
        fontSize: 14,
        cursor: 'pointer',
        padding: 0,
      }}
    >
      ← Terug
    </button>
  );
}
