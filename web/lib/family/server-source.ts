// The family app on the real server: one WebSocket to /family/ws (contract/web/family.md).
//
// The app sends `hello` first; the server answers with `welcome` and full snapshots (`state`,
// `events`, `routines`, `circle`, `pace`), then sends `state` whenever it changes and each new
// `event`. State comes whole, so this only maps wire messages (snake_case, ISO times with the
// home's offset) onto FamilyState (camelCase, minutes since midnight at her home). Anything the
// server hasn't sent keeps its seed value (pace, routines and circle until they arrive).
// When the socket is down, Miguel shows as offline and it reconnects with backoff.

import { mediaOrigin, resolveMedia } from "./config";
import { seedState } from "./seed";
import type { FamilySource, SendRequest } from "./source";
import type {
  Alert,
  CheckIn,
  Delivery,
  EventKind,
  FamilyState,
  Member,
  MiguelMode,
  RequestKind,
  RequestStatus,
  Routine,
  TimelineEvent,
  Tone,
} from "./types";
import {
  FAMILY_PROTOCOL_VERSION,
  isFamilyClientMessage,
  makeRef,
  parseFamilyServerMessage,
  type FamilyClientMessage,
  type FamilyServerMessage,
  type WireAlert,
  type WireCheckIn,
  type WireDelivery,
  type WireEvent,
  type WireMember,
  type WireMode,
  type WireRoutine,
  type WireStage,
} from "./wire";

/** The bits of a browser WebSocket this uses, so tests can pass a fake. */
export interface SocketLike {
  readonly readyState: number;
  send(data: string): void;
  close(): void;
  onopen: (() => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onclose: (() => void) | null;
  onerror: (() => void) | null;
}

export interface ServerSourceOptions {
  url: string;
  token: string;
  /** Circle member id of the person using this app. */
  viewer: string;
  createSocket?: (url: string) => SocketLike;
  now?: () => number;
}

const OPEN = 1;

/** Reconnect delays in ms; the last one repeats. Reset once the server says `welcome`. */
export const RECONNECT_MS = [500, 1000, 2000, 5000, 10000];

export const CONNECTING_NOTE = "Connecting to Miguel…";
export const RECONNECTING_NOTE = "Can't reach Miguel right now. Trying again…";
const UNAUTHORIZED_NOTE = "Miguel didn't accept this app's family token.";
const OFFLINE_MESSAGE = "Can't reach Miguel right now. Try again in a moment.";
const LOST_MESSAGE = "Lost the connection before Miguel answered. Try again in a moment.";

const MODE: Record<WireMode, MiguelMode> = {
  with_mom: "withMom",
  delivering: "delivering",
  charging: "charging",
  listening: "listening",
  night_light: "nightLight",
  idle: "idle",
  offline: "offline",
};

const STAGE: Record<WireStage, Delivery["stage"]> = {
  sent: "sent",
  loading: "loading",
  on_the_way: "onTheWay",
  delivered: "delivered",
  failed: "failed",
};

const EVENT_KIND: Record<WireEvent["kind"], EventKind> = {
  wake: "wake",
  walk: "walk",
  water: "water",
  medication: "medication",
  meal: "meal",
  rest: "rest",
  message: "message",
  check_in: "checkIn",
  company: "company",
  night_light: "nightLight",
  delivery: "delivery",
  alert: "alert",
};

const ROUTINE_KIND: Record<WireRoutine["kind"], Routine["kind"]> = {
  water: "water",
  medication: "medication",
  check_in: "checkIn",
  night_walk: "nightWalk",
  walk: "walk",
};

const TONES: Tone[] = ["sun", "sky", "ember", "sand"];
const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

/** Minutes since midnight in the home's time zone: the wire's times carry its offset, so read the clock digits. */
export function homeMinutes(iso: string): number {
  return Number(iso.slice(11, 13)) * 60 + Number(iso.slice(14, 16));
}

/** "Saturday, 14 November" from "2026-11-14" (or an ISO time). */
export function dayLabelOf(date: string): string {
  const [y, m, d] = date.slice(0, 10).split("-").map(Number);
  const day = new Date(Date.UTC(y, m - 1, d));
  return `${WEEKDAYS[day.getUTCDay()]}, ${d} ${MONTHS[m - 1]}`;
}

function initialsOf(name: string): string {
  const words = name.trim().split(/\s+/);
  // "Dr. Patel" → "P"
  const word = words.length > 1 && words[0].endsWith(".") ? words[1] : words[0];
  return (word?.[0] ?? "?").toUpperCase();
}

/** What the app shows before the server has said anything: Miguel offline, no day yet; the rest from the seed. */
export function serverBootState(now: number): FamilyState {
  const seed = seedState(now);
  const local = new Date(now);
  return {
    ...seed,
    mode: "offline",
    modeNote: CONNECTING_NOTE,
    clock: now ? local.getHours() * 60 + local.getMinutes() : seed.clock,
    clockSetAt: now,
    dayLabel: "Today",
    events: [],
    delivery: null,
    checkIn: { phase: "idle" },
    alert: null,
  };
}

interface Pending {
  kind: RequestKind;
  /** Puts back an optimistic change if the request fails. */
  undo?: () => void;
}

export class ServerSource implements FamilySource {
  private state: FamilyState;
  private listeners = new Set<() => void>();
  private frameListeners = new Set<() => void>();
  private frame: string | null = null;
  private ws: SocketLike | null = null;
  private signedIn = false;
  private started = false;
  private stopped = false;
  private attempts = 0;
  private retry: ReturnType<typeof setTimeout> | undefined;
  private seq = 0;
  private pending = new Map<string, Pending>();
  private readonly media: string;
  private readonly now: () => number;
  private readonly createSocket: (url: string) => SocketLike;

