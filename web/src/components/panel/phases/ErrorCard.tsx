import { useRunStore } from '../../../state/runStore';

const REASON_COPY: Record<string, string> = {
  citation_grounding: 'De AI kon de citaten niet verifiëren. Probeer de vraag opnieuw.',
  decomposition: 'De vraag kon niet worden geanalyseerd. Probeer hem anders te formuleren.',
  case_rerank: 'Geen relevante jurisprudentie gevonden voor deze vraag.',
  rate_limit: 'Even rustig aan — probeer het over een minuut opnieuw.',
  llm_error: 'Er ging iets mis bij het AI-model. Probeer het opnieuw.',
  connection_lost: 'Verbinding verloren. Probeer het opnieuw.',
};

function copyFor(reason: string | undefined): string {
  if (!reason) return 'Er ging iets mis.';
  return REASON_COPY[reason] ?? 'Er ging iets mis.';
}

export default function ErrorCard() {
  const traceLog = useRunStore((s) => s.traceLog);
  const reset = useRunStore((s) => s.reset);

  // Find the run_failed event's reason.
  const failEv = [...traceLog].reverse().find((e) => e.type === 'run_failed');
  const reason = (failEv?.data?.reason as string | undefined);

  return (
    <div style={{
      padding: 16,
      background: 'rgba(240, 113, 120, 0.1)',
      border: '1px solid rgba(240, 113, 120, 0.3)',
      borderRadius: 10,
    }}>
      <div style={{ fontWeight: 600, color: 'var(--error)', marginBottom: 6 }}>
        Fout
      </div>
      <p style={{ fontSize: 13, color: 'var(--text-primary)', marginBottom: 12 }}>
        {copyFor(reason)}
      </p>
      <button
        onClick={() => {
          reset();
          // Re-populate with the same question for a quick retry — handled by IdlePhase's default.
          // (We just reset; the user clicks Ask again in idle.)
        }}
        style={{
          padding: '8px 14px',
          background: 'var(--accent)',
          color: '#0a0b0f',
          border: 'none',
          borderRadius: 6,
          fontSize: 13,
          fontWeight: 600,
          cursor: 'pointer',
        }}
      >
        Opnieuw proberen
      </button>
    </div>
  );
}
