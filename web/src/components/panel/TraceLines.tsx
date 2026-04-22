import type { ReactNode } from 'react';
import type { TraceEvent } from '../../types/events';

type Rendered = string | ReactNode;

const subLineStyle: React.CSSProperties = {
  paddingLeft: 14,
  color: 'var(--text-tertiary)',
  fontSize: 12,
  opacity: 0.85,
  lineHeight: 1.55,
};

const subLineItalicStyle: React.CSSProperties = {
  ...subLineStyle,
  fontStyle: 'italic',
};

function renderDecomposition(data: Record<string, unknown>): ReactNode {
  const subs = (data.sub_questions as string[] | undefined) ?? [];
  const concepts = (data.concepts as string[] | undefined) ?? [];
  const intent = (data.intent as string | undefined) ?? '';
  const huurtype = (data.huurtype_hypothese as string | undefined) ?? '';
  return (
    <div>
      <div>decomposeert:</div>
      {subs.map((q, i) => (
        <div key={`sq-${i}`} style={subLineStyle}>• {q}</div>
      ))}
      {concepts.length > 0 && (
        <div style={subLineStyle}>concepten: {concepts.join(', ')}</div>
      )}
      {intent && <div style={subLineStyle}>intentie: {intent}</div>}
      {huurtype && <div style={subLineStyle}>huurtype: {huurtype}</div>}
    </div>
  );
}

function renderRerankWithPicks(
  picks: Array<{ ecli: string; reason: string }>,
): ReactNode {
  return (
    <div>
      <div>gekozen:</div>
      {picks.map((p, i) => (
        <div key={p.ecli + i} style={subLineStyle}>
          ✓ {p.ecli} — {p.reason}
        </div>
      ))}
    </div>
  );
}

function renderCitationEnriched(
  kind: string,
  id: string,
  label: string | undefined,
  quote: string,
  explanation: string,
): ReactNode {
  const headline =
    kind === 'artikel' && label
      ? `bron ${kind} ${id} (${label})`
      : `bron ${kind} ${id}`;
  return (
    <div>
      <div>{headline}</div>
      <div style={subLineItalicStyle}>"{quote}"</div>
      <div style={subLineStyle}>→ {explanation}</div>
    </div>
  );
}

function eventLine(ev: TraceEvent): Rendered | null {
  switch (ev.type) {
    case 'agent_started':
      return 'start';
    case 'agent_finished':
      return 'klaar';
    case 'decomposition_done':
      return renderDecomposition(ev.data);
    case 'tool_call_started':
      return `→ ${ev.data.tool}`;
    case 'tool_call_completed':
      return `✓ ${ev.data.tool} — ${ev.data.result_summary ?? ''}`;
    case 'node_visited':
      return `bezocht ${ev.data.article_id}`;
    case 'edge_traversed':
      return null;
    case 'search_started':
      return 'zoekt jurisprudentie';
    case 'case_found':
      return `gevonden ${ev.data.ecli} (sim=${Number(ev.data.similarity).toFixed(2)})`;
    case 'reranked': {
      const picks = ev.data.picks as Array<{ ecli: string; reason: string }> | undefined;
      if (picks && picks.length > 0) {
        return renderRerankWithPicks(picks);
      }
      // Back-compat: old snapshots have only `kept`.
      const kept = (ev.data.kept as string[] | undefined) ?? [];
      return `gekozen: ${kept.join(', ')}`;
    }
    case 'citation_resolved': {
      const kind = ev.data.kind as string;
      const id = ev.data.id as string;
      const quote = ev.data.quote as string | undefined;
      const explanation = ev.data.explanation as string | undefined;
      const label = ev.data.label as string | undefined;
      if (quote && explanation) {
        return renderCitationEnriched(kind, id, label, quote, explanation);
      }
      // Back-compat: snapshots predating enrichment.
      return `bron ${kind} ${id}`;
    }
    case 'answer_delta':
      return null;
    case 'agent_thinking':
      return null;
    default:
      return ev.type;
  }
}

export default function TraceLines({ events }: { events: TraceEvent[] }) {
  const rendered = events
    .map(eventLine)
    .filter((l): l is Rendered => l !== null);
  if (rendered.length === 0) return null;
  return (
    <ul
      style={{
        listStyle: 'none',
        padding: 0,
        margin: '10px 0 0',
        fontFamily: 'ui-monospace, monospace',
        fontSize: 13,
        color: 'var(--text-tertiary)',
        lineHeight: 1.65,
      }}
    >
      {rendered.map((l, i) => (
        <li key={i}>{l}</li>
      ))}
    </ul>
  );
}