  constructor(private opts: ServerSourceOptions) {
    this.now = opts.now ?? (() => Date.now());
    this.createSocket = opts.createSocket ?? ((url) => new WebSocket(url) as unknown as SocketLike);
    this.media = mediaOrigin(opts.url);
    const boot = serverBootState(this.now());
    this.state = { ...boot, viewer: { ...boot.viewer, id: opts.viewer } };
  }

  getState = (): FamilyState => this.state;

  /** The first subscriber opens the socket (so the server's prerender never does). */
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    this.start();
    return () => this.listeners.delete(listener);
  };

  getFrame = (): string | null => this.frame;

  subscribeFrame = (listener: () => void): (() => void) => {
    this.frameListeners.add(listener);
    return () => this.frameListeners.delete(listener);
  };

  start() {
    if (this.started || this.stopped) return;
    this.started = true;
    this.connect();
  }

  /** Close for good (tests, hot reload). */
  stop() {
    this.stopped = true;
    clearTimeout(this.retry);
    const ws = this.ws;
    this.ws = null;
    ws?.close();
  }

  // ---- connection ----

  private connect() {
    let ws: SocketLike;
    try {
      ws = this.createSocket(this.opts.url);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;
    ws.onopen = () => {
      if (this.ws !== ws) return;
      ws.send(JSON.stringify({ t: "hello", v: FAMILY_PROTOCOL_VERSION, token: this.opts.token, viewer: this.opts.viewer }));
    };
    ws.onmessage = (ev) => {
      if (this.ws !== ws || typeof ev.data !== "string") return;
      const msg = parseFamilyServerMessage(ev.data);
      if (msg) this.receive(msg);
    };
    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.ws = null;
      this.down();
      this.scheduleReconnect();
    };
    ws.onerror = () => {}; // onclose follows
  }

  private scheduleReconnect() {
    if (this.stopped) return;
    const delay = RECONNECT_MS[Math.min(this.attempts, RECONNECT_MS.length - 1)];
    this.attempts += 1;
    this.retry = setTimeout(() => this.connect(), delay);
  }

  /** The socket closed: Miguel shows offline, and requests still waiting won't get an answer. */
  private down() {
    this.signedIn = false;
    for (const [ref, p] of this.pending) {
      p.undo?.();
      if (this.state.requests[p.kind]?.ref === ref) {
        this.setRequest(p.kind, { ref, status: "error", code: "offline", message: LOST_MESSAGE });
      }
    }
    this.pending.clear();
    // Keep saying the token was refused, rather than "trying again", until a welcome.
    const note = this.state.modeNote === UNAUTHORIZED_NOTE ? UNAUTHORIZED_NOTE : RECONNECTING_NOTE;
    this.set({ mode: "offline", modeNote: note });
    this.setFrame(null);
  }

  // ---- server → app ----

