// Mirror of backend StructuredAnswer + TraceEvent shapes.
// Keep in sync with src/jurist/schemas.py.

export type Intent = 'legality_check' | 'calculation' | 'procedure' | 'other';

export interface WetArtikelCitation {
  article_id: string;
  bwb_id: string;
  article_label: string;
  quote: string;
  explanation: string;
}

export interface UitspraakCitation {
  ecli: string;
  quote: string;
  explanation: string;
}

export type StructuredAnswerBase = {
  korte_conclusie: string;
  relevante_wetsartikelen: WetArtikelCitation[];
  vergelijkbare_uitspraken: UitspraakCitation[];
  aanbeveling: string;
};

export type StructuredAnswer =
  | (StructuredAnswerBase & { kind: 'answer'; insufficient_context_reason: null })
  | (StructuredAnswerBase & { kind: 'insufficient_context'; insufficient_context_reason: string });

export type AgentName =
  | 'decomposer'
  | 'statute_retriever'
  | 'case_retriever'
  | 'synthesizer'
  | 'validator'
  | '';

export interface TraceEvent {
  type: string;
  agent: AgentName;
  run_id: string;
  ts: string;
  data: Record<string, unknown>;
}
