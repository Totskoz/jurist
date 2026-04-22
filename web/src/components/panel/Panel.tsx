import { useEffect } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { useRunStore } from '../../state/runStore';
import { usePhase } from '../../hooks/usePhase';
import CollapseHandle from './CollapseHandle';
import IdlePhase from './phases/IdlePhase';
import RunningPhase from './phases/RunningPhase';
import AnswerReadyPhase from './phases/AnswerReadyPhase';
import InspectNodePhase from './phases/InspectNodePhase';

const PANEL_WIDTH = 560;
const COLLAPSE_OFFSET = PANEL_WIDTH + 48;

export default function Panel() {
  const phase = usePhase();
  const collapsed = useRunStore((s) => s.panelCollapsed);
  const inspectedNode = useRunStore((s) => s.inspectedNode);
  const closeInspector = useRunStore((s) => s.closeInspector);

  useEffect(() => {
    if (!inspectedNode) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeInspector();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [inspectedNode, closeInspector]);

  return (
    <motion.aside
      animate={{ x: collapsed ? COLLAPSE_OFFSET : 0 }}
      transition={{ type: 'spring', stiffness: 180, damping: 22 }}
      style={{
        position: 'fixed',
        top: 16,
        right: 16,
        bottom: 16,
        width: PANEL_WIDTH,
        background: 'var(--panel-surface)',
        backdropFilter: 'blur(20px)',
        border: '1px solid var(--panel-border)',
        borderRadius: 14,
        color: 'var(--text-primary)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        zIndex: 5,
      }}
    >
      <CollapseHandle />
      <div style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden', padding: 28 }}>
        <AnimatePresence mode="wait">
          <motion.div
            key={phase}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -12 }}
            transition={{ type: 'spring', stiffness: 220, damping: 24 }}
          >
            {phase === 'idle' && <IdlePhase />}
            {phase === 'running' && <RunningPhase />}
            {phase === 'answer-ready' && <AnswerReadyPhase />}
            {phase === 'inspecting-node' && <InspectNodePhase />}
          </motion.div>
        </AnimatePresence>
      </div>
    </motion.aside>
  );
}