  private receive(m: FamilyServerMessage) {
    switch (m.t) {
      case "welcome":
        this.signedIn = true;
        this.attempts = 0;
        this.set({
          resident: { name: m.resident.name, short: m.resident.short, home: `${m.resident.name}'s home` },
          viewer: { id: m.viewer.id, name: m.viewer.name },
          clock: homeMinutes(m.now),
          clockSetAt: this.now(),
          dayLabel: dayLabelOf(m.now),
          modeNote: this.state.mode === "offline" ? "Connected. Waiting for Miguel…" : this.state.modeNote,
        });
        return;
      case "state": {
        const checkIn = this.checkIn(m.check_in);
        this.set({
          mode: MODE[m.mode],
          modeNote: m.mode_note,
          delivery: m.delivery ? this.delivery(m.delivery) : null,
          checkIn,
          alert: m.alert ? this.alert(m.alert) : null,
        });
        if (checkIn.phase !== "live") this.setFrame(null);
        return;
      }
      case "events":
        this.set({ events: m.items.map((e) => this.event(e)), dayLabel: dayLabelOf(m.day) });
        return;
      case "event": {
        const e = this.event(m);
        const i = this.state.events.findIndex((x) => x.id === e.id);
        const events = i < 0 ? [...this.state.events, e] : this.state.events.map((x, j) => (j === i ? e : x));
        this.set({ events });
        return;
      }
      case "routines":
        this.set({ routines: m.items.map(routine) });
        return;
      case "circle":
        this.set({ members: m.items.map((p, i) => this.member(p, i)) });
        return;
      case "phones":
        this.set({ phones: m.items.map((p) => ({ member: p.member, phone: p.phone })) });
        return;
      case "pace":
        // The day screen needs at least two days to draw a trend; keep the seed until then.
        if (m.days.length >= 2) this.set({ pace: m.days.map((d) => d.mps) });
        return;
      case "ack":
        this.settle(m.ref, { status: "ok", id: m.id });
        return;
      case "error":
        if (m.ref !== undefined && this.pending.has(m.ref)) {
          this.pending.get(m.ref)?.undo?.();
          this.settle(m.ref, { status: "error", code: m.code, message: m.message });
        } else if (m.code === "unauthorized") {
          this.set({ mode: "offline", modeNote: UNAUTHORIZED_NOTE });
        }
        return;
      case "frame": {
        const c = this.state.checkIn;
        if (c.phase === "live" && (!c.id || c.id === m.call)) this.setFrame(`data:image/jpeg;base64,${m.jpeg}`);
        return;
      }
      case "rtc":
        return; // WebRTC isn't wired up; the server uses the JPEG fallback (`frame`).
    }
  }

  private delivery(d: WireDelivery): Delivery {
    return {
      id: d.id,
      item: d.item,
      label: d.label,
      message: d.message,
      stage: STAGE[d.stage],
      detail: d.detail,
      photo: d.photo ? resolveMedia(d.photo, this.media) : undefined,
    };
  }

  private checkIn(c: WireCheckIn): CheckIn {
    if (c.phase === "live") return { phase: "live", id: c.id, startedAt: Date.parse(c.started_at) };
    return { phase: c.phase, id: c.id };
  }

  private alert(a: WireAlert): Alert {
    return {
      id: a.id,
      at: homeMinutes(a.at),
      place: a.place,
      saw: a.saw,
      heard: a.heard,
      did: a.did,
      status: a.status,
      handledBy: a.handled_by,
      photo: a.photo ? resolveMedia(a.photo, this.media) : undefined,
    };
  }

  private event(e: WireEvent): TimelineEvent {
    return {
      id: e.id,
      at: homeMinutes(e.at),
      kind: EVENT_KIND[e.kind],
      title: e.title,
      note: e.note,
      quote: e.quote,
      quoteBy: e.quote_by,
      photo: e.photo ? resolveMedia(e.photo, this.media) : undefined,
    };
  }

  private member(p: WireMember, i: number): Member {
    const known = this.state.members.find((x) => x.id === p.id);
    return {
      id: p.id,
      name: p.name,
      initials: known?.name === p.name ? known.initials : initialsOf(p.name),
      relation: p.relation,
      access: p.access,
      tone: known?.tone ?? TONES[i % TONES.length],
      you: p.you,
      invited: p.invited,
    };
  }

  // ---- app → server ----

  send(request: SendRequest) {
    // Voice notes need an upload first (POST /family/media); not wired up yet, so only text goes.
    this.request("send", (ref) => ({
      t: "send",
      ref,
      item: request.item,
      label: request.label,
      ...(request.message ? { message: request.message } : {}),
    }));
  }

