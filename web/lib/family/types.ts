// The family app's data model. The demo source (demo-source.ts) and a future
// server source both produce a FamilyState; screens only read this.

/** What Miguel is doing right now, as the family sees it. */
export type MiguelMode =
  | "withMom"
  | "delivering"
  | "charging"
  | "listening"
  | "nightLight"
  | "idle"
  | "offline";

/** Face expressions. Mostly follow the mode; "talking" and "excited" are momentary. */
export type Expression =
  | "happy"
  | "excited"
  | "focused"
  | "sleepy"
  | "listening"
  | "concerned"
  | "night"
  | "offline";

export type ItemKind = "water" | "medication" | "note" | "other";

export type EventKind =
  | "wake"
  | "walk"
  | "water"
  | "medication"
  | "meal"
  | "rest"
  | "message"
  | "checkIn"
  | "company"
  | "nightLight"
  | "delivery"
  | "alert";

export interface TimelineEvent {
  id: string;
  /** Minutes since midnight on the demo day. */
  at: number;
  kind: EventKind;
  title: string;
  note?: string;
  /** Something someone said, shown as a quote. */
  quote?: string;
  quoteBy?: string;
}

export type DeliveryStage = "sent" | "loading" | "onTheWay" | "delivered";

export interface Delivery {
  id: string;
  item: ItemKind;
  /** What it is, in words ("Water", "Her reading glasses"). */
  label: string;
  message?: string;
  voiceNote?: boolean;
  stage: DeliveryStage;
}

export type CheckIn =
  | { phase: "idle" }
  | { phase: "asking" }
  | { phase: "live"; startedAt: number }
  | { phase: "declined" };

export interface Alert {
  id: string;
  at: number;
  place: string;
  saw: string;
  heard: string;
  did: string[];
  status: "active" | "handled";
}

export interface Routine {
  id: string;
  kind: "water" | "medication" | "checkIn" | "nightWalk" | "walk";
  title: string;
  schedule: string;
  detail: string;
  on: boolean;
}

export type Tone = "sun" | "sky" | "ember" | "sand";

export interface Member {
  id: string;
  name: string;
  initials: string;
  relation: string;
  access: string;
  tone: Tone;
  you?: boolean;
  invited?: boolean;
}

export interface FamilyState {
  resident: { name: string; short: string; home: string };
  viewer: { name: string };
  mode: MiguelMode;
  /** One short line under the mode ("In the lounge with Ruth"). */
  modeNote: string;
  /** Demo clock: minutes since midnight at `clockSetAt` (epoch ms). */
  clock: number;
  clockSetAt: number;
  dayLabel: string;
  events: TimelineEvent[];
  delivery: Delivery | null;
  checkIn: CheckIn;
  /** What happens when the family asks to check in (demo only). */
  checkInAnswer: "yes" | "no";
  alert: Alert | null;
  routines: Routine[];
  members: Member[];
  /** Walking pace over the last 7 days, m/s, oldest first. */
  pace: number[];
}
