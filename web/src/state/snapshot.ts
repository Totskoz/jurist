import type { StructuredAnswer, TraceEvent } from '../types/events';
import type { CaseHit, CitationResolution, EdgeState, NodeState } from './runStore';

/**
 * Structural subset of RunState that components render. Both the live slice
 * and rehydrated historic snapshots conform to this shape so a single
 * `useActiveRun` hook can swap between them.
 */
export interface ActiveRunView {
  question: string;
  kgState: Map<string, NodeState>;
  edgeState: Map<string, EdgeState>;
  traceLog: TraceEvent[];
  thinkingByAgent: Record<string, string>;
  answerText: string;
  finalAnswer: StructuredAnswer | null;
  cases: CaseHit[];
  resolutions: CitationResolution[];
  citedSet: Set<string>;
}

/**
 * Serialized form of ActiveRunView: Maps → entries arrays, Set → array,
 * and `answer_delta` events filtered out of the trace (they are redundant
 * with `answerText` + `finalAnswer` and dominate the size budget).
 */
export interface RunSnapshot {
  kgState: [string, NodeState][];
  edgeState: [string, EdgeState][];
  traceLog: TraceEvent[];
  thinkingByAgent: Record<string, string>;
  answerText: string;
  finalAnswer: StructuredAnswer | null;
  cases: CaseHit[];
  resolutions: CitationResolution[];
  citedSet: string[];
}

export function toSnapshot(view: ActiveRunView): RunSnapshot {
  return {
    kgState: [...view.kgState.entries()],
    edgeState: [...view.edgeState.entries()],
    traceLog: view.traceLog.filter((ev) => ev.type !== 'answer_delta'),
    thinkingByAgent: { ...view.thinkingByAgent },
    answerText: view.answerText,
    finalAnswer: view.finalAnswer,
    cases: [...view.cases],
    resolutions: [...view.resolutions],
    citedSet: [...view.citedSet],
  };
}

export function fromSnapshot(snap: RunSnapshot, question: string): ActiveRunView {
  return {
    question,
    kgState: new Map(snap.kgState),
    edgeState: new Map(snap.edgeState),
    traceLog: snap.traceLog,
    thinkingByAgent: { ...snap.thinkingByAgent },
    answerText: snap.answerText,
    finalAnswer: snap.finalAnswer,
    cases: [...snap.cases],
    resolutions: [...snap.resolutions],
    citedSet: new Set(snap.citedSet),
  };
}
