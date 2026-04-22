import { useEffect, useRef, useState } from 'react';
import { useRunStore } from '../../../state/runStore';
import { useActiveRun } from '../../../hooks/useActiveRun';
import PipelineProgress from '../PipelineProgress';
import AgentThinking from '../AgentThinking';
import TraceLines from '../TraceLines';

const AGENT_ORDER = ['decomposer', 'statute_retriever', 'case_retriever', 'synthesizer', 'validator'] as const;

export default function RunningPhase() {
  const question = useRunStore((s) => s.question);
  const { traceLog, thinkingByAgent, answerText } = useActiveRun();

  // Which agent is currently active (most recent agent_started without a matching agent_finished)?
  // Also capture when it started so we can show live elapsed time — makes it obvious
  // that a silent agent (e.g. synthesizer before first token) is still working.
  const { active, activeStartedAt } = (() => {
    let current: string | null = null;
    let startedAt: number | null = null;
    for (const ev of traceLog) {
      if (!ev.agent) continue;
      if (ev.type === 'agent_started') {
        current = ev.agent;
        const t = Date.parse(ev.ts);
        startedAt = Number.isFinite(t) ? t : Date.now();
      }
      if (ev.type === 'agent_finished' && current === ev.agent) {
        current = null;
        startedAt = null;
      }
    }
    return { active: current, activeStartedAt: startedAt };
  })();

  // Tick every 250ms while an agent is active so the elapsed counter advances
  // visibly between events. Interval is cleared as soon as no agent is active.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (active == null) return;
    const id = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(id);
  }, [active]);
  const elapsedSec =
    active != null && activeStartedAt != null
      ? Math.max(0, (now - activeStartedAt) / 1000)
      : 0;

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
            <div style={{
              fontSize: 13,
              fontWeight: 700,
              color: isActive ? 'var(--accent)' : 'var(--text-tertiary)',
              textTransform: 'uppercase',
              letterSpacing: 0.6,
              display: 'flex',
              alignItems: 'center',
              gap: 8,
            }}>
              <span>{agent}</span>
              {isActive && (
                <>
                  <span className="agent-spin" aria-hidden />
                  <span style={{
                    fontVariantNumeric: 'tabular-nums',
                    fontWeight: 500,
                    letterSpacing: 0,
                    textTransform: 'none',
                    color: 'var(--text-secondary)',
                    opacity: 0.75,
                  }}>
                    {elapsedSec.toFixed(1)}s
                  </span>
                </>
              )}
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
