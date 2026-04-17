import { useRunStore } from '../state/runStore';
import type { TraceEvent } from '../types/events';

const AGENT_ORDER = [
  'decomposer',
  'statute_retriever',
  'case_retriever',
  'synthesizer',
  'validator',
] as const;
type AgentName = (typeof AGENT_ORDER)[number];

function eventLine(ev: TraceEvent): string | null {
  switch (ev.type) {
    case 'agent_started':
      return 'started';
    case 'agent_finished':
      return 'finished';
    case 'tool_call_started':
      return `→ ${ev.data.tool}(${JSON.stringify(ev.data.args)})`;
    case 'tool_call_completed':
      return `✓ ${ev.data.tool} — ${ev.data.result_summary}`;
    case 'node_visited':
      return `visited ${ev.data.article_id}`;
    case 'edge_traversed':
      return `traversed ${ev.data.from_id} → ${ev.data.to_id}`;
    case 'search_started':
      return 'vector search';
    case 'case_found':
      return `case ${ev.data.ecli} (sim=${(ev.data.similarity as number).toFixed(2)})`;
    case 'reranked':
      return `kept ${(ev.data.kept as string[]).join(', ')}`;
    case 'answer_delta':
      // Rendered in the AnswerPanel, not as a trace line.
      return null;
    case 'citation_resolved':
      return `resolved ${ev.data.kind} ${ev.data.id}`;
    default:
      return ev.type;
  }
}

export default function TracePanel() {
  const traceLog = useRunStore((s) => s.traceLog);
  const thinkingByAgent = useRunStore((s) => s.thinkingByAgent);

  const byAgent: Record<string, TraceEvent[]> = {};
  for (const ev of traceLog) {
    if (ev.agent) (byAgent[ev.agent] ??= []).push(ev);
  }

  return (
    <div className="h-full w-full overflow-y-auto border rounded p-3 text-sm">
      {AGENT_ORDER.map((agent: AgentName) => {
        const events = byAgent[agent] ?? [];
        if (events.length === 0) return null;
        return (
          <div key={agent} className="mb-4">
            <div className="font-semibold text-gray-800">{agent}</div>
            {thinkingByAgent[agent] && (
              <div className="mt-1 pl-3 border-l-2 border-amber-400 text-amber-900 whitespace-pre-wrap">
                {thinkingByAgent[agent]}
              </div>
            )}
            <ul className="mt-1 pl-3 space-y-0.5 font-mono text-xs text-gray-700">
              {events.map((ev, i) => {
                const line = eventLine(ev);
                if (line === null) return null;
                return <li key={i}>{line}</li>;
              })}
            </ul>
          </div>
        );
      })}
      {traceLog.length === 0 && (
        <div className="text-gray-500">Waiting for a question…</div>
      )}
    </div>
  );
}
