interface Props {
  agent: string;
  text: string;
}

export default function AgentThinking({ agent, text }: Props) {
  if (!text) return null;
  return (
    <div
      style={{
        marginTop: 12,
        paddingLeft: 12,
        borderLeft: '2px solid var(--accent)',
        color: 'var(--text-secondary)',
        fontSize: 12,
        whiteSpace: 'pre-wrap',
      }}
    >
      <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 }}>
        {agent} — gedachten
      </div>
      {text}
    </div>
  );
}
