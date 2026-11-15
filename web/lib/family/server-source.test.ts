import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { familyWsUrl, mediaOrigin, resolveMedia, wantsDemo } from "./config";
import { CONNECTING_NOTE, RECONNECT_MS, RECONNECTING_NOTE, ServerSource, dayLabelOf, homeMinutes, type SocketLike } from "./server-source";
import { isFamilyClientMessage } from "./wire";

const dir = join(__dirname, "..", "..", "..", "contract", "web", "samples", "family");
const sample = (name: string) => JSON.parse(readFileSync(join(dir, `${name}.json`), "utf8"));

/** A WebSocket the test drives by hand. */
class FakeSocket implements SocketLike {
  readyState = 0;
  sent: Record<string, unknown>[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: unknown }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) {}
  send(data: string) {
    this.sent.push(JSON.parse(data));
  }
  close() {
    this.drop();
  }
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  receive(msg: object | string) {
    this.onmessage?.({ data: typeof msg === "string" ? msg : JSON.stringify(msg) });
  }
  drop() {
    if (this.readyState === 3) return;
    this.readyState = 3;
    this.onclose?.();
  }
  last() {
    return this.sent[this.sent.length - 1];
  }
}

const WS_URL = "ws://192.168.4.20:8080/family/ws";
const MEDIA = "http://192.168.4.20:8080";

