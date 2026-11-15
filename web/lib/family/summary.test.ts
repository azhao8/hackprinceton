import { describe, expect, it } from "vitest";
import { seedState } from "./seed";
import { summarize } from "./summary";

describe("summarize", () => {
  it("tells the seeded day in two sentences, from the timeline only", () => {
    const s = summarize(seedState(0));
    expect(s.read).toBe(
      "Mom was up at 7:40 am and had a fairly active morning: a walk with Miguel, her morning pills, a glass of water from you and a call with you. " +
        "In the afternoon she rested, went for another walk, heard from David and had tea with Ruth.",
    );
  });

  it("mentions the water you sent once it's in her day, before a later call", () => {
    const state = seedState(0);
    state.events = [
      ...state.events,
      { id: "x", at: 16 * 60 + 12, kind: "water", title: "Water, from you", quote: "Love you, Mom ❤️", quoteBy: "Sarah" },
      { id: "y", at: 16 * 60 + 26, kind: "checkIn", title: "You checked in", note: "6 minutes together." },
    ];
    const s = summarize(state);
    expect(s.read).toContain("In the afternoon she rested, went for another walk, had tea with Ruth and got the water you sent.");
    expect(s.family.map((e) => e.title)).toEqual(["Water, from you", "You checked in", "Voice note played", "Water, from you", "You checked in"]);
  });

  it("labels the week's walking pace with days, today last", () => {
    const s = summarize(seedState(0));
    expect(s.pace.map((d) => d.initial).join("")).toBe("SMTWTFS");
    expect(s.pace[6]).toMatchObject({ day: "Saturday", today: true, value: 0.74 });
    expect(s.paceUsual).toBeCloseTo(0.723, 3);
  });

  it("says it's a quiet day when nothing has happened yet", () => {
    const state = seedState(0);
    state.events = [];
    expect(summarize(state).read).toMatch(/quiet day/);
  });
});
