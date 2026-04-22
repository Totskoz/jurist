import type { StructuredAnswer } from '../types/events';

type Props = Extract<StructuredAnswer, { kind: 'insufficient_context' }>;

export function InsufficientContextBanner(props: Props) {
  return (
    <div className="p-4 border border-amber-400 bg-amber-50 rounded">
      <h3 className="text-amber-900 font-semibold mb-2">
        Geen voldoende bronnen voor deze vraag
      </h3>
      <p className="text-amber-900">{props.korte_conclusie}</p>
      <p className="text-amber-800 text-sm mt-2 italic">
        {props.insufficient_context_reason}
      </p>
      <p className="text-amber-900 mt-3">{props.aanbeveling}</p>
    </div>
  );
}