describe("ServerSource", () => {
  let sockets: FakeSocket[];
  let source: ServerSource;
  const now = 1_731_618_720_000;

  beforeEach(() => {
    vi.useFakeTimers();
    sockets = [];
    source = new ServerSource({
      url: WS_URL,
      token: "secret",
      viewer: "m1",
      now: () => now,
      createSocket: (url) => {
        const s = new FakeSocket(url);
        sockets.push(s);
        return s;
      },
    });
  });
  afterEach(() => {
    source.stop();
    vi.useRealTimers();
  });

  const socket = () => sockets[sockets.length - 1];

  /** Subscribe (which connects), open, and get the server's welcome and snapshots. */
  const connect = (...snapshots: string[]) => {
    const changes = vi.fn();
    source.subscribe(changes);
    socket().open();
    socket().receive(sample("welcome"));
    for (const name of snapshots) socket().receive(sample(name));
    return changes;
  };

  it("shows Miguel offline and doesn't connect until someone subscribes", () => {
    expect(source.getState().mode).toBe("offline");
    expect(source.getState().modeNote).toBe(CONNECTING_NOTE);
    expect(source.getState().events).toEqual([]);
    expect(sockets).toHaveLength(0);
  });

  it("says hello first, with the token and viewer", () => {
    source.subscribe(() => {});
    expect(socket().url).toBe(WS_URL);
    socket().open();
    expect(socket().sent).toEqual([{ t: "hello", v: 1, token: "secret", viewer: "m1" }]);
    expect(isFamilyClientMessage(socket().sent[0])).toBe(true);
  });

  it("maps welcome and the snapshots onto the app's state", () => {
    const changes = connect("state-with-mom", "events", "routines", "circle", "pace");
    const s = source.getState();
    expect(changes).toHaveBeenCalled();
    expect(s.resident).toEqual({ name: "Margaret", short: "Mom", home: "Margaret's home" });
    expect(s.viewer).toEqual({ id: "m1", name: "Sarah" });
    expect(s.clock).toBe(16 * 60 + 12);
    expect(s.clockSetAt).toBe(now);
    expect(s.dayLabel).toBe("Saturday, 14 November");
    expect(s.mode).toBe("withMom");
    expect(s.modeNote).toBe("In the living room with her");
    expect(s.events.map((e) => [e.id, e.at, e.kind])).toEqual([
      ["e1", 7 * 60 + 40, "wake"],
      ["e3", 9 * 60, "medication"],
      ["e4", 10 * 60 + 30, "water"],
      ["e8", 14 * 60 + 10, "walk"],
    ]);
    expect(s.events[2]).toMatchObject({ quote: "Morning, Mom! Drink up.", quoteBy: "Sarah" });
    expect(s.routines.map((r) => [r.id, r.kind])).toEqual([
      ["r1", "water"],
      ["r2", "medication"],
      ["r4", "nightWalk"],
    ]);
    expect(s.members.map((m) => [m.name, m.initials, m.you ?? false, m.invited ?? false])).toEqual([
      ["Sarah", "S", true, false],
      ["David", "D", false, false],
      ["Dr. Patel", "P", false, true],
    ]);
    expect(s.pace).toEqual([0.71, 0.74, 0.69, 0.73, 0.72, 0.75, 0.74]);
  });

  it("keeps the seed's routines, circle and pace until the server sends them", () => {
    connect("state-with-mom");
    const s = source.getState();
    expect(s.routines.length).toBeGreaterThan(0);
    expect(s.members.find((m) => m.you)?.name).toBe("Sarah");
    expect(s.pace).toHaveLength(7);
  });

  it("maps a delivery's stage, and a failure with its reason", () => {
    connect("state-delivering");
    expect(source.getState().mode).toBe("delivering");
    expect(source.getState().delivery).toMatchObject({ id: "d7", item: "water", label: "Water", message: "Love you, Mom", stage: "loading" });

    const state = sample("state-delivering");
    socket().receive({ ...state, delivery: { ...state.delivery, stage: "on_the_way" } });
    expect(source.getState().delivery?.stage).toBe("onTheWay");

    socket().receive({ ...state, mode: "with_mom", delivery: { ...state.delivery, stage: "failed", detail: "Couldn't find her" } });
    expect(source.getState().delivery).toMatchObject({ stage: "failed", detail: "Couldn't find her" });

    socket().receive({ ...state, delivery: { ...state.delivery, stage: "delivered", photo: "/family/media/abc" } });
    expect(source.getState().delivery?.photo).toBe(`${MEDIA}/family/media/abc`);
  });

  it("maps a possible fall, with the photo on the server's origin", () => {
    connect("state-alert");
    expect(source.getState().alert).toEqual({
      id: "a1",
      at: 16 * 60 + 21,
      place: "Living room, by the window",
      saw: "Margaret went from standing to the floor and hasn't gotten up.",
      heard: "I slipped. My hip hurts.",
      did: ["Asked if she was okay", "Told David", "Staying beside her"],
      status: "active",
      handledBy: undefined,
      photo: `${MEDIA}/family/media/7f3c1a9e5b2d4c6f8a0e1b2c3d4e5f60`,
    });
  });

  it("adds each new event once, and replaces one sent again", () => {
    connect("events");
    socket().receive(sample("event"));
    socket().receive({ ...sample("event"), title: "Water, from Sarah" });
    const added = source.getState().events.filter((e) => e.id === "e11");
    expect(added).toHaveLength(1);
    expect(added[0]).toMatchObject({ kind: "water", at: 16 * 60 + 19, title: "Water, from Sarah", photo: `${MEDIA}/family/media/0c9d8e7f6a5b4c3d2e1f0a9b8c7d6e5f` });
  });

  it("ignores malformed and unknown messages", () => {
    connect("state-with-mom");
    const before = source.getState();
    socket().receive("{nope");
    socket().receive({ t: "weather", sky: "blue" });
    socket().receive({ ...sample("state-with-mom"), mode: "dancing" });
    expect(source.getState()).toBe(before);
  });

  it("send: tracks the request until the ack, which carries the delivery id", () => {
    connect("state-with-mom");
    source.send({ item: "water", label: "Water", message: "Love you, Mom", voiceNote: false });
    const msg = socket().last();
    expect(msg).toMatchObject({ t: "send", item: "water", label: "Water", message: "Love you, Mom" });
    expect(isFamilyClientMessage(msg)).toBe(true);
    expect(source.getState().requests.send).toEqual({ ref: msg.ref, status: "waiting" });

    socket().receive({ t: "ack", ref: msg.ref, ok: true, id: "d7" });
    expect(source.getState().requests.send).toMatchObject({ status: "ok", id: "d7" });
  });

  it("send: shows the server's error, e.g. busy", () => {
    connect("state-delivering");
    source.send({ item: "water", label: "Water" });
    const ref = socket().last().ref as string;
    socket().receive({ ...sample("error"), ref });
    expect(source.getState().requests.send).toMatchObject({
      status: "error",
      code: "busy",
      message: "Miguel is already bringing her water. Try again when he's back.",
    });
  });

  it("an answer to an older request doesn't overwrite a newer one", () => {
    connect("state-with-mom");
    source.send({ item: "water", label: "Water" });
    const first = socket().last().ref;
    source.send({ item: "note", label: "Your note", message: "Hi" });
    socket().receive({ t: "ack", ref: first, ok: true, id: "d1" });
    expect(source.getState().requests.send?.status).toBe("waiting");
  });

  it("requests fail right away while the socket is down", () => {
    source.subscribe(() => {});
    source.send({ item: "water", label: "Water" });
    expect(socket().sent).toEqual([]);
    expect(source.getState().requests.send).toMatchObject({ status: "error", code: "offline" });
  });

  it("ask: sends the question; Miguel's answer arrives as a message event", () => {
    connect("events");
    source.ask("  Did Mom eat lunch today?  ");
    const msg = socket().last();
    expect(msg).toMatchObject({ t: "ask", text: "Did Mom eat lunch today?" });
    expect(isFamilyClientMessage(msg)).toBe(true);
    source.ask("   ");
    expect(socket().last()).toBe(msg);

    socket().receive({ t: "ack", ref: msg.ref, ok: true });
    socket().receive({ t: "event", id: "e20", at: "2026-11-14T16:30:00-05:00", kind: "message", title: "Miguel", note: "Yes, soup at 12:30." });
    expect(source.getState().requests.ask?.status).toBe("ok");
    expect(source.getState().events.at(-1)).toMatchObject({ kind: "message", title: "Miguel", note: "Yes, soup at 12:30.", at: 16 * 60 + 30 });
  });

  it("check-in: asks, goes live, shows camera frames for this call only, then clears them", () => {
    connect("state-with-mom");
    source.requestCheckIn();
    expect(socket().last()).toMatchObject({ t: "check_in", action: "request" });

    const frames = vi.fn();
    source.subscribeFrame(frames);
    socket().receive(sample("frame")); // not live yet: ignored
    expect(source.getFrame()).toBeNull();

    socket().receive(sample("state-check-in"));
    expect(source.getState().checkIn).toEqual({ phase: "live", id: "c3", startedAt: Date.parse("2026-11-14T16:20:00-05:00") });
    socket().receive(sample("frame"));
    expect(source.getFrame()).toBe(`data:image/jpeg;base64,${sample("frame").jpeg}`);
    socket().receive({ t: "frame", call: "c9", jpeg: "other" });
    expect(source.getFrame()).toBe(`data:image/jpeg;base64,${sample("frame").jpeg}`);
    expect(frames).toHaveBeenCalledTimes(1);

    socket().receive(sample("state-with-mom"));
    expect(source.getState().checkIn.phase).toBe("idle");
    expect(source.getFrame()).toBeNull();
  });

  it("ending a check-in goes back to idle right away and tells the server", () => {
    connect("state-check-in");
    source.endCheckIn();
    expect(source.getState().checkIn.phase).toBe("idle");
    expect(socket().last()).toMatchObject({ t: "check_in", action: "end" });
  });

  it("alert: marks it handled through the server", () => {
    connect("state-alert");
    source.handleAlert();
    const msg = socket().last();
    expect(msg).toMatchObject({ t: "alert", id: "a1", action: "handled" });
    const state = sample("state-alert");
    socket().receive({ ...state, alert: { ...state.alert, status: "handled", handled_by: "Sarah" } });
    expect(source.getState().alert).toMatchObject({ status: "handled", handledBy: "Sarah" });
  });

  it("routine: flips right away, and flips back if the server says no", () => {
    connect("routines");
    source.toggleRoutine("r1");
    expect(source.getState().routines.find((r) => r.id === "r1")?.on).toBe(false);
    const msg = socket().last();
    expect(msg).toMatchObject({ t: "routine", id: "r1", on: false });
    socket().receive({ t: "error", ref: msg.ref, code: "not_found", message: "No such routine." });
    expect(source.getState().routines.find((r) => r.id === "r1")?.on).toBe(true);
    expect(source.getState().requests.routine?.status).toBe("error");
  });

  it("invite: shows them as invited right away; the server's circle replaces the list", () => {
    connect("circle");
    source.invite("  Ana ", "Granddaughter");
    expect(socket().last()).toMatchObject({ t: "invite", name: "Ana", relation: "Granddaughter" });
    expect(source.getState().members.at(-1)).toMatchObject({ name: "Ana", invited: true });
    const circle = sample("circle");
    socket().receive({ ...circle, items: [...circle.items, { id: "m5", name: "Ana", relation: "Granddaughter", access: "Alerts and messages", invited: true }] });
    expect(source.getState().members.filter((m) => m.name === "Ana").map((m) => m.id)).toEqual(["m5"]);
  });

  it("reconnects with backoff, shows offline meanwhile, and fails what was waiting", () => {
    connect("state-with-mom");
    source.send({ item: "water", label: "Water" });
    socket().drop();
    expect(source.getState().mode).toBe("offline");
    expect(source.getState().modeNote).toBe(RECONNECTING_NOTE);
    expect(source.getState().requests.send).toMatchObject({ status: "error", code: "offline" });

    expect(sockets).toHaveLength(1);
    vi.advanceTimersByTime(RECONNECT_MS[0]);
    expect(sockets).toHaveLength(2);
    socket().drop(); // refused again: waits longer
    vi.advanceTimersByTime(RECONNECT_MS[1] - 1);
    expect(sockets).toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(sockets).toHaveLength(3);

    // The server answers every new hello with a full snapshot.
    socket().open();
    expect(socket().sent[0]).toMatchObject({ t: "hello" });
    socket().receive(sample("welcome"));
    socket().receive(sample("state-with-mom"));
    expect(source.getState().mode).toBe("withMom");

    socket().drop(); // after a welcome, the backoff starts over
    vi.advanceTimersByTime(RECONNECT_MS[0]);
    expect(sockets).toHaveLength(4);
  });

  it("says so when the token is refused", () => {
    source.subscribe(() => {});
    socket().open();
    socket().receive({ t: "error", code: "unauthorized", message: "Wrong token." });
    socket().drop();
    expect(source.getState().mode).toBe("offline");
    expect(source.getState().modeNote).toMatch(/token/);
  });

  it("stop() closes the socket for good", () => {
    connect("state-with-mom");
    source.stop();
    vi.advanceTimersByTime(60_000);
    expect(sockets).toHaveLength(1);
  });
});

