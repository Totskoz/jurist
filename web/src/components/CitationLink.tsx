import { useActiveRun } from '../hooks/useActiveRun';

interface Props {
  kind: 'artikel' | 'uitspraak';
  id: string;
  children: React.ReactNode;
}

export default function CitationLink({ kind, id, children }: Props) {
  const { resolutions } = useActiveRun();
  const resolved = resolutions.find((r) => r.kind === kind && r.id === id);
  if (!resolved) {
    return (
      <span style={{
        color: 'var(--text-tertiary)',
        fontStyle: 'italic',
        opacity: 0.7,
      }}>
        {children}
      </span>
    );
  }
  return (
    <a
      href={resolved.resolved_url}
      target="_blank"
      rel="noreferrer"
      style={{
        color: 'var(--accent)',
        textDecoration: 'none',
        borderBottom: '1px dashed rgba(245, 194, 74, 0.4)',
      }}
    >
      {children}
    </a>
  );
}
