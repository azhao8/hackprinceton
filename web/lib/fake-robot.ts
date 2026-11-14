// A stand-in robot that runs in the browser, so the dashboard has sample
// telemetry before the server and the mock robot exist. It is not a physics
// model: pitch wobbles like a balancing robot and the wheels wander between
// a few cruise speeds.

import type { ClientMessage, Telemetry } from "./messages";

const TRACK_WIDTH_M = 0.2;
const MAX_ACCEL = 0.6; // m/s^2, how fast wheel speed moves toward its target
const CRUISE_SPEEDS: Array<[v: number, w: number]> = [
  [0, 0],
  [0.25, 0],
  [0.25, 0.6],
  [0.15, -0.8],
  [0.35, 0],
];
const SEGMENT_S = 3;
const LEAN_TIME_S = 0.15;

/** Small seeded PRNG (mulberry32) so tests are repeatable. */
function makeRandom(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function approach(current: number, target: number, maxStep: number): number {
  if (Math.abs(target - current) <= maxStep) return target;
  return current + Math.sign(target - current) * maxStep;
}

export class FakeRobot {
  private time = 0;
  private vl = 0;
  private vr = 0;
  private pitch = 0;
  private lean = 0;
  private batt = 12.4;
  private estop = false;
  private readonly random: () => number;

  constructor(seed = 1) {
    this.random = makeRandom(seed);
  }

  /** Handle a message the dashboard would send to the server. */
  receive(msg: ClientMessage): void {
    if (msg.t === "estop") this.estop = msg.on;
  }

  get estopped(): boolean {
    return this.estop;
  }

  /** Advance by dt seconds and return the next telemetry message. */
  step(dt: number): Telemetry {
    this.time += dt;

    const [v, w] = this.estop
      ? [0, 0]
      : CRUISE_SPEEDS[Math.floor(this.time / SEGMENT_S) % CRUISE_SPEEDS.length];
    const targetVl = v - (w * TRACK_WIDTH_M) / 2;
    const targetVr = v + (w * TRACK_WIDTH_M) / 2;
    const prevVl = this.vl;
    const prevVr = this.vr;
    this.vl = approach(this.vl, targetVl, MAX_ACCEL * dt);
    this.vr = approach(this.vr, targetVr, MAX_ACCEL * dt);

    // Lean into acceleration (smoothed), plus a balancing wobble. Sensor noise
    // goes on the reported pitch only, so the rate stays readable.
    const accel = (this.vl + this.vr - prevVl - prevVr) / 2 / Math.max(dt, 1e-6);
    this.lean += (4 * accel - this.lean) * Math.min(1, dt / LEAN_TIME_S);
    const wobble = 0.8 * Math.sin(2 * Math.PI * 0.7 * this.time);
    const prevPitch = this.pitch;
    this.pitch = this.lean + wobble;
    const rate = (this.pitch - prevPitch) / Math.max(dt, 1e-6);
    const noise = (this.random() - 0.5) * 0.3;

    this.batt = Math.max(10.8, this.batt - 0.0004 * dt);
    const moving = Math.abs(this.vl) + Math.abs(this.vr) > 0.01;

    // Modeled in degrees for readability; sent in radians like the real robot.
    return {
      t: "tel",
      pitch: round(((this.pitch + noise) * Math.PI) / 180, 4),
      rate: round((rate * Math.PI) / 180, 4),
      vl: round(this.vl, 3),
      vr: round(this.vr, 3),
      batt: round(this.batt, 2),
      state: moving ? "drive" : "balance",
      fault: null,
    };
  }
}

function round(value: number, digits: number): number {
  const f = 10 ** digits;
  return Math.round(value * f) / f;
}
