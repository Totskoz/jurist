import { useState } from 'react';
import { useRunStore } from '../../../state/runStore';
import { useActiveRun } from '../../../hooks/useActiveRun';
import CitationLink from '../../CitationLink';
import { InsufficientContextBanner } from '../../InsufficientContextBanner';
import PipelineProgress from '../PipelineProgress';
import AgentThinking from '../AgentThinking';
import TraceLines from '../TraceLines';
import ErrorCard from './ErrorCard';

const AGENT_ORDER = ['decomposer', 'statute_retriever', 'case_retriever', 'synthesizer', 'validator'] as const;

export default function AnswerReadyPhase() {
  const status = useRunStore((s) => s.status);
  const reset = useRunStore((s) => s.reset);
  const { question, finalAnswer, traceLog, thinkingByAgent } = useActiveRun();

  const [showReasoning, setShowReasoning] = useState(false);

  const byAgent: Record<string, typeof traceLog> = {};
  for (const ev of traceLog) {
    if (ev.agent) (byAgent[ev.agent] ??= []).push(ev);
  }

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

      {status === 'failed' ? (
        <ErrorCard />
      ) : !finalAnswer ? (
        <p style={{ color: 'var(--text-secondary)', fontSize: 14 }}>Geen antwoord ontvangen.</p>
      ) : finalAnswer.kind === 'insufficient_context' ? (
        <InsufficientContextBanner {...finalAnswer} />
      ) : (
        <>
          <Section title="Korte conclusie">
            <p style={{ fontSize: 17, lineHeight: 1.6, margin: 0 }}>{finalAnswer.korte_conclusie}</p>
          </Section>

          <Section title="Relevante wetsartikelen">
            <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
              {finalAnswer.relevante_wetsartikelen.map((c, i) => (
                <li key={`${c.bwb_id}-${i}`} style={{ marginBottom: 14, fontSize: 15, lineHeight: 1.6 }}>
                  <CitationLink kind="artikel" id={c.bwb_id}>
                    {c.article_label}
                  </CitationLink>
                  <em style={{ display: 'block', color: 'var(--text-secondary)', marginTop: 4 }}>"{c.quote}"</em>
                  <span>{c.explanation}</span>
                </li>
              ))}
            </ul>
          </Section>

          <Section title="Vergelijkbare uitspraken">
            <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
              {finalAnswer.vergelijkbare_uitspraken.map((c, i) => (
                <li key={`${c.ecli}-${i}`} style={{ marginBottom: 14, fontSize: 15, lineHeight: 1.6 }}>
                  <CitationLink kind="uitspraak" id={c.ecli}>
                    {c.ecli}
                  </CitationLink>
                  <em style={{ display: 'block', color: 'var(--text-secondary)', marginTop: 4 }}>"{c.quote}"</em>
                  <span>{c.explanation}</span>
                </li>
              ))}
            </ul>
          </Section>

          <Section title="Aanbeveling">
            <p style={{ fontSize: 15, lineHeight: 1.6, margin: 0 }}>{finalAnswer.aanbeveling}</p>
          </Section>
        </>
      )}

      {/* Collapsed reasoning disclosure */}
      {traceLog.length > 0 && (
        <div style={{ marginTop: 24, borderTop: '1px solid var(--panel-border)', paddingTop: 20 }}>
          <button
            onClick={() => setShowReasoning((v) => !v)}
            aria-expanded={showReasoning}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--text-secondary)',
              fontSize: 14,
              cursor: 'pointer',
              padding: 0,
            }}
          >
            {showReasoning ? '▾ Verberg redenering' : '▸ Toon redenering'}
          </button>
          {showReasoning && (
            <div style={{ marginTop: 14 }}>
              <PipelineProgress />
              {AGENT_ORDER.map((agent) => {
                if (!byAgent[agent]) return null;
                return (
                  <div key={agent} style={{ marginTop: 12 }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: 0.6 }}>
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
          marginTop: 24,
          width: '100%',
          padding: '12px 16px',
          background: 'rgba(255,255,255,0.05)',
          color: 'var(--text-primary)',
          border: '1px solid var(--panel-border)',
          borderRadius: 8,
          fontSize: 15,
          fontWeight: 500,
          cursor: 'pointer',
        }}
      >
        Nieuwe vraag
      </button>

      <p style={{ fontSize: 11, color: 'var(--text-tertiary)', textAlign: 'center', marginTop: 16 }}>
        Demo. Geen juridisch advies.
      </p>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{ marginBottom: 22 }}>
      <h3 style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: 0.6, marginBottom: 10, marginTop: 0 }}>
        {title}
      </h3>
      {children}
    </section>
  );
}
