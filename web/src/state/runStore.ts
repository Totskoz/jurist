import { create } from 'zustand';
import type { StructuredAnswer, TraceEvent } from '../types/events';

export type NodeState = 'default' | 'current' | 'visited' | 'cited';
export type EdgeState = 'default' | 'traversed';
export type RunStatus = 'idle' | 'running' | 'finished' | 'failed';

export interface CaseHit {
  ecli: string;
  similarity: number;
}

export interface CitationResolution {
  kind: 'artikel' | 'uitspraak';
  id: string;
  resolved_url: string;
}

interface RunState {
  runId: string | null;
  status: RunStatus;
  question: string;

  kgState: Map<string, NodeState>;
  edgeState: Map<string, EdgeState>;

  traceLog: TraceEvent[];
  thinkingByAgent: Record<string, string>;
  answerText: string;
  finalAnswer: StructuredAnswer | null;
  cases: CaseHit[];
  resolutions: CitationResolution[];

  start: (runId: string, question: string) => void;
  apply: (ev: TraceEvent) => void;
  reset: () => void;
}

const edgeKey = (from: string, to: string): string => `${from}::${to}`;

export const useRunStore = create<RunState>((set, get) => ({
  runId: null,
  status: 'idle',
  question: '',
  kgState: new Map(),
  edgeState: new Map(),
  traceLog: [],
  thinkingByAgent: {},
  answerText: '',
  finalAnswer: null,
  cases: [],
  resolutions: [],

  start: (runId, question) =>
    set({
      runId,
      question,
      status: 'running',
      kgState: new Map(),
      edgeState: new Map(),
      traceLog: [],
      thinkingByAgent: {},
      answerText: '',
      finalAnswer: null,
      cases: [],
      resolutions: [],
    }),

  reset: () =>
    set({
      runId: null,
      status: 'idle',
      question: '',
      kgState: new Map(),
      edgeState: new Map(),
      traceLog: [],
      thinkingByAgent: {},
      answerText: '',
      finalAnswer: null,
      cases: [],
      resolutions: [],
    }),

  apply: (ev) => {
    const s = get();
    const traceLog = [...s.traceLog, ev];

    switch (ev.type) {
      case 'node_visited': {
        const aid = ev.data.article_id as string;
        const next = new Map(s.kgState);
        // Demote prior "current" to "visited".
        for (const [k, v] of next) {
          if (v === 'current') next.set(k, 'visited');
        }
        next.set(aid, 'current');
        set({ traceLog, kgState: next });
        return;
      }
      case 'edge_traversed': {
        const from = ev.data.from_id as string;
        const to = ev.data.to_id as string;
        const next = new Map(s.edgeState);
        next.set(edgeKey(from, to), 'traversed');
        set({ traceLog, edgeState: next });
        return;
      }
      case 'agent_thinking': {
        const agent = ev.agent;
        const delta = (ev.data.text as string) ?? '';
        set({
          traceLog,
          thinkingByAgent: {
            ...s.thinkingByAgent,
            [agent]: (s.thinkingByAgent[agent] ?? '') + delta,
          },
        });
        return;
      }
      case 'answer_delta': {
        set({ traceLog, answerText: s.answerText + ((ev.data.text as string) ?? '') });
        return;
      }
      case 'case_found': {
        set({
          traceLog,
          cases: [
            ...s.cases,
            {
              ecli: ev.data.ecli as string,
              similarity: ev.data.similarity as number,
            },
          ],
        });
        return;
      }
      case 'citation_resolved': {
        set({
          traceLog,
          resolutions: [
            ...s.resolutions,
            {
              kind: ev.data.kind as 'artikel' | 'uitspraak',
              id: ev.data.id as string,
              resolved_url: ev.data.resolved_url as string,
            },
          ],
        });
        return;
      }
      case 'run_finished': {
        // Demote any "current" to "cited" on the retriever's selected set.
        const next = new Map(s.kgState);
        for (const [k, v] of next) {
          if (v === 'current' || v === 'visited') next.set(k, 'cited');
        }
        const finalAnswer = (ev.data.final_answer as StructuredAnswer) ?? null;
        set({ traceLog, kgState: next, status: 'finished', finalAnswer });
        return;
      }
      case 'run_failed': {
        set({ traceLog, status: 'failed' });
        return;
      }
      default: {
        set({ traceLog });
      }
    }
  },
}));

export const edgeStateKey = edgeKey;
