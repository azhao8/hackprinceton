import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { parseServerMessage, type ClientMessage } from "./messages";

const samples = join(__dirname, "..", "..", "contract", "web", "samples");
const sample = (name: string) => readFileSync(join(samples, name), "utf8");

describe("contract/web samples", () => {
  it("tel.json parses as telemetry", () => {
    expect(parseServerMessage(sample("tel.json"))).toEqual({
      t: "tel",
      pitch: 0.021,
      rate: -0.007,
      vl: 0.28,
      vr: 0.31,
      batt: 11.6,
      state: "balance",
      fault: null,
    });
  });

  it("estop.json has the shape the dashboard sends", () => {
    const msg = JSON.parse(sample("estop.json")) as ClientMessage;
    expect(msg.t).toBe("estop");
    expect(typeof msg.on).toBe("boolean");
  });
});

describe("parseServerMessage", () => {
  it("keeps a fault string", () => {
    const raw = '{"t":"tel","pitch":0,"rate":0,"vl":0,"vr":0,"batt":10.9,"state":"idle","fault":"tilt"}';
    expect(parseServerMessage(raw)?.fault).toBe("tilt");
  });

  it.each([
    ["not JSON", "{nope"],
    ["an array", "[1,2]"],
    ["an unknown type", '{"t":"sees","people":[]}'],
    ["a missing field", '{"t":"tel","pitch":1,"rate":0,"vl":0,"vr":0,"state":"balance","fault":null}'],
    ["a string number", '{"t":"tel","pitch":"1","rate":0,"vl":0,"vr":0,"batt":12,"state":"balance","fault":null}'],
  ])("returns null for %s", (_label, raw) => {
    expect(parseServerMessage(raw)).toBeNull();
  });
});
