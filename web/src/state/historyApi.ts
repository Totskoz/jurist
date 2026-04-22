import type { RunSnapshot } from './snapshot';

export interface HistoryEntry {
  id: string;
  question: string;
  timestamp: number;
  status: 'finished' | 'failed';
  snapshot: RunSnapshot;
}

interface HistoryFile {
  version: 1;
  entries: HistoryEntry[];
}

export async function getHistory(): Promise<HistoryEntry[]> {
  const resp = await fetch('/api/history');
  if (!resp.ok) throw new Error(`GET /api/history failed: ${resp.status}`);
  const body: HistoryFile = await resp.json();
  if (body.version !== 1) return [];
  return body.entries;
}

export async function putHistory(entries: HistoryEntry[]): Promise<void> {
  const resp = await fetch('/api/history', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ version: 1, entries }),
  });
  if (!resp.ok) throw new Error(`PUT /api/history failed: ${resp.status}`);
}
