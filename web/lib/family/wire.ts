// Family app ↔ server messages, v1. Mirrors contract/web/family.md; change both together.
// The server's side is Python (server/app/api); the samples in contract/web/samples/family/
// are the shared truth, and the tests check every one of them against these types.

export const FAMILY_PROTOCOL_VERSION = 1;

export type WireMode = "with_mom" | "delivering" | "charging" | "listening" | "night_light" | "idle" | "offline";
export type WireItem = "water" | "medication" | "note" | "other";
export type WireStage = "sent" | "loading" | "on_the_way" | "delivered" | "failed";
export type WireEventKind =
  | "wake"
  | "walk"
  | "water"
  | "medication"
  | "meal"
  | "rest"
  | "message"
  | "check_in"
  | "company"
  | "night_light"
  | "delivery"
  | "alert";

/** ISO 8601 with the home's UTC offset, e.g. 2026-11-14T16:12:00-05:00. */
export type IsoTime = string;

export interface WireDelivery {
  id: string;
  item: WireItem;
  label: string;
  message?: string;
  stage: WireStage;
  detail?: string;
  photo?: string;
}

export type WireCheckIn =
  | { phase: "idle" | "asking" | "declined"; id?: string }
  | { phase: "live"; id: string; started_at: IsoTime };

export interface WireAlert {
  id: string;
  kind: "possible_fall";
  at: IsoTime;
  place?: string;
  saw: string;
  heard?: string;
  did: string[];
  status: "active" | "handled";
  handled_by?: string;
  photo?: string;
}

export interface WireEvent {
  id: string;
  at: IsoTime;
  kind: WireEventKind;
  title: string;
  note?: string;
  quote?: string;
  quote_by?: string;
  photo?: string;
}

export interface WireRoutine {
  id: string;
  kind: "water" | "medication" | "check_in" | "night_walk" | "walk";
  title: string;
  schedule: string;
  detail: string;
  on: boolean;
}

export interface WireMember {
  id: string;
  name: string;
  relation: string;
  access: string;
  you?: boolean;
  invited?: boolean;
}

export type RtcPayload = { sdp: { type: "offer" | "answer"; sdp: string } } | { candidate: Record<string, unknown> };

// ---- server → app ----

export type FamilyServerMessage =
  | {
      t: "welcome";
      v: number;
      resident: { name: string; short: string };
      viewer: { id: string; name: string };
      tz: string;
      now: IsoTime;
    }
  | {
      t: "state";
      mode: WireMode;
      mode_note: string;
      since: IsoTime;
      link: "up" | "down";
      delivery: WireDelivery | null;
      check_in: WireCheckIn;
      alert: WireAlert | null;
    }
  | { t: "events"; day: string; items: WireEvent[] }
  | ({ t: "event" } & WireEvent)
  | { t: "routines"; items: WireRoutine[] }
  | { t: "circle"; items: WireMember[] }
  | { t: "pace"; days: { date: string; mps: number }[] }
  | { t: "ack"; ref: string; ok: true; id?: string }
  | { t: "error"; ref?: string; code: string; message: string }
  | ({ t: "rtc"; call: string } & RtcPayload)
  | { t: "frame"; call: string; jpeg: string }
  /** Phones linked for texting Miguel (iMessage through Photon). `phone` is E.164. */
  | { t: "phones"; items: WirePhone[] };

/** A phone linked to a family member, for texting Miguel. */
export interface WirePhone {
  member: string;
  phone: string;
}

// ---- app → server ----

export type FamilyClientMessage =
  | { t: "hello"; v: number; token: string; viewer: string }
  | { t: "send"; ref: string; item: WireItem; label: string; message?: string; voice_note?: string }
  | { t: "check_in"; ref: string; action: "request" | "end" }
  | ({ t: "rtc"; call: string } & RtcPayload)
  | { t: "talk"; ref: string; media: string }
  | { t: "alert"; ref: string; id: string; action: "handled" }
  | { t: "routine"; ref: string; id: string; on: boolean }
  | { t: "invite"; ref: string; name: string; relation: string }
  /** "Ask Miguel": free text. Answers arrive as `event`s (kind "message", title "Miguel", note = his reply). */
  | { t: "ask"; ref: string; text: string }
  /** Link `phone` (E.164) to `member`, or unlink with "". */
  | { t: "phone"; ref: string; member: string; phone: string };

/** Longest "Ask Miguel" question, in characters. */
export const ASK_MAX = 500;

// ---- validation ----
// Small hand-written checks (no schema library): enough to drop malformed or unknown
// messages instead of crashing the app. Unknown `t` values are ignored by design.

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const str = (v: unknown): v is string => typeof v === "string";
const optStr = (v: unknown) => v === undefined || str(v);
const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/;
const iso = (v: unknown): v is string => str(v) && ISO.test(v);
const oneOf = <T extends string>(v: unknown, values: readonly T[]): v is T => str(v) && (values as readonly string[]).includes(v);

const MODES = ["with_mom", "delivering", "charging", "listening", "night_light", "idle", "offline"] as const;
const ITEMS = ["water", "medication", "note", "other"] as const;
const STAGES = ["sent", "loading", "on_the_way", "delivered", "failed"] as const;
const EVENT_KINDS = [
  "wake",
  "walk",
  "water",
  "medication",
  "meal",
  "rest",
  "message",
  "check_in",
  "company",
  "night_light",
  "delivery",
  "alert",
] as const;
const ROUTINE_KINDS = ["water", "medication", "check_in", "night_walk", "walk"] as const;

