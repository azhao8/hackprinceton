// Where the family app's state comes from.
//
// DemoSource runs the whole day in the browser with seeded data and timers, so the
// app demos without a robot. ServerSource (server-source.ts) runs it on the Python
// server's family WebSocket (contract/web/family.md). Both implement FamilySource;
// screens don't know which one they're on.

import { clockLabel } from "./format";
import { ALERT_AT, AFTERNOON, NIGHT, seedState } from "./seed";
import type { Alert, Delivery, EventKind, FamilyState, ItemKind, MiguelMode, RequestKind, RequestStatus, TimelineEvent } from "./types";

export interface SendRequest {
  item: ItemKind;
  label: string;
  message?: string;
  voiceNote?: boolean;
}

export interface FamilySource {
  getState(): FamilyState;
  subscribe(listener: () => void): () => void;
  /** The latest check-in video frame (a data: URL), or null. Separate from the state so 5 fps video doesn't re-render every screen. */
  getFrame(): string | null;
  subscribeFrame(listener: () => void): () => void;
  send(request: SendRequest): void;
  /** "Ask Miguel": a free-text question. His answer arrives as a "message" event titled "Miguel…". */
  ask(text: string): void;
  requestCheckIn(): void;
  endCheckIn(): void;
  handleAlert(): void;
  toggleRoutine(id: string): void;
  invite(name: string, relation: string): void;
  /** Link a phone (E.164) to a member for texting Miguel; "" unlinks. */
  linkPhone(member: string, phone: string): void;
}

/** Demo-only controls, used by the hidden demo panel. */
export interface DemoControls {
  setMode(mode: MiguelMode): void;
  setCheckInAnswer(answer: "yes" | "no"): void;
  triggerAlert(): void;
  night(): void;
  reset(): void;
}

/** How long each demo step takes, in ms. Tests shorten nothing; they use fake timers. */
export const DEMO_TIMING = {
  loading: 2600,
  onTheWay: 6000,
  delivered: 13000,
  settle: 2500,
  checkInAnswer: 3800,
  answer: 1800,
};
export type DemoTiming = typeof DEMO_TIMING;

const MODE_NOTES: Record<MiguelMode, string> = {
  withMom: "In the living room with her",
  delivering: "Bringing something to her",
  charging: "On the dock while she rests",
  listening: "She's telling Miguel something",
  nightLight: "Walking with her, screen on low",
  idle: "Waiting in her room",
  offline: "Hasn't checked in for 4 min",
};

/** Minutes since midnight on the demo clock, right now. */
export function demoNow(state: FamilyState, nowMs: number): number {
  return state.clock + Math.floor((nowMs - state.clockSetAt) / 60000);
}

const ITEM_EVENT: Record<ItemKind, EventKind> = {
  water: "water",
  medication: "medication",
  note: "message",
  other: "delivery",
};

export class DemoSource implements FamilySource {
  private state: FamilyState;
  private listeners = new Set<() => void>();
  private timers: ReturnType<typeof setTimeout>[] = [];
  private seq = 0;
  private timing: DemoTiming;

  /** `timing` overrides some step lengths (NEXT_PUBLIC_DEMO_TIMING, for filming at a watchable pace). */
  constructor(
    private now: () => number = () => Date.now(),
    timing: Partial<DemoTiming> = {},
  ) {
    this.state = seedState(now());
    this.timing = { ...DEMO_TIMING, ...timing };
  }

  getState = (): FamilyState => this.state;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  // The demo check-in shows the illustration, never camera frames.
  getFrame = (): string | null => null;
  subscribeFrame = (): (() => void) => () => {};

  private set(patch: Partial<FamilyState>) {
    this.state = { ...this.state, ...patch };
    this.listeners.forEach((l) => l());
  }

  private request(kind: RequestKind, status: Omit<RequestStatus, "ref">) {
    this.set({ requests: { ...this.state.requests, [kind]: { ref: this.id("r"), ...status } } });
  }

  private later(ms: number, fn: () => void) {
    this.timers.push(setTimeout(fn, ms));
  }

  private clearTimers() {
    this.timers.forEach(clearTimeout);
    this.timers = [];
  }

  private id(prefix: string) {
    this.seq += 1;
    return `${prefix}${this.seq}`;
  }

  private minutes() {
    return demoNow(this.state, this.now());
  }

  private addEvent(event: Omit<TimelineEvent, "id" | "at">) {
    const e: TimelineEvent = { id: this.id("ev"), at: this.minutes(), ...event };
    this.set({ events: [...this.state.events, e] });
  }

  private setMode(mode: MiguelMode, note = MODE_NOTES[mode]) {
    this.set({ mode, modeNote: note });
  }

