import { describe, expect, it } from "vitest";
import { maskPhone, normalizePhone } from "./format";
import { isFamilyClientMessage } from "./wire";

describe("normalizePhone", () => {
  it.each([
    ["+1 215 555 0123", "+12155550123"],
    ["(215) 555-0123", "+12155550123"],
    ["2155550123", "+12155550123"],
    ["1-215-555-0123", "+12155550123"],
    ["+44 20 7946 0958", "+442079460958"],
  ])("%s -> %s", (typed, e164) => {
    expect(normalizePhone(typed)).toBe(e164);
  });

  it.each(["", "555-0123", "hello", "+0123456789", "+1234567890123456"])("rejects %j", (typed) => {
    expect(normalizePhone(typed)).toBeNull();
  });
});

describe("phone linking", () => {
  it("masks all but the last four digits", () => {
    expect(maskPhone("+12155550123")).toBe("•••• 0123");
  });

  it("accepts a link and an unlink, not a malformed number", () => {
    expect(isFamilyClientMessage({ t: "phone", ref: "r1", member: "m2", phone: "+12155550123" })).toBe(true);
    expect(isFamilyClientMessage({ t: "phone", ref: "r1", member: "m2", phone: "" })).toBe(true);
    expect(isFamilyClientMessage({ t: "phone", ref: "r1", member: "m2", phone: "215-555-0123" })).toBe(false);
  });
});
