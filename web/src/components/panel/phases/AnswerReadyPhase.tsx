import { useState } from 'react';
import { useRunStore } from '../../../state/runStore';
import CitationLink from '../../CitationLink';
import { InsufficientContextBanner } from '../../InsufficientContextBanner';
import PipelineProgress from '../PipelineProgress';
import AgentThinking from '../AgentThinking';
import TraceLines from '../TraceLines';
import ErrorCard from './ErrorCard';

const AGENT_ORDER = ['decomposer', 'statute_retriever', 'case_retriever', 'synthesizer', 'validator'] as const;

export default function AnswerReadyPhase() {
  const status = useRunStore((s) => s.status);
  const finalAnswer = useRunStore((s) => s.finalAnswer);
  const question = useRunStore((s) => s.question);
  const traceLog = useRunStore((s) => s.traceLog);
  const thinkingByAgent = useRunStore((s) => s.thinkingByAgent);
  const reset = useRunStore((s) => s.reset);

  const [showReasoning, setShowReasoning] = useState(false);

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

      {status === 'failed' ? (
        <ErrorCard />
      ) : !finalAnswer ? (
        <p style={{ color: 'var(--text-secondary)' }}>Geen antwoord ontvangen.</p>
      ) : finalAnswer.kind === 'insufficient_context' ? (
        <InsufficientContextBanner {...finalAnswer} />
      ) : (
        <>
          <Section title="Korte conclusie">
            <p style={{ fontSize: 15, lineHeight: 1.55 }}>{finalAnswer.korte_conclusie}</p>
          </Section>

          <Section title="Relevante wetsartikelen">
            <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
              {finalAnswer.relevante_wetsartikelen.map((c, i) => (
                <li key={`${c.bwb_id}-${i}`} style={{ marginBottom: 10, fontSize: 13, lineHeight: 1.55 }}>
                  <CitationLink kind="artikel" id={c.bwb_id}>
                    {c.article_label}
                  </CitationLink>
                  <em style={{ display: 'block', color: 'var(--text-secondary)', marginTop: 2 }}>"{c.quote}"</em>
                  <span>{c.explanation}</span>
                </li>
              ))}
            </ul>
          </Section>

          <Section title="Vergelijkbare uitspraken">
            <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
              {finalAnswer.vergelijkbare_uitspraken.map((c, i) => (
                <li key={`${c.ecli}-${i}`} style={{ marginBottom: 10, fontSize: 13, lineHeight: 1.55 }}>
                  <CitationLink kind="uitspraak" id={c.ecli}>
                    {c.ecli}
                  </CitationLink>
                  <em style={{ display: 'block', color: 'var(--text-secondary)', marginTop: 2 }}>"{c.quote}"</em>
                  <span>{c.explanation}</span>
                </li>
              ))}
            </ul>
          </Section>

          <Section title="Aanbeveling">
            <p style={{ fontSize: 13, lineHeight: 1.55 }}>{finalAnswer.aanbeveling}</p>
          </Section>
        </>
      )}

      {/* Collapsed reasoning disclosure */}
      {traceLog.length > 0 && (
        <div style={{ marginTop: 20, borderTop: '1px solid var(--panel-border)', paddingTop: 16 }}>
          <button
            onClick={() => setShowReasoning((v) => !v)}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--text-secondary)',
              fontSize: 12,
              cursor: 'pointer',
              padding: 0,
            }}
          >
            {showReasoning ? '▾ Verberg redenering' : '▸ Toon redenering'}
          </button>
          {showReasoning && (
            <div style={{ marginTop: 10 }}>
              <PipelineProgress />
              {AGENT_ORDER.map((agent) => {
                if (!byAgent[agent]) return null;
                return (
                  <div key={agent} style={{ marginTop: 8 }}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
                      {agent}
                    </div>
                    {thinkingByAgent[agent] && <AgentThinking agent={agent} text={thinkingByAgent[agent]} />}
                    <TraceLines events={byAgent[agent]} />
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      <button
        onClick={reset}
        style={{
          marginTop: 20,
          width: '100%',
          padding: '10px 14px',
          background: 'rgba(255,255,255,0.05)',
          color: 'var(--text-primary)',
          border: '1px solid var(--panel-border)',
          borderRadius: 8,
          fontSize: 13,
          cursor: 'pointer',
        }}
      >
        Nieuwe vraag
      </button>

      <p style={{ fontSize: 10, color: 'var(--text-tertiary)', textAlign: 'center', marginTop: 14 }}>
        Demo. Geen juridisch advies.
      </p>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{ marginBottom: 18 }}>
      <h3 style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 }}>
        {title}
      </h3>
      {children}
    </section>
  );
}