  send(request: SendRequest) {
    const delivery: Delivery = { id: this.id("d"), ...request, stage: "sent" };
    this.set({ delivery });
    this.request("send", { status: "ok", id: delivery.id });
    this.setMode("delivering", `Bringing ${request.label.toLowerCase()} to her`);
    const stage = (s: Delivery["stage"]) => {
      if (this.state.delivery?.id === delivery.id) this.set({ delivery: { ...this.state.delivery, stage: s } });
    };
    this.later(this.timing.loading, () => stage("loading"));
    this.later(this.timing.onTheWay, () => stage("onTheWay"));
    this.later(this.timing.delivered, () => {
      if (this.state.delivery?.id !== delivery.id) return;
      stage("delivered");
      this.addEvent({
        kind: ITEM_EVENT[request.item],
        title: request.item === "note" ? "Your note, delivered" : `${request.label}, from you`,
        quote: request.message,
        quoteBy: request.message ? this.state.viewer.name : undefined,
        note: request.message ? undefined : request.voiceNote ? "Miguel played your voice note." : "Miguel brought it to her chair.",
      });
      this.setMode("withMom");
      this.later(this.timing.settle, () => {
        if (this.state.delivery?.id === delivery.id) this.set({ delivery: null });
      });
    });
  }

  ask(text: string) {
    const question = text.trim();
    if (!question) return;
    this.request("ask", { status: "ok" });
    this.later(this.timing.answer, () => {
      const last = [...this.state.events].sort((a, b) => b.at - a.at)[0];
      this.addEvent({
        kind: "message",
        title: "Miguel",
        note: `She's doing well. ${this.state.modeNote}.${
          last ? ` The last thing I noted was “${last.title}” at ${clockLabel(last.at)}.` : ""
        }`,
      });
    });
  }

  requestCheckIn() {
    this.set({ checkIn: { phase: "asking" } });
    this.setMode("listening", `Asking ${this.state.resident.name} if now's a good time`);
    this.later(this.timing.checkInAnswer, () => {
      if (this.state.checkIn.phase !== "asking") return;
      if (this.state.checkInAnswer === "yes") {
        this.set({ checkIn: { phase: "live", startedAt: this.now() } });
        this.setMode("withMom", "On a call with you");
      } else {
        this.set({ checkIn: { phase: "declined" } });
        this.setMode("withMom");
      }
    });
  }

  endCheckIn() {
    const c = this.state.checkIn;
    if (c.phase === "live") {
      const mins = Math.max(1, Math.round((this.now() - c.startedAt) / 60000));
      this.addEvent({ kind: "checkIn", title: "You checked in", note: `${mins} minute${mins === 1 ? "" : "s"} together.` });
    }
    this.set({ checkIn: { phase: "idle" } });
    this.setMode("withMom");
  }

  handleAlert() {
    const alert = this.state.alert;
    if (!alert || alert.status === "handled") return;
    this.set({ alert: { ...alert, status: "handled", handledBy: this.state.viewer.name } });
    this.addEvent({
      kind: "alert",
      title: "Possible fall, handled",
      note: `${this.state.viewer.name} responded. Ruth from next door is on her way over.`,
    });
  }

  toggleRoutine(id: string) {
    this.set({ routines: this.state.routines.map((r) => (r.id === id ? { ...r, on: !r.on } : r)) });
  }

  invite(name: string, relation: string) {
    const trimmed = name.trim();
    if (!trimmed) return;
    this.set({
      members: [
        ...this.state.members,
        {
          id: this.id("m"),
          name: trimmed,
          initials: trimmed[0].toUpperCase(),
          relation: relation.trim() || "Family",
          access: "Alerts and messages",
          tone: "sky",
          invited: true,
        },
      ],
    });
  }

  linkPhone(member: string, phone: string) {
    const others = this.state.phones.filter((p) => p.member !== member && p.phone !== phone);
    this.set({ phones: phone ? [...others, { member, phone }] : others });
  }

  // ---- demo controls ----

  setModeDemo(mode: MiguelMode) {
    this.setMode(mode);
  }

  setCheckInAnswer(answer: "yes" | "no") {
    this.set({ checkInAnswer: answer });
  }

  triggerAlert() {
    const alert: Alert = {
      id: this.id("a"),
      at: ALERT_AT,
      place: "Living room, by the window",
      saw: "Margaret went from standing to the floor and hasn't gotten up.",
      heard: "I slipped. My hip hurts.",
      did: ["Asked if she was okay", "Told David", "Staying beside her"],
      status: "active",
    };
    this.set({ alert, clock: ALERT_AT, clockSetAt: this.now() });
    this.setMode("withMom", "Staying beside her");
  }

  night() {
    this.set({ clock: NIGHT, clockSetAt: this.now() });
    this.setMode("nightLight");
  }

  reset() {
    this.clearTimers();
    this.state = { ...seedState(this.now()), clock: AFTERNOON };
    this.listeners.forEach((l) => l());
  }
}

// DemoControls.setMode would clash with the private helper's name, so expose it under the interface name.
export function demoControls(source: DemoSource): DemoControls {
  return {
    setMode: (m) => source.setModeDemo(m),
    setCheckInAnswer: (a) => source.setCheckInAnswer(a),
    triggerAlert: () => source.triggerAlert(),
    night: () => source.night(),
    reset: () => source.reset(),
  };
}
