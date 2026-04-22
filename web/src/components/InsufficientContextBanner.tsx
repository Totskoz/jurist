import type { StructuredAnswer } from '../types/events';

type Props = Extract<StructuredAnswer, { kind: 'insufficient_context' }>;

export function InsufficientContextBanner(props: Props) {
  return (
    <div style={{
      padding: 16,
      background: 'rgba(245, 194, 74, 0.08)',
      border: '1px solid rgba(245, 194, 74, 0.3)',
      borderRadius: 10,
    }}>
      <h3 style={{
        fontSize: 14,
        fontWeight: 600,
        color: 'var(--accent)',
        marginTop: 0,
        marginBottom: 8,
      }}>
        Geen voldoende bronnen voor deze vraag
      </h3>
      <p style={{ fontSize: 13, color: 'var(--text-primary)', margin: '0 0 8px' }}>
        {props.korte_conclusie}
      </p>
      <p style={{ fontSize: 12, color: 'var(--text-secondary)', fontStyle: 'italic', margin: '0 0 10px' }}>
        {props.insufficient_context_reason}
      </p>
      <p style={{ fontSize: 13, color: 'var(--text-primary)', margin: 0 }}>
        {props.aanbeveling}
      </p>
    </div>
  );
}