  ask(text: string) {
    const question = text.trim();
    if (!question) return;
    this.request("ask", (ref) => ({ t: "ask", ref, text: question }));
  }

  requestCheckIn() {
    this.request("checkIn", (ref) => ({ t: "check_in", ref, action: "request" }));
  }

  endCheckIn() {
    // Back to idle right away (the server's next `state` confirms it), so "Okay" and "End" feel instant.
    const before = this.state.checkIn;
    if (before.phase === "idle") return;
    this.set({ checkIn: { phase: "idle" } });
    this.setFrame(null);
    this.request(
      "checkIn",
      (ref) => ({ t: "check_in", ref, action: "end" }),
      () => this.set({ checkIn: before }),
    );
  }

  handleAlert() {
    const alert = this.state.alert;
    if (!alert || alert.status === "handled") return;
    this.request("alert", (ref) => ({ t: "alert", ref, id: alert.id, action: "handled" }));
  }

  toggleRoutine(id: string) {
    const routine = this.state.routines.find((r) => r.id === id);
    if (!routine) return;
    const flip = (on: boolean) => this.set({ routines: this.state.routines.map((r) => (r.id === id ? { ...r, on } : r)) });
    flip(!routine.on);
    this.request("routine", (ref) => ({ t: "routine", ref, id, on: !routine.on }), () => flip(routine.on));
  }

  invite(name: string, relation: string) {
    const trimmed = name.trim();
    if (!trimmed) return;
    const rel = relation.trim() || "Family";
    const tempId = `invite-${this.seq + 1}`;
    // Shown as invited right away; the server's `circle` replaces the list.
    this.set({
      members: [
        ...this.state.members,
        { id: tempId, name: trimmed, initials: initialsOf(trimmed), relation: rel, access: "Alerts and messages", tone: "sky", invited: true },
      ],
    });
    this.request(
      "invite",
      (ref) => ({ t: "invite", ref, name: trimmed, relation: rel }),
      () => this.set({ members: this.state.members.filter((m) => m.id !== tempId) }),
    );
  }

  linkPhone(member: string, phone: string) {
    const before = this.state.phones;
    // Shown right away; the server's `phones` confirms it (or the error puts it back).
    const others = before.filter((p) => p.member !== member && p.phone !== phone);
    this.set({ phones: phone ? [...others, { member, phone }] : others });
    this.request("phone", (ref) => ({ t: "phone", ref, member, phone }), () => this.set({ phones: before }));
  }

  /** Send one request with a fresh ref and track it until `ack` or `error`. */
  private request(kind: RequestKind, build: (ref: string) => FamilyClientMessage, undo?: () => void) {
    this.seq += 1;
    const ref = makeRef(this.now(), this.seq);
    const msg = build(ref);
    const ws = this.ws;
    if (!isFamilyClientMessage(msg) || !this.signedIn || !ws || ws.readyState !== OPEN) {
      undo?.();
      this.setRequest(kind, { ref, status: "error", code: "offline", message: OFFLINE_MESSAGE });
      return;
    }
    ws.send(JSON.stringify(msg));
    this.pending.set(ref, { kind, undo });
    this.setRequest(kind, { ref, status: "waiting" });
  }

  private settle(ref: string, status: Omit<RequestStatus, "ref">) {
    const p = this.pending.get(ref);
    if (!p) return;
    this.pending.delete(ref);
    // An older request's answer doesn't overwrite a newer one of the same kind.
    if (this.state.requests[p.kind]?.ref === ref) this.setRequest(p.kind, { ref, ...status });
  }

  private setRequest(kind: RequestKind, status: RequestStatus) {
    this.set({ requests: { ...this.state.requests, [kind]: status } });
  }

  // ---- plumbing ----

  private set(patch: Partial<FamilyState>) {
    this.state = { ...this.state, ...patch };
    this.listeners.forEach((l) => l());
  }

  private setFrame(frame: string | null) {
    if (frame === this.frame) return;
    this.frame = frame;
    this.frameListeners.forEach((l) => l());
  }
}

function routine(r: WireRoutine): Routine {
  return { id: r.id, kind: ROUTINE_KIND[r.kind], title: r.title, schedule: r.schedule, detail: r.detail, on: r.on };
}
