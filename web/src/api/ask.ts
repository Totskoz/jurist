export interface AskResponse {
  question_id: string;
}

export async function ask(question: string): Promise<AskResponse> {
  const res = await fetch('/api/ask', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ question }),
  });
  if (!res.ok) {
    throw new Error(`ask failed: ${res.status}`);
  }
  return res.json();
}
