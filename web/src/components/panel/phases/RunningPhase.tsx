import { useRunStore } from '../../../state/runStore';
import PipelineProgress from '../PipelineProgress';
import AgentThinking from '../AgentThinking';
import TraceLines from '../TraceLines';

const AGENT_ORDER = ['decomposer', 'statute_retriever', 'case_retriever', 'synthesizer', 'validator'] as const;

export default function RunningPhase() {
  const question = useRunStore((s) => s.question);
  const traceLog = useRunStore((s) => s.traceLog);
  const thinkingByAgent = useRunStore((s) => s.thinkingByAgent);
  const answerText = useRunStore((s) => s.answerText);

  // Which agent is currently active (most recent agent_started without a matching agent_finished)?
  const active = (() => {
    const done = new Set<string>();
    let current: string | null = null;
    for (const ev of traceLog) {
      if (!ev.agent) continue;
      if (ev.type === 'agent_started') current = ev.agent;
      if (ev.type === 'agent_finished') {
        done.add(ev.agent);
        if (current === ev.agent) current = null;
      }
    }
    return current;
  })();

  const byAgent: Record<string, typeof traceLog> = {};
  for (const ev of traceLog) {
    if (ev.agent) (byAgent[ev.agent] ??= []).push(ev);
  }

  return (
    <div>
      <div style={{
        fontSize: 12,
        color: 'var(--text-secondary)',
        padding: '6px 10px',
        background: 'rgba(255,255,255,0.03)',
        borderRadius: 6,
        marginBottom: 16,
      }}>
        {question}
      </div>

      <PipelineProgress />

      {AGENT_ORDER.map((agent) => {
        if (!byAgent[agent]) return null;
        const isActive = active === agent;
        return (
          <div key={agent} style={{ marginBottom: isActive ? 16 : 8 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: isActive ? 'var(--accent)' : 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
              {agent}
            </div>
            {isActive && thinkingByAgent[agent] && (
              <AgentThinking agent={agent} text={thinkingByAgent[agent]} />
            )}
            <TraceLines events={byAgent[agent]} />
          </div>
        );
      })}

      {answerText && (
        <div style={{
          marginTop: 16,
          padding: 12,
          background: 'rgba(134, 207, 154, 0.08)',
          border: '1px solid rgba(134, 207, 154, 0.3)',
          borderRadius: 8,
          fontSize: 13,
          color: 'var(--text-primary)',
          whiteSpace: 'pre-wrap',
          lineHeight: 1.5,
        }}>
          {answerText}
        </div>
      )}
    </div>
  );
}
