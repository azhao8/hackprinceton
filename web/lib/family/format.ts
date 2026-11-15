// Small formatting helpers for the demo clock.

/** "4:12 pm" from minutes since midnight. */
export function clockLabel(minutes: number): string {
  const m = ((minutes % 1440) + 1440) % 1440;
  const h24 = Math.floor(m / 60);
  const mm = m % 60;
  const h = h24 % 12 === 0 ? 12 : h24 % 12;
  return `${h}:${mm.toString().padStart(2, "0")} ${h24 < 12 ? "am" : "pm"}`;
}

/** "morning" | "afternoon" | "evening" | "night" */
export function partOfDay(minutes: number): "morning" | "afternoon" | "evening" | "night" {
  const h = Math.floor((((minutes % 1440) + 1440) % 1440) / 60);
  if (h < 5) return "night";
  if (h < 12) return "morning";
  if (h < 17) return "afternoon";
  if (h < 22) return "evening";
  return "night";
}

/** "2 min" / "1 hr 5 min" between two minute stamps. */
export function sinceLabel(from: number, to: number): string {
  const d = Math.max(0, to - from);
  if (d < 1) return "just now";
  if (d < 60) return `${d} min`;
  const h = Math.floor(d / 60);
  const r = d % 60;
  return r ? `${h} hr ${r} min` : `${h} hr`;
}
