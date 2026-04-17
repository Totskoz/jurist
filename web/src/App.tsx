import { useState } from 'react';
import AnswerPanel from './components/AnswerPanel';
import KGPanel from './components/KGPanel';
import TracePanel from './components/TracePanel';
import { ask } from './api/ask';
import { subscribe } from './api/sse';
import { useRunStore } from './state/runStore';

const LOCKED_QUESTION =
  'Mijn verhuurder wil de huur met 15% verhogen per volgend jaar, mag dat?';

export default function App() {
  const [input, setInput] = useState(LOCKED_QUESTION);
  const status = useRunStore((s) => s.status);
  const start = useRunStore((s) => s.start);
  const apply = useRunStore((s) => s.apply);

  const submit = async () => {
    const q = input.trim();
    if (!q) return;
    const { question_id } = await ask(q);
    start(question_id, q);
    subscribe(question_id, (ev) => apply(ev));
  };

  return (
    <div className="h-full flex flex-col">
      <header className="flex gap-2 items-center p-3 border-b">
        <h1 className="font-semibold text-lg">Jurist</h1>
        <input
          className="flex-1 border rounded px-3 py-2"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={status === 'running'}
        />
        <button
          className="px-4 py-2 rounded bg-blue-600 text-white disabled:bg-gray-400"
          onClick={() => void submit()}
          disabled={status === 'running'}
        >
          {status === 'running' ? 'Running…' : 'Ask'}
        </button>
      </header>

      <main className="grid grid-cols-2 gap-3 p-3 flex-1 min-h-0">
        <KGPanel />
        <TracePanel />
      </main>

      <section className="p-3 border-t max-h-96 overflow-y-auto">
        <AnswerPanel />
      </section>
    </div>
  );
}
