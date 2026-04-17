import { useRunStore } from '../state/runStore';

interface Props {
  kind: 'artikel' | 'uitspraak';
  id: string;
  children: React.ReactNode;
}

export default function CitationLink({ kind, id, children }: Props) {
  const resolved = useRunStore((s) => s.resolutions.find((r) => r.kind === kind && r.id === id));
  if (!resolved) {
    return <span className="text-gray-500 italic">{children}</span>;
  }
  return (
    <a
      href={resolved.resolved_url}
      target="_blank"
      rel="noreferrer"
      className="text-blue-700 underline hover:text-blue-900"
    >
      {children}
    </a>
  );
}
