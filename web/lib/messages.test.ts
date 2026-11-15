import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { parseServerMessage, type ClientMessage } from "./messages";

const web = join(__dirname, "..", "..", "contract", "web", "samples");
const robot = join(__dirname, "..", "..", "contract", "samples");
const read = (dir: string, name: string) => readFileSync(join(dir, name), "utf8");

describe("contract samples", () => {
  it("web tel.json parses as telemetry, angles in degrees", () => {
    expect(parseServerMessage(read(web, "tel.json"))).toEqual({
      t: "tel", pitch: 5.71, rate: -1.8, vl: 0, vr: 0, batt: null, state: "balance", fault: null,
      x: 0.012, yaw: 0.4, ack: 814,
    });
  });

  it.each(["tel-idle.json", "tel-balance.json", "tel-drive.json", "tel-fell.json"])(
    "the robot's %s parses", (name) => {
      expect(parseServerMessage(read(robot, name))?.t).toBe("tel");
    });

  it("status.json parses", () => {
    expect(parseServerMessage(read(web, "status.json"))).toEqual({
      t: "status", follow: false, link: true, estop: false,
      settings: { mode: "person", speed: 0.25, distance: 0.45, voice: true }, lag_ms: 27.4, skill: null,
      vision: { mode: "server", status: "running", camera: { frames: 120, age_s: 0.08 } },
      trim_shift: -8.75, listening: false,
      // #79 fields the sample doesn't carry: their defaults
      drift: false, drift_rate: null, autostart: { waiting: false, note: "" }, calibrating: false,
      phone: false, family: 0, agent: false,
    });
  });

  it("estop.json has the shape the page sends", () => {
    const msg = JSON.parse(read(web, "estop.json")) as ClientMessage;
    expect(msg).toEqual({ t: "estop", on: true });
  });
});

describe("parseServerMessage", () => {
  it("keeps a fault string", () => {
    const raw = '{"t":"tel","pitch":0,"rate":0,"vl":0,"vr":0,"batt":null,"state":"idle","fault":"fell over"}';
    expect(parseServerMessage(raw)?.t === "tel" && parseServerMessage(raw)).toMatchObject({ fault: "fell over" });
  });

  it.each([
    ["not JSON", "{nope"],
    ["an array", "[1,2]"],
    ["an unknown type", '{"t":"sees","people":[]}'],
    ["a missing field", '{"t":"tel","pitch":1,"rate":0,"vl":0,"vr":0,"state":"balance","fault":null}'],
    ["a string number", '{"t":"tel","pitch":"1","rate":0,"vl":0,"vr":0,"batt":12,"state":"balance","fault":null}'],
    ["status without settings", '{"t":"status","follow":false,"link":true,"estop":false}'],
  ])("returns null for %s", (_label, raw) => {
    expect(parseServerMessage(raw)).toBeNull();
  });
});

describe("agent events and memory", () => {
  it("parses an agent event and a memory view", () => {
    expect(parseServerMessage('{"t":"agent","id":4,"kind":"say","text":"On it!","to":"senior","data":{}}')).toEqual({
      t: "agent", id: 4, kind: "say", text: "On it!", to: "senior", data: {},
    });
    const mem = parseServerMessage(
      '{"t":"memory","on":true,"people":["Mom"],"places":[{"name":"water station","marker":3,"aliases":["water"],"description":""}],' +
        '"facts":[{"key":"evening pills","value":"blue bottle","source":"agent"}]}',
    );
    expect(mem).toEqual({
      t: "memory", on: true, people: ["Mom"],
      places: [{ name: "water station", marker: 3, aliases: ["water"], description: "" }],
      facts: [{ key: "evening pills", value: "blue bottle", source: "agent" }],
    });
    expect(parseServerMessage('{"t":"agent","kind":"say"}')).toBeNull();
  });
});
