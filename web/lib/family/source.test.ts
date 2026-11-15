import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clockLabel, partOfDay, sinceLabel } from "./format";
import { AFTERNOON, NIGHT } from "./seed";
import { DEMO_TIMING, DemoSource, demoControls, demoNow } from "./source";

describe("DemoSource", () => {
  let now = 1_000_000;
  let source: DemoSource;

  beforeEach(() => {
    vi.useFakeTimers();
    now = 1_000_000;
    source = new DemoSource(() => now);
  });
  afterEach(() => vi.useRealTimers());

  const advance = (ms: number) => {
    now += ms;
    vi.advanceTimersByTime(ms);
  };

  it("starts on Saturday afternoon with Mom and a seeded day", () => {
    const s = source.getState();
    expect(s.mode).toBe("withMom");
    expect(demoNow(s, now)).toBe(AFTERNOON);
    expect(s.events.length).toBeGreaterThan(5);
  });

  it("walks a delivery through every stage, then logs it and goes back to Mom", () => {
    const changes = vi.fn();
    source.subscribe(changes);
    source.send({ item: "water", label: "Water", message: "Love you, Mom" });
    expect(source.getState().mode).toBe("delivering");
    expect(source.getState().delivery?.stage).toBe("sent");

    advance(DEMO_TIMING.loading);
    expect(source.getState().delivery?.stage).toBe("loading");
    advance(DEMO_TIMING.onTheWay - DEMO_TIMING.loading);
    expect(source.getState().delivery?.stage).toBe("onTheWay");
    advance(DEMO_TIMING.delivered - DEMO_TIMING.onTheWay);

    const s = source.getState();
    expect(s.delivery?.stage).toBe("delivered");
    expect(s.mode).toBe("withMom");
    const last = s.events[s.events.length - 1];
    expect(last).toMatchObject({ kind: "water", title: "Water, from you", quote: "Love you, Mom", quoteBy: "Sarah" });

    advance(DEMO_TIMING.settle);
    expect(source.getState().delivery).toBeNull();
    expect(changes).toHaveBeenCalled();
  });

  it("a newer delivery replaces an older one without the old timers interfering", () => {
    source.send({ item: "water", label: "Water" });
    advance(1000);
    source.send({ item: "other", label: "Her reading glasses" });
    advance(DEMO_TIMING.delivered + DEMO_TIMING.settle);
    const added = source.getState().events.filter((e) => e.at >= AFTERNOON && e.id.startsWith("ev"));
    expect(added.map((e) => e.title)).toEqual(["Her reading glasses, from you"]);
  });

  it("a send reports which delivery it started", () => {
    source.send({ item: "water", label: "Water" });
    const s = source.getState();
    expect(s.requests.send).toMatchObject({ status: "ok", id: s.delivery?.id });
  });

  it("ask: Miguel answers with a message event", () => {
    source.ask("How's Mom?");
    expect(source.getState().requests.ask?.status).toBe("ok");
    advance(DEMO_TIMING.answer);
    const last = source.getState().events.at(-1);
    expect(last).toMatchObject({ kind: "message", title: "Miguel" });
    expect(last?.note).toMatch(/^She's doing well\./);
  });

  it("check-in: asks first, then connects when she says yes and logs the call", () => {
    source.requestCheckIn();
    expect(source.getState().checkIn.phase).toBe("asking");
    expect(source.getState().mode).toBe("listening");
    advance(DEMO_TIMING.checkInAnswer);
    expect(source.getState().checkIn.phase).toBe("live");
    advance(3 * 60_000);
    source.endCheckIn();
    const s = source.getState();
    expect(s.checkIn.phase).toBe("idle");
    expect(s.events[s.events.length - 1]).toMatchObject({ kind: "checkIn", note: "3 minutes together." });
  });

  it("check-in: respects a no", () => {
    demoControls(source).setCheckInAnswer("no");
    source.requestCheckIn();
    advance(DEMO_TIMING.checkInAnswer);
    expect(source.getState().checkIn.phase).toBe("declined");
    expect(source.getState().mode).toBe("withMom");
  });

  it("possible fall: raises an alert, then logs it once handled", () => {
    demoControls(source).triggerAlert();
    expect(source.getState().alert?.status).toBe("active");
    source.handleAlert();
    source.handleAlert();
    const s = source.getState();
    expect(s.alert?.status).toBe("handled");
    expect(s.events.filter((e) => e.kind === "alert")).toHaveLength(1);
  });

  it("night mode moves the clock to 2 am and turns on the night-light", () => {
    demoControls(source).night();
    const s = source.getState();
    expect(s.mode).toBe("nightLight");
    expect(demoNow(s, now)).toBe(NIGHT);
  });

  it("routines toggle and invites join the circle as invited", () => {
    source.toggleRoutine("r5");
    expect(source.getState().routines.find((r) => r.id === "r5")?.on).toBe(true);
    source.invite("  Ana ", "Granddaughter");
    source.invite("   ", "nobody");
    const added = source.getState().members.filter((m) => m.name === "Ana");
    expect(added).toHaveLength(1);
    expect(added[0]).toMatchObject({ initials: "A", relation: "Granddaughter", invited: true });
  });

  it("reset brings back the seeded day and cancels pending timers", () => {
    source.send({ item: "water", label: "Water" });
    demoControls(source).reset();
    advance(DEMO_TIMING.delivered + DEMO_TIMING.settle);
    const s = source.getState();
    expect(s.delivery).toBeNull();
    expect(s.mode).toBe("withMom");
    expect(s.events.some((e) => e.title === "Water, from you" && e.at > AFTERNOON)).toBe(false);
  });
});

describe("format", () => {
  it("labels times, parts of day and durations", () => {
    expect(clockLabel(AFTERNOON)).toBe("4:12 pm");
    expect(clockLabel(0)).toBe("12:00 am");
    expect(clockLabel(12 * 60 + 5)).toBe("12:05 pm");
    expect(partOfDay(NIGHT)).toBe("night");
    expect(partOfDay(9 * 60)).toBe("morning");
    expect(partOfDay(AFTERNOON)).toBe("afternoon");
    expect(partOfDay(19 * 60)).toBe("evening");
    expect(sinceLabel(100, 100)).toBe("just now");
    expect(sinceLabel(100, 165)).toBe("1 hr 5 min");
  });
});