describe("wire helpers", () => {
  it("reads home-local times and day labels", () => {
    expect(homeMinutes("2026-11-14T16:12:00-05:00")).toBe(16 * 60 + 12);
    expect(homeMinutes("2026-11-14T00:05:00Z")).toBe(5);
    expect(dayLabelOf("2026-11-14")).toBe("Saturday, 14 November");
    expect(dayLabelOf("2026-11-15T08:00:00-05:00")).toBe("Sunday, 15 November");
  });
});

describe("config", () => {
  it("picks the demo from ?demo or the build setting", () => {
    expect(wantsDemo("?demo", false)).toBe(true);
    expect(wantsDemo("?item=note&demo=1", false)).toBe(true);
    expect(wantsDemo("", false)).toBe(false);
    expect(wantsDemo(null, false)).toBe(false);
    expect(wantsDemo(null, true)).toBe(true);
  });

  it("finds the WebSocket on the page's host, or the configured URL", () => {
    expect(familyWsUrl({ protocol: "http:", hostname: "192.168.4.20" }, undefined)).toBe("ws://192.168.4.20:8080/family/ws");
    expect(familyWsUrl({ protocol: "https:", hostname: "miguel.local" }, undefined)).toBe("wss://miguel.local:8443/family/ws");
    expect(familyWsUrl({ protocol: "https:", hostname: "x" }, "wss://tunnel.example/family/ws")).toBe("wss://tunnel.example/family/ws");
  });

  it("resolves media against the server, not the Next app", () => {
    expect(mediaOrigin("ws://192.168.4.20:8080/family/ws")).toBe("http://192.168.4.20:8080");
    expect(mediaOrigin("wss://miguel.local:8443/family/ws")).toBe("https://miguel.local:8443");
    expect(mediaOrigin("wss://tunnel.example/family/ws")).toBe("https://tunnel.example");
    expect(resolveMedia("/family/media/abc", "https://miguel.local:8443")).toBe("https://miguel.local:8443/family/media/abc");
    expect(resolveMedia("https://cdn.example/x.jpg", "http://h:8080")).toBe("https://cdn.example/x.jpg");
  });
});
