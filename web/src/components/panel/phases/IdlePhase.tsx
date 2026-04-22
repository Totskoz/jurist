import { useState } from 'react';
import { useRunStore } from '../../../state/runStore';
import { ask } from '../../../api/ask';
import { subscribe } from '../../../api/sse';

const LOCKED_QUESTION = 'Mijn verhuurder wil de huur met 15% verhogen per volgend jaar, mag dat?';

export default function IdlePhase() {
  const [input, setInput] = useState(LOCKED_QUESTION);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const start = useRunStore((s) => s.start);
  const apply = useRunStore((s) => s.apply);

  const submit = async () => {
    const q = input.trim();
    if (!q) return;
    setSubmitting(true);
    setError(null);
    try {
      const { question_id } = await ask(q);
      start(question_id, q);
      subscribe(question_id, (ev) => apply(ev));
    } catch (e) {
      setError('Kon de vraag niet versturen. Probeer opnieuw.');
      setSubmitting(false);
    }
  };

  return (
    <div>
      <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 4, color: 'var(--text-primary)' }}>
        Jurist
      </h2>
      <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 20 }}>
        Dutch huurrecht — multi-agent demo
      </p>

      <label style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
        Je vraag
      </label>
      <textarea
        value={input}
        onChange={(e) => setInput(e.target.value)}
        disabled={submitting}
        rows={5}
        style={{
          display: 'block',
          width: '100%',
          marginTop: 6,
          padding: 12,
          fontSize: 14,
          fontFamily: 'inherit',
          color: 'var(--text-primary)',
          background: 'rgba(255,255,255,0.04)',
          border: '1px solid var(--panel-border)',
          borderRadius: 8,
          resize: 'vertical',
        }}
      />

      {error && (
        <p style={{ color: 'var(--error)', fontSize: 12, marginTop: 8 }}>{error}</p>
      )}

      <button
        onClick={() => void submit()}
        disabled={submitting || input.trim().length === 0}
        style={{
          marginTop: 16,
          width: '100%',
          padding: '12px 16px',
          background: 'var(--accent)',
          color: '#0a0b0f',
          border: 'none',
          borderRadius: 8,
          fontSize: 14,
          fontWeight: 600,
          cursor: submitting ? 'not-allowed' : 'pointer',
          opacity: submitting ? 0.6 : 1,
        }}
      >
        {submitting ? 'Bezig…' : 'Vraag stellen'}
      </button>
    </div>
  );
}
