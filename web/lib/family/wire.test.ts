import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { isFamilyClientMessage, makeRef, parseFamilyServerMessage } from "./wire";

const dir = join(__dirname, "..", "..", "..", "contract", "web", "samples", "family");
const read = (name: string) => readFileSync(join(dir, name), "utf8");

// Which way each sample goes (contract/web/family.md).
const SERVER = [
  "welcome",
  "state-with-mom",
  "state-delivering",
  "state-check-in",
  "state-alert",
  "events",
  "event",
  "routines",
  "circle",
  "pace",
  "ack",
  "error",
  "rtc-answer",
  "frame",
];
const CLIENT = ["hello", "send", "check-in-request", "rtc-offer", "talk", "alert-handled", "routine", "invite"];

describe("contract/web/samples/family", () => {
  it("has a direction for every sample file", () => {
    const files = readdirSync(dir).map((f) => f.replace(/\.json$/, ""));
    expect([...files].sort()).toEqual([...SERVER, ...CLIENT].sort());
  });

  it.each(SERVER)("%s.json parses as a server message", (name) => {
    const raw = read(`${name}.json`);
    const msg = parseFamilyServerMessage(raw);
    expect(msg).not.toBeNull();
    expect(msg?.t).toBe(JSON.parse(raw).t);
  });

  it.each(CLIENT)("%s.json is a valid app message", (name) => {
    expect(isFamilyClientMessage(JSON.parse(read(`${name}.json`)))).toBe(true);
  });
});

describe("parseFamilyServerMessage", () => {
  const state = JSON.parse(read("state-with-mom.json"));

  it.each([
    ["not JSON", "{nope"],
    ["an unknown type", '{"t":"weather","sky":"blue"}'],
    ["an unknown mode", JSON.stringify({ ...state, mode: "dancing" })],
    ["a time without its UTC offset", JSON.stringify({ ...state, since: "2026-11-14T16:02:00" })],
    ["a live check-in without a start", JSON.stringify({ ...state, check_in: { phase: "live", id: "c1" } })],
    ["a delivery with an unknown stage", JSON.stringify({ ...state, delivery: { id: "d1", item: "water", label: "Water", stage: "lost" } })],
  ])("drops %s", (_label, raw) => {
    expect(parseFamilyServerMessage(raw)).toBeNull();
  });

  it("keeps an alert's details", () => {
    const msg = parseFamilyServerMessage(read("state-alert.json"));
    expect(msg?.t === "state" && msg.alert?.heard).toBe("I slipped. My hip hurts.");
  });
});

describe("isFamilyClientMessage", () => {
  it("rejects requests missing what the server needs", () => {
    expect(isFamilyClientMessage({ t: "hello", v: 1, viewer: "m1" })).toBe(false); // no token
    expect(isFamilyClientMessage({ t: "send", ref: "r1", item: "cake", label: "Cake" })).toBe(false);
    expect(isFamilyClientMessage({ t: "alert", ref: "r1", id: "a1", action: "ignore" })).toBe(false);
    expect(isFamilyClientMessage({ t: "rtc", call: "c1" })).toBe(false); // neither sdp nor candidate
  });

  it("makes request refs", () => {
    expect(makeRef(1731618840000, 3)).toBe("r-1731618840-3");
  });
});
