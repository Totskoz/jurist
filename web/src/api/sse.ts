import type { TraceEvent } from '../types/events';

export interface Subscription {
  close: () => void;
}

export function subscribe(
  questionId: string,
  onEvent: (ev: TraceEvent) => void,
  onError?: (err: Event) => void,
): Subscription {
  let terminalSeen = false;
  let explicitlyClosed = false;

  const es = new EventSource(`/api/stream?question_id=${encodeURIComponent(questionId)}`);

  es.onmessage = (msg) => {
    try {
      const ev = JSON.parse(msg.data) as TraceEvent;
      if (ev.type === 'run_finished' || ev.type === 'run_failed') {
        terminalSeen = true;
      }
      onEvent(ev);
      if (terminalSeen) {
        explicitlyClosed = true;
        es.close();
      }
    } catch (e) {
      console.error('bad SSE payload', msg.data, e);
    }
  };

  es.onerror = (err) => {
    // If the stream died without a terminal event and we didn't close it ourselves,
    // synthesise a client-side run_failed{connection_lost}.
    if (!terminalSeen && !explicitlyClosed && es.readyState === EventSource.CLOSED) {
      onEvent({
        type: 'run_failed',
        agent: null,
        run_id: questionId,
        ts: new Date().toISOString(),
        data: { reason: 'connection_lost' },
      } as unknown as TraceEvent);
      terminalSeen = true;
    }
    if (onError) onError(err);
  };

  return {
    close: () => {
      explicitlyClosed = true;
      es.close();
    },
  };
}
