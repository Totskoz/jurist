export function formatRelativeNl(ts: number, now: number = Date.now()): string {
  const diffMs = Math.max(0, now - ts);
  const sec = Math.floor(diffMs / 1000);
  if (sec < 30) return 'net nu';
  if (sec < 60) return `${sec} seconden geleden`;
  const min = Math.floor(sec / 60);
  if (min < 60) return min === 1 ? '1 minuut geleden' : `${min} minuten geleden`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return hr === 1 ? '1 uur geleden' : `${hr} uur geleden`;
  const day = Math.floor(hr / 24);
  if (day === 1) return 'gisteren';
  return `${day} dagen geleden`;
}
