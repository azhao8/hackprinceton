// "Miguel's summary" of a day, built only from what's in the timeline: a short read of the day
// (an interpretation, and labeled as one on screen) and the facts behind it, grouped. No
// diagnosis, no guessing at how she feels; just what Miguel noted, in order.

import { clockLabel, partOfDay } from "./format";
import type { FamilyState, TimelineEvent } from "./types";

const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

/** Something the family sent or did themselves (water from you, a note from David, a check-in). */
export const fromFamily = (e: TimelineEvent) =>
  e.kind === "checkIn" || /from you/i.test(e.title) || (!!e.quoteBy && e.quoteBy !== "Miguel") || (e.kind === "message" && !e.title.startsWith("Miguel"));

const list = (parts: string[]) =>
  parts.length > 1 ? `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}` : (parts[0] ?? "");

interface Bit {
  at: number;
  rank: number;
  /** For a list after a colon: "a walk with Miguel". */
  noun: string;
  /** For "she …": "went for a walk with Miguel". */
  verb: string;
}

/** The parts of the day worth a mention, most telling first (rank), one of each kind. */
function bits(events: TimelineEvent[], viewer: string, walkedBefore: boolean, morning: boolean): Bit[] {
  const out = new Map<string, Bit>();
  const add = (key: string, b: Bit) => !out.has(key) && out.set(key, b);
  for (const e of events) {
    if (e.kind === "walk") {
      const again = walkedBefore || out.has("walk");
      add("walk", { at: e.at, rank: 0, noun: again ? "another walk" : "a walk with Miguel", verb: again ? "went for another walk" : "went for a walk with Miguel" });
    } else if (e.kind === "medication") {
      add("meds", { at: e.at, rank: 1, noun: morning ? "her morning pills" : "her pills", verb: "took her pills" });
    } else if (e.kind === "rest") {
      add("rest", { at: e.at, rank: 1, noun: "a rest", verb: "rested" });
    } else if (e.kind === "company") {
      const what = e.title.charAt(0).toLowerCase() + e.title.slice(1);
      add("company", { at: e.at, rank: 2, noun: what, verb: `had ${what}` });
    } else if ((e.kind === "water" || e.kind === "delivery") && /from you/i.test(e.title)) {
      add("sent", { at: e.at, rank: 2, noun: "a glass of water from you", verb: "got the water you sent" });
    } else if (e.kind === "checkIn") {
      add("call", { at: e.at, rank: 3, noun: "a call with you", verb: "talked with you" });
    } else if (e.kind === "message" && e.quoteBy && e.quoteBy !== viewer && !e.title.startsWith("Miguel")) {
      add("note", { at: e.at, rank: 4, noun: `a voice note from ${e.quoteBy}`, verb: `heard from ${e.quoteBy}` });
    }
  }
  return [...out.values()];
}

/** The most telling `n`, back in the order they happened. */
const pick = (b: Bit[], n: number) => [...b].sort((x, y) => x.rank - y.rank || x.at - y.at).slice(0, n).sort((x, y) => x.at - y.at);

export interface PaceDay {
  /** "S", "M", …; today is the last one. */
  initial: string;
  day: string;
  value: number;
  today: boolean;
}

export interface DaySummary {
  /** Two sentences: how the day went, from the timeline. Shown as Miguel's read, not as fact. */
  read: string;
  walks: TimelineEvent[];
  pace: PaceDay[];
  paceToday: number;
  paceUsual: number;
  /** Her own routine: waking, pills, meals, rest. */
  routine: TimelineEvent[];
  /** What the family sent or did. */
  family: TimelineEvent[];
}

export function summarize(s: FamilyState): DaySummary {
  const events = [...s.events].filter((e) => e.kind !== "alert").sort((a, b) => a.at - b.at);
  const viewer = s.viewer.name;
  const mom = s.resident.short;
  const wake = events.find((e) => e.kind === "wake");
  const morning = events.filter((e) => partOfDay(e.at) === "morning");
  const later = events.filter((e) => partOfDay(e.at) !== "morning" && partOfDay(e.at) !== "night");

  const walkedInMorning = morning.some((e) => e.kind === "walk");
  const am = pick(bits(morning, viewer, false, true), 4);
  const pm = pick(bits(later, viewer, walkedInMorning, false), 4);
  const sentences: string[] = [];
  const active = walkedInMorning ? "a fairly active morning" : "a quiet morning";
  if (wake || am.length) {
    const what = am.length ? `: ${list(am.map((b) => b.noun))}` : "";
    sentences.push(`${mom} ${wake ? `was up at ${clockLabel(wake.at)} and ` : ""}had ${active}${what}.`);
  }
  if (pm.length) sentences.push(`In the afternoon she ${list(pm.map((b) => b.verb))}.`);
  const read = sentences.join(" ") || `A quiet day so far. What Miguel notices will show up here.`;

  const pace = s.pace;
  const paceToday = pace[pace.length - 1] ?? 0;
  const paceUsual = pace.length > 1 ? pace.slice(0, -1).reduce((a, b) => a + b, 0) / (pace.length - 1) : paceToday;
  const todayIndex = Math.max(0, DAYS.indexOf(s.dayLabel.split(",")[0]));
  const paceDays: PaceDay[] = pace.map((value, i) => {
    const d = DAYS[(todayIndex - (pace.length - 1 - i) + 7 * 4) % 7];
    return { initial: d[0], day: d, value, today: i === pace.length - 1 };
  });

  return {
    read,
    walks: events.filter((e) => e.kind === "walk"),
    pace: paceDays,
    paceToday,
    paceUsual,
    routine: events.filter((e) => e.kind === "wake" || e.kind === "medication" || e.kind === "meal" || e.kind === "rest"),
    family: events.filter(fromFamily),
  };
}

