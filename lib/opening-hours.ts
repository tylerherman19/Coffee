// Evaluate the supported weekly OSM syntax in the shops' local timezone.
// Seasonal dates, holidays and malformed rules are unknown rather than closed.
export function isOpenNow(hours: string | null, at = new Date()): boolean | null {
  if (!hours) return null;
  if (hours.trim() === '24/7') return true;
  if (/^(off|closed)$/.test(hours.trim())) return false;
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: 'America/Chicago', weekday: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(at);
  const days = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'];
  const weekday = parts.find(p => p.type === 'weekday')?.value;
  const today = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].indexOf(weekday || '');
  const minute = Number(parts.find(p => p.type === 'hour')?.value) * 60 + Number(parts.find(p => p.type === 'minute')?.value);
  let open = false;
  for (const rule of hours.split(';')) {
    const match = rule.trim().match(/^(?:(Mo|Tu|We|Th|Fr|Sa|Su)([A-Za-z,-]*)\s+)?(off|closed|\d{2}:\d{2}-\d{2}:\d{2}(?:,\d{2}:\d{2}-\d{2}:\d{2})*)$/);
    if (!match) return null;
    const activeDays = new Set<number>();
    for (const token of (match[1] ? match[1] + match[2] : 'Mo-Su').split(',')) {
      const [from, to = from] = token.split('-');
      const a = days.indexOf(from), b = days.indexOf(to);
      if (a < 0 || b < 0) return null;
      for (let d = a; ; d = (d + 1) % 7) { activeDays.add(d); if (d === b) break; }
    }
    if (match[3] === 'off' || match[3] === 'closed') {
      if (activeDays.has(today)) open = false;
      continue;
    }
    for (const span of match[3].split(',')) {
      const [startText, endText] = span.split('-');
      const minutes = (v: string) => { const [h, m] = v.split(':').map(Number); return h <= 24 && m < 60 && (h !== 24 || m === 0) ? h * 60 + m : NaN; };
      const start = minutes(startText), end = minutes(endText);
      if (!Number.isFinite(start) || !Number.isFinite(end) || start === 1440) return null;
      if (end < start) {
        if ((activeDays.has(today) && minute >= start) || (activeDays.has((today + 6) % 7) && minute < end)) open = true;
      } else if (activeDays.has(today) && minute >= start && minute < end) open = true;
    }
  }
  return open;
}
