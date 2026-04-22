import { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { useRunStore } from '../../state/runStore';
import { usePhase } from '../../hooks/usePhase';
import { computePanelWidth, PANEL_COLLAPSE_OVERSHOOT } from '../../layout';
import CollapseHandle from './CollapseHandle';
import IdlePhase from './phases/IdlePhase';
import RunningPhase from './phases/RunningPhase';
import AnswerReadyPhase from './phases/AnswerReadyPhase';
import InspectNodePhase from './phases/InspectNodePhase';
import HistoryIcon from './HistoryIcon';
import HistoryDrawer from './HistoryDrawer';
import ViewingHistoryPill from './ViewingHistoryPill';

export default function Panel() {
  const phase = usePhase();
  const collapsed = useRunStore((s) => s.panelCollapsed);
  const inspectedNode = useRunStore((s) => s.inspectedNode);
  const closeInspector = useRunStore((s) => s.closeInspector);

  // Panel width tracks ~1/3 of the viewport, clamped to a sensible band.
  const [panelWidth, setPanelWidth] = useState(() =>
    computePanelWidth(typeof window !== 'undefined' ? window.innerWidth : 1280),
  );
  useEffect(() => {
    const onResize = () => setPanelWidth(computePanelWidth(window.innerWidth));
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  useEffect(() => {
    if (!inspectedNode) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeInspector();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [inspectedNode, closeInspector]);

  const hydrateHistory = useRunStore((s) => s.hydrateHistory);
  useEffect(() => {
    void hydrateHistory();
  }, [hydrateHistory]);

  const collapseOffset = panelWidth + PANEL_COLLAPSE_OVERSHOOT;

  return (
    <motion.aside
      animate={{ x: collapsed ? collapseOffset : 0 }}
      transition={{ type: 'spring', stiffness: 180, damping: 22 }}
      style={{
        position: 'fixed',
        top: 16,
        right: 16,
        bottom: 16,
        width: panelWidth,
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
      <HistoryIcon />
      <CollapseHandle />
      <div style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden', padding: 28 }}>
        <ViewingHistoryPill />
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
      <HistoryDrawer />
    </motion.aside>
  );
}
