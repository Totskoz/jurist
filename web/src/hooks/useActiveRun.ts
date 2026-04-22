import { useMemo } from 'react';
import { useRunStore } from '../state/runStore';
import type { HistoryEntry } from '../state/historyApi';
import { fromSnapshot, type ActiveRunView } from '../state/snapshot';

/**
 * Pure selector — given the live slice view, the viewingHistoryId, and the
 * history array, returns whichever view the UI should render. Extracted as a
 * pure function for unit testing; the hook below is a thin React wrapper.
 */
export function selectActiveRun(
  liveView: ActiveRunView,
  viewingHistoryId: string | null,
  history: HistoryEntry[],
): ActiveRunView {
  if (viewingHistoryId === null) return liveView;
  const entry = history.find((e) => e.id === viewingHistoryId);
  if (!entry) return liveView;
  return fromSnapshot(entry.snapshot);
}

export function useActiveRun(): ActiveRunView {
  const kgState = useRunStore((s) => s.kgState);
  const edgeState = useRunStore((s) => s.edgeState);
  const traceLog = useRunStore((s) => s.traceLog);
  const thinkingByAgent = useRunStore((s) => s.thinkingByAgent);
  const answerText = useRunStore((s) => s.answerText);
  const finalAnswer = useRunStore((s) => s.finalAnswer);
  const cases = useRunStore((s) => s.cases);
  const resolutions = useRunStore((s) => s.resolutions);
  const citedSet = useRunStore((s) => s.citedSet);
  const viewingHistoryId = useRunStore((s) => s.viewingHistoryId);
  const history = useRunStore((s) => s.history);

  const liveView: ActiveRunView = {
    kgState, edgeState, traceLog, thinkingByAgent,
    answerText, finalAnswer, cases, resolutions, citedSet,
  };

  return useMemo(
    () => selectActiveRun(liveView, viewingHistoryId, history),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [viewingHistoryId, history, kgState, edgeState, traceLog, thinkingByAgent,
     answerText, finalAnswer, cases, resolutions, citedSet],
  );
}
