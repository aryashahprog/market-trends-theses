const HOUR = 3600000, DAY = 24 * HOUR;

export function staticSchedule(status, now) {
  const cutoff = now - (status.stale_grace_minutes ?? 90) * 60000;
  const slots = now >= Date.parse(status.now) ? (status.slots ?? []).map(Date.parse) : [];
  const next = slots.find((at) => at > now);
  const due = slots.filter((at) => at <= cutoff).at(-1);
  if (next !== undefined && due !== undefined) {
    return { due: new Date(due).toISOString(), next: new Date(next).toISOString() };
  }
  const clock = new Intl.DateTimeFormat("en-US", { timeZone: status.timezone || "America/New_York", year: "numeric",
    month: "numeric", day: "numeric", hour: "numeric", hourCycle: "h23", minute: "numeric", second: "numeric" });
  const asWallTime = (at) => {
    const p = Object.fromEntries(clock.formatToParts(at).map(({ type, value }) => [type, Number(value)]));
    return Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second);
  };
  const hours = status.refresh_hours || [8, 16];
  const around = (at) => {
    const midnight = Math.floor(asWallTime(at) / DAY) * DAY;
    return [-1, 0, 1].flatMap((offset) => hours.map((h) => midnight + offset * DAY + h * HOUR))
      .map((wallTime) => wallTime - (asWallTime(wallTime) - wallTime));
  };
  return { due: new Date(around(cutoff).filter((at) => at <= cutoff).at(-1)).toISOString(),
    next: new Date(next ?? around(now).find((at) => at > now)).toISOString() };
}

export const count = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
export const sourceCount = (evidence) => new Set(evidence.map((e) => e.canonical_url || e.url).filter(Boolean)).size;
export const evidenceLabel = (s) => `${count(s.evidence.length, "claim")} · ${count(sourceCount(s.evidence), "source")}`;
