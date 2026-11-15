// The family app's data model. The demo source (source.ts) and the server source
// (server-source.ts) both produce a FamilyState; screens only read this.

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
  /** Photo URL, ready for an <img> (e.g. her with what Miguel brought). */
  photo?: string;
}

export type DeliveryStage = "sent" | "loading" | "onTheWay" | "delivered" | "failed";

export interface Delivery {
  id: string;
  item: ItemKind;
  /** What it is, in words ("Water", "Her reading glasses"). */
  label: string;
  message?: string;
  voiceNote?: boolean;
  stage: DeliveryStage;
  /** Why it failed, in words ("Couldn't find her"). */
  detail?: string;
  /** Photo URL of her with it, once delivered. */
  photo?: string;
}

/** `id` is the server's call id (matches `frame.call`); the demo leaves it out. */
export type CheckIn =
  | { phase: "idle"; id?: string }
  | { phase: "asking"; id?: string }
  | { phase: "live"; id?: string; startedAt: number }
  | { phase: "declined"; id?: string };

export interface Alert {
  id: string;
  at: number;
  place?: string;
  saw: string;
  /** What she said when Miguel asked if she was okay, if anything. */
  heard?: string;
  did: string[];
  status: "active" | "handled";
  /** Who answered it. */
  handledBy?: string;
  photo?: string;
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

/** Requests the app makes; the latest of each kind is tracked in FamilyState.requests. */
export type RequestKind = "send" | "ask" | "checkIn" | "alert" | "routine" | "invite";

export interface RequestStatus {
  ref: string;
  status: "waiting" | "ok" | "error";
  /** What the request created (a delivery id), once it worked. */
  id?: string;
  /** Why it didn't work: the server's code ("busy") and a line for people. */
  code?: string;
  message?: string;
}

export interface FamilyState {
  resident: { name: string; short: string; home: string };
  /** The family member using this app (circle member id). */
  viewer: { id: string; name: string };
  mode: MiguelMode;
  /** One short line under the mode ("In the living room with Ruth"). */
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
  /** The latest request of each kind and how it went. */
  requests: Partial<Record<RequestKind, RequestStatus>>;
}
