import Graph from './components/graph/Graph';
import Panel from './components/panel/Panel';
import ClusterLegend from './components/graph/ClusterLegend';

export default function App() {
  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      background: 'linear-gradient(to bottom, var(--bg-gradient-top), var(--bg-gradient-bot))',
      overflow: 'hidden',
    }}>
      <Graph />
      <ClusterLegend />
      <Panel />
    </div>
  );
}
