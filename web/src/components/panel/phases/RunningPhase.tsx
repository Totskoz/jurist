import { useEffect, useRef } from 'react';
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

  // Autoscroll to bottom as new events / answer tokens arrive.
  const bottomRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [traceLog.length, answerText]);

  return (
    <div>
      <div style={{
        fontSize: 14,
        lineHeight: 1.5,
        color: 'var(--text-secondary)',
        padding: '10px 14px',
        background: 'rgba(255,255,255,0.03)',
        borderRadius: 8,
        marginBottom: 20,
      }}>
        {question}
      </div>

      <PipelineProgress />

      {AGENT_ORDER.map((agent) => {
        if (!byAgent[agent]) return null;
        const isActive = active === agent;
        return (
          <div key={agent} style={{ marginBottom: isActive ? 20 : 12 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: isActive ? 'var(--accent)' : 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: 0.6 }}>
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
          marginTop: 20,
          padding: 16,
          background: 'rgba(134, 207, 154, 0.08)',
          border: '1px solid rgba(134, 207, 154, 0.3)',
          borderRadius: 10,
          fontSize: 15,
          color: 'var(--text-primary)',
          whiteSpace: 'pre-wrap',
          lineHeight: 1.6,
        }}>
          {answerText}
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
