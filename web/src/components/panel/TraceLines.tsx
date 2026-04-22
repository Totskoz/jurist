import type { TraceEvent } from '../../types/events';

function eventLine(ev: TraceEvent): string | null {
  switch (ev.type) {
    case 'agent_started': return 'start';
    case 'agent_finished': return 'klaar';
    case 'tool_call_started':
      return `→ ${ev.data.tool}`;
    case 'tool_call_completed':
      return `✓ ${ev.data.tool} — ${ev.data.result_summary ?? ''}`;
    case 'node_visited':
      return `bezocht ${ev.data.article_id}`;
    case 'edge_traversed':
      return null; // too noisy — graph shows these
    case 'search_started':
      return 'zoekt jurisprudentie';
    case 'case_found':
      return `gevonden ${ev.data.ecli} (sim=${Number(ev.data.similarity).toFixed(2)})`;
    case 'reranked':
      return `gekozen: ${(ev.data.kept as string[]).join(', ')}`;
    case 'citation_resolved':
      return `bron ${ev.data.kind} ${ev.data.id}`;
    case 'answer_delta':
      return null; // rendered as streaming prose elsewhere
    case 'agent_thinking':
      return null; // shown in AgentThinking
    default:
      return ev.type;
  }
}

export default function TraceLines({ events }: { events: TraceEvent[] }) {
  const lines = events.map(eventLine).filter((l) => l !== null);
  if (lines.length === 0) return null;
  return (
    <ul style={{
      listStyle: 'none',
      padding: 0,
      margin: '10px 0 0',
      fontFamily: 'ui-monospace, monospace',
      fontSize: 13,
      color: 'var(--text-tertiary)',
      lineHeight: 1.65,
    }}>
      {lines.map((l, i) => <li key={i}>{l}</li>)}
    </ul>
  );
}
