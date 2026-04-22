import { useRunStore } from '../../state/runStore';
import { color } from '../../theme';

const AGENTS = ['decomposer', 'statute_retriever', 'case_retriever', 'synthesizer', 'validator'] as const;
const LABELS: Record<(typeof AGENTS)[number], string> = {
  decomposer: 'Ontleden',
  statute_retriever: 'Wet',
  case_retriever: 'Jurisprudentie',
  synthesizer: 'Antwoord',
  validator: 'Check',
};

type AgentStatus = 'pending' | 'active' | 'done';

export default function PipelineProgress() {
  const traceLog = useRunStore((s) => s.traceLog);

  const statusByAgent: Record<string, AgentStatus> = {};
  for (const agent of AGENTS) statusByAgent[agent] = 'pending';
  for (const ev of traceLog) {
    if (!ev.agent) continue;
    if (ev.type === 'agent_started') statusByAgent[ev.agent] = 'active';
    if (ev.type === 'agent_finished') statusByAgent[ev.agent] = 'done';
  }

  return (
    <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
      {AGENTS.map((agent) => {
        const st = statusByAgent[agent];
        const bg =
          st === 'done' ? 'rgba(134, 207, 154, 0.25)' :
          st === 'active' ? 'rgba(245, 194, 74, 0.3)' :
          'rgba(255,255,255,0.04)';
        const border =
          st === 'done' ? 'rgba(134, 207, 154, 0.6)' :
          st === 'active' ? color.accent :
          'rgba(255,255,255,0.1)';
        const text =
          st === 'active' ? color.textPrimary : 'var(--text-secondary)';
        return (
          <div
            key={agent}
            style={{
              flex: 1,
              padding: '9px 6px',
              borderRadius: 8,
              background: bg,
              border: `1px solid ${border}`,
              fontSize: 12,
              fontWeight: 600,
              textAlign: 'center',
              color: text,
            }}
          >
            {LABELS[agent]}
          </div>
        );
      })}
    </div>
  );
}
