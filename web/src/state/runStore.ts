import { create } from 'zustand';
import type { StructuredAnswer, TraceEvent } from '../types/events';
import { getHistory, putHistory, type HistoryEntry } from './historyApi';
import { toSnapshot } from './snapshot';

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

  inspectedNode: string | null;
  panelCollapsed: boolean;
  citedSet: Set<string>;
  history: HistoryEntry[];
  viewingHistoryId: string | null;
  historyDrawerOpen: boolean;

  start: (runId: string, question: string) => void;
  apply: (ev: TraceEvent) => void;
  reset: () => void;
  inspectNode: (articleId: string) => void;
  closeInspector: () => void;
  toggleCollapse: () => void;
  toggleHistoryDrawer: () => void;
  viewHistory: (id: string) => void;
  exitHistory: () => void;
  archiveCurrent: (status: 'finished' | 'failed') => void;
  deleteHistory: (id: string) => void;
  clearHistory: () => void;
  hydrateHistory: () => Promise<void>;
}

const HISTORY_CAP = 15;

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
  inspectedNode: null,
  panelCollapsed: false,
  citedSet: new Set(),
  history: [],
  viewingHistoryId: null,
  historyDrawerOpen: false,

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
      inspectedNode: null,
      viewingHistoryId: null,
      citedSet: new Set(),
      // panelCollapsed intentionally NOT reset — user's collapse preference persists.
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
      inspectedNode: null,
      panelCollapsed: false,
      viewingHistoryId: null,
      citedSet: new Set(),
      // history intentionally NOT reset — survives "Nieuwe vraag"; hydrateHistory() repopulates on mount.
    }),

  inspectNode: (articleId) => set({ inspectedNode: articleId }),
  closeInspector: () => set({ inspectedNode: null }),
  toggleCollapse: () => set((s) => ({ panelCollapsed: !s.panelCollapsed })),
  toggleHistoryDrawer: () => set((s) => ({ historyDrawerOpen: !s.historyDrawerOpen })),
  viewHistory: (id) => set({ viewingHistoryId: id, historyDrawerOpen: false }),
  exitHistory: () => set({ viewingHistoryId: null }),

  archiveCurrent: (status) => {
    const s = get();
    if (!s.runId) return;  // nothing to archive

    const snapshot = toSnapshot({
      kgState: s.kgState,
      edgeState: s.edgeState,
      traceLog: s.traceLog,
      thinkingByAgent: s.thinkingByAgent,
      answerText: s.answerText,
      finalAnswer: s.finalAnswer,
      cases: s.cases,
      resolutions: s.resolutions,
      citedSet: s.citedSet,
    });

    const entry: HistoryEntry = {
      id: s.runId,
      question: s.question,
      timestamp: Date.now(),
      status,
      snapshot,
    };

    const next = [entry, ...s.history].slice(0, HISTORY_CAP);
    set({ history: next });

    // Fire-and-forget PUT; errors are logged, local state is authoritative.
    void putHistory(next).catch((err) => {
      console.warn('history PUT failed:', err);
    });
  },

  deleteHistory: (id) => {
    const s = get();
    const next = s.history.filter((e) => e.id !== id);
    const patch: Partial<RunState> = { history: next };
    if (s.viewingHistoryId === id) patch.viewingHistoryId = null;
    set(patch);
    void putHistory(next).catch((err) => {
      console.warn('history PUT failed:', err);
    });
  },

  clearHistory: () => {
    set({ history: [], viewingHistoryId: null });
    void putHistory([]).catch((err) => {
      console.warn('history PUT failed:', err);
    });
  },

  hydrateHistory: async () => {
    try {
      const entries = await getHistory();
      set({ history: entries });
    } catch (err) {
      console.warn('history GET failed:', err);
      set({ history: [] });
    }
  },

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
        const finalAnswer = (ev.data.final_answer as StructuredAnswer) ?? null;
        const citedSet = new Set<string>();
        if (finalAnswer && finalAnswer.kind === 'answer') {
          for (const art of finalAnswer.relevante_wetsartikelen ?? []) {
            if (art.article_id) citedSet.add(art.article_id);
          }
        }
        const next = new Map(s.kgState);
        // Demote any still-current to visited first.
        for (const [k, v] of next) {
          if (v === 'current') next.set(k, 'visited');
        }
        // Only promote cited articles to `cited`.
        for (const aid of citedSet) {
          next.set(aid, 'cited');
        }
        set({ traceLog, kgState: next, status: 'finished', finalAnswer, citedSet });
        get().archiveCurrent('finished');
        return;
      }
      case 'run_failed': {
        set({ traceLog, status: 'failed' });
        get().archiveCurrent('failed');
        return;
      }
      default: {
        set({ traceLog });
      }
    }
  },
}));

export const edgeStateKey = edgeKey;
