import { useRunStore } from '../state/runStore';
import CitationLink from './CitationLink';
import { InsufficientContextBanner } from './InsufficientContextBanner';

export default function AnswerPanel() {
  const finalAnswer = useRunStore((s) => s.finalAnswer);
  const streaming = useRunStore((s) => s.answerText);
  const status = useRunStore((s) => s.status);

  if (status === 'idle') {
    return (
      <div className="p-4 border rounded text-gray-500">
        Answer appears here after you ask a question.
      </div>
    );
  }

  if (!finalAnswer) {
    return (
      <div className="p-4 border rounded">
        <div className="text-sm text-gray-500 mb-2">Synthesizer is streaming…</div>
        <p className="whitespace-pre-wrap">{streaming}</p>
      </div>
    );
  }

  if (finalAnswer.kind === 'insufficient_context') {
    return <InsufficientContextBanner {...finalAnswer} />;
  }

  return (
    <div className="p-4 border rounded space-y-4">
      <section>
        <h2 className="font-semibold text-lg">Korte conclusie</h2>
        <p>{finalAnswer.korte_conclusie}</p>
      </section>

      <section>
        <h2 className="font-semibold text-lg">Relevante wetsartikelen</h2>
        <ul className="list-disc list-inside space-y-2">
          {finalAnswer.relevante_wetsartikelen.map((c, i) => (
            <li key={`${c.bwb_id}-${i}`}>
              <CitationLink kind="artikel" id={c.bwb_id}>
                {c.article_label}
              </CitationLink>{' '}
              — <em>"{c.quote}"</em> {c.explanation}
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2 className="font-semibold text-lg">Vergelijkbare uitspraken</h2>
        <ul className="list-disc list-inside space-y-2">
          {finalAnswer.vergelijkbare_uitspraken.map((c, i) => (
            <li key={`${c.ecli}-${i}`}>
              <CitationLink kind="uitspraak" id={c.ecli}>
                {c.ecli}
              </CitationLink>{' '}
              — <em>"{c.quote}"</em> {c.explanation}
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2 className="font-semibold text-lg">Aanbeveling</h2>
        <p>{finalAnswer.aanbeveling}</p>
      </section>

      <p className="text-xs text-gray-400 pt-4 border-t">
        Demo. Geen juridisch advies.
      </p>
    </div>
  );
}