function isDelivery(v: unknown): boolean {
  return isObj(v) && str(v.id) && oneOf(v.item, ITEMS) && str(v.label) && oneOf(v.stage, STAGES) && optStr(v.message) && optStr(v.detail) && optStr(v.photo);
}

function isCheckIn(v: unknown): boolean {
  if (!isObj(v)) return false;
  if (v.phase === "live") return str(v.id) && iso(v.started_at);
  return oneOf(v.phase, ["idle", "asking", "declined"] as const) && optStr(v.id);
}

function isAlert(v: unknown): boolean {
  return (
    isObj(v) &&
    str(v.id) &&
    v.kind === "possible_fall" &&
    iso(v.at) &&
    str(v.saw) &&
    Array.isArray(v.did) &&
    v.did.every(str) &&
    oneOf(v.status, ["active", "handled"] as const) &&
    optStr(v.place) &&
    optStr(v.heard) &&
    optStr(v.handled_by) &&
    optStr(v.photo)
  );
}

function isEvent(v: unknown): boolean {
  return (
    isObj(v) &&
    str(v.id) &&
    iso(v.at) &&
    oneOf(v.kind, EVENT_KINDS) &&
    str(v.title) &&
    optStr(v.note) &&
    optStr(v.quote) &&
    optStr(v.quote_by) &&
    optStr(v.photo)
  );
}

function isRtc(v: Obj): boolean {
  if (!str(v.call)) return false;
  if (isObj(v.sdp)) return oneOf(v.sdp.type, ["offer", "answer"] as const) && str(v.sdp.sdp);
  return isObj(v.candidate);
}

function validServer(m: Obj): boolean {
  switch (m.t) {
    case "welcome":
      return (
        typeof m.v === "number" &&
        isObj(m.resident) &&
        str(m.resident.name) &&
        str(m.resident.short) &&
        isObj(m.viewer) &&
        str(m.viewer.id) &&
        str(m.viewer.name) &&
        str(m.tz) &&
        iso(m.now)
      );
    case "state":
      return (
        oneOf(m.mode, MODES) &&
        str(m.mode_note) &&
        iso(m.since) &&
        oneOf(m.link, ["up", "down"] as const) &&
        (m.delivery === null || isDelivery(m.delivery)) &&
        isCheckIn(m.check_in) &&
        (m.alert === null || isAlert(m.alert))
      );
    case "events":
      return str(m.day) && Array.isArray(m.items) && m.items.every(isEvent);
    case "event":
      return isEvent(m);
    case "routines":
      return (
        Array.isArray(m.items) &&
        m.items.every((r) => isObj(r) && str(r.id) && oneOf(r.kind, ROUTINE_KINDS) && str(r.title) && str(r.schedule) && str(r.detail) && typeof r.on === "boolean")
      );
    case "circle":
      return Array.isArray(m.items) && m.items.every((p) => isObj(p) && str(p.id) && str(p.name) && str(p.relation) && str(p.access));
    case "pace":
      return Array.isArray(m.days) && m.days.every((d) => isObj(d) && str(d.date) && typeof d.mps === "number");
    case "ack":
      return str(m.ref) && m.ok === true && optStr(m.id);
    case "error":
      return str(m.code) && str(m.message) && optStr(m.ref);
    case "rtc":
      return isRtc(m);
    case "frame":
      return str(m.call) && str(m.jpeg);
    case "phones":
      return Array.isArray(m.items) && m.items.every((p) => isObj(p) && str(p.member) && str(p.phone));
    default:
      return false;
  }
}

/** Parse one frame from the server. Malformed or unknown messages return null (and are ignored). */
export function parseFamilyServerMessage(raw: string): FamilyServerMessage | null {
  let v: unknown;
  try {
    v = JSON.parse(raw);
  } catch {
    return null;
  }
  return isObj(v) && validServer(v) ? (v as unknown as FamilyServerMessage) : null;
}

/** Check a message before the app sends it (and in tests, the contract samples). */
export function isFamilyClientMessage(v: unknown): v is FamilyClientMessage {
  if (!isObj(v)) return false;
  switch (v.t) {
    case "hello":
      return typeof v.v === "number" && str(v.token) && str(v.viewer);
    case "send":
      return str(v.ref) && oneOf(v.item, ITEMS) && str(v.label) && optStr(v.message) && optStr(v.voice_note);
    case "check_in":
      return str(v.ref) && oneOf(v.action, ["request", "end"] as const);
    case "rtc":
      return isRtc(v);
    case "talk":
      return str(v.ref) && str(v.media);
    case "alert":
      return str(v.ref) && str(v.id) && v.action === "handled";
    case "routine":
      return str(v.ref) && str(v.id) && typeof v.on === "boolean";
    case "invite":
      return str(v.ref) && str(v.name) && str(v.relation);
    case "ask":
      return str(v.ref) && str(v.text) && v.text.trim().length > 0 && v.text.length <= ASK_MAX;
    case "phone":
      return str(v.ref) && str(v.member) && str(v.phone) && (v.phone === "" || /^\+[1-9]\d{7,14}$/.test(v.phone));
    default:
      return false;
  }
}

/** A request id: unique enough within one app session. */
export function makeRef(now = Date.now(), seq = 0): string {
  return `r-${Math.floor(now / 1000)}-${seq}`;
}
