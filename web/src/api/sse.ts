import type { TraceEvent } from '../types/events';

export interface Subscription {
  close: () => void;
}

export function subscribe(
  questionId: string,
  onEvent: (ev: TraceEvent) => void,
  onError?: (err: Event) => void,
): Subscription {
  const es = new EventSource(`/api/stream?question_id=${encodeURIComponent(questionId)}`);
  es.onmessage = (msg) => {
    try {
      const ev = JSON.parse(msg.data) as TraceEvent;
      onEvent(ev);
      if (ev.type === 'run_finished' || ev.type === 'run_failed') {
        es.close();
      }
    } catch (e) {
      console.error('bad SSE payload', msg.data, e);
    }
  };
  es.onerror = (err) => {
    if (onError) onError(err);
  };
  return { close: () => es.close() };
}
