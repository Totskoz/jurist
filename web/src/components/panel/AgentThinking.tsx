interface Props {
  agent: string;
  text: string;
}

export default function AgentThinking({ agent, text }: Props) {
  if (!text) return null;
  return (
    <div
      style={{
        marginTop: 14,
        paddingLeft: 14,
        borderLeft: '3px solid var(--accent)',
        color: 'var(--text-secondary)',
        fontSize: 14,
        lineHeight: 1.55,
        whiteSpace: 'pre-wrap',
      }}
    >
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: 0.6, marginBottom: 6 }}>
        {agent} — gedachten
      </div>
      {text}
    </div>
  );
}
