import { useRunStore, type RunStatus } from '../state/runStore';

export type PhaseKey = 'idle' | 'running' | 'answer-ready' | 'inspecting-node';

export function derivePhase(status: RunStatus, inspectedNode: string | null): PhaseKey {
  if (inspectedNode) return 'inspecting-node';
  if (status === 'running') return 'running';
  if (status === 'finished' || status === 'failed') return 'answer-ready';
  return 'idle';
}

export function usePhase(): PhaseKey {
  const status = useRunStore((s) => s.status);
  const inspectedNode = useRunStore((s) => s.inspectedNode);
  return derivePhase(status, inspectedNode);
}
