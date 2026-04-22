import { useRunStore, type RunStatus } from '../state/runStore';

export type PhaseKey = 'idle' | 'running' | 'answer-ready' | 'inspecting-node';

export function derivePhase(
  status: RunStatus,
  inspectedNode: string | null,
  viewingHistoryId: string | null,
): PhaseKey {
  if (inspectedNode) return 'inspecting-node';
  if (viewingHistoryId !== null) return 'answer-ready';
  if (status === 'running') return 'running';
  if (status === 'finished' || status === 'failed') return 'answer-ready';
  return 'idle';
}

export function usePhase(): PhaseKey {
  const status = useRunStore((s) => s.status);
  const inspectedNode = useRunStore((s) => s.inspectedNode);
  const viewingHistoryId = useRunStore((s) => s.viewingHistoryId);
  return derivePhase(status, inspectedNode, viewingHistoryId);
}
