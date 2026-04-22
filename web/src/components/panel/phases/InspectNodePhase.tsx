import { useRunStore } from '../../../state/runStore';
import { useKgData } from '../../../hooks/useKgData';
import CitationLink from '../../CitationLink';
import { shortLabelFor } from '../../graph/clusters';

export default function InspectNodePhase() {
  const inspectedNode = useRunStore((s) => s.inspectedNode);
  const citedSet = useRunStore((s) => s.citedSet);
  const closeInspector = useRunStore((s) => s.closeInspector);
  const inspectNode = useRunStore((s) => s.inspectNode);
  const { data } = useKgData();

  if (!inspectedNode || !data) return null;
  const node = data.nodes.find((n) => n.article_id === inspectedNode);
  if (!node) {
    return (
      <div>
        <BackButton onBack={closeInspector} />
        <p style={{ color: 'var(--text-secondary)' }}>Artikel niet gevonden.</p>
      </div>
    );
  }

  const isCited = citedSet.has(node.article_id);

  return (
    <div>
      <BackButton onBack={closeInspector} />

      <div style={{ marginTop: 12, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h3 style={{ fontSize: 18, fontWeight: 600, margin: 0 }}>{shortLabelFor(node)}</h3>
        <CitationLink kind="artikel" id={node.article_id}>
          Bron ↗
        </CitationLink>
      </div>

      <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>
        {node.title}
      </div>

      {isCited && (
        <div style={{
          display: 'inline-block',
          marginTop: 10,
          padding: '3px 8px',
          background: 'rgba(134, 207, 154, 0.15)',
          border: '1px solid rgba(134, 207, 154, 0.4)',
          borderRadius: 12,
          fontSize: 11,
          color: '#86cf9a',
        }}>
          Geciteerd in dit antwoord
        </div>
      )}

      <div style={{
        marginTop: 16,
        fontSize: 13,
        lineHeight: 1.6,
        color: 'var(--text-primary)',
        whiteSpace: 'pre-wrap',
      }}>
        {node.body_text || '(geen tekst beschikbaar)'}
      </div>

      {node.outgoing_refs.length > 0 && (
        <div style={{ marginTop: 20 }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 }}>
            Verwijst naar
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {node.outgoing_refs
              .filter((ref) => data.nodes.some((n) => n.article_id === ref))
              .map((ref) => {
                const target = data.nodes.find((n) => n.article_id === ref)!;
                return (
                  <button
                    key={ref}
                    onClick={() => inspectNode(ref)}
                    style={{
                      padding: '4px 10px',
                      background: 'rgba(255,255,255,0.05)',
                      border: '1px solid var(--panel-border)',
                      borderRadius: 12,
                      fontSize: 11,
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
        fontSize: 13,
        cursor: 'pointer',
        padding: 0,
      }}
    >
      ← Terug
    </button>
  );
}
