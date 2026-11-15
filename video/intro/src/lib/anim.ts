// Small deterministic animation toolkit: easing, keyframe tracks, oscillators, noise.

export const clamp = (v: number, a = 0, b = 1) => Math.min(b, Math.max(a, v));
export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
export const invLerp = (a: number, b: number, v: number) => clamp((v - a) / (b - a));
export const smoothstep = (t: number) => t * t * (3 - 2 * t);

export type Ease = (t: number) => number;
export const linear: Ease = (t) => t;
export const easeInCubic: Ease = (t) => t * t * t;
export const easeOutCubic: Ease = (t) => 1 - Math.pow(1 - t, 3);
export const easeInOutCubic: Ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
export const easeOutQuint: Ease = (t) => 1 - Math.pow(1 - t, 5);
export const easeOutExpo: Ease = (t) => (t >= 1 ? 1 : 1 - Math.pow(2, -10 * t));
export const easeInQuad: Ease = (t) => t * t;
export const easeInOutSine: Ease = (t) => -(Math.cos(Math.PI * t) - 1) / 2;
export const easeOutBack = (s = 1.4): Ease => (t) => 1 + (s + 1) * Math.pow(t - 1, 3) + s * Math.pow(t - 1, 2);

/** CSS-style cubic-bezier easing. */
export const bezier = (x1: number, y1: number, x2: number, y2: number): Ease => {
  const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx;
  const cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
  const sx = (t: number) => ((ax * t + bx) * t + cx) * t;
  const sy = (t: number) => ((ay * t + by) * t + cy) * t;
  const dx = (t: number) => (3 * ax * t + 2 * bx) * t + cx;
  return (x: number) => {
    if (x <= 0) return 0;
    if (x >= 1) return 1;
    let t = x;
    for (let i = 0; i < 8; i++) {
      const e = sx(t) - x;
      const d = dx(t);
      if (Math.abs(e) < 1e-6 || Math.abs(d) < 1e-6) break;
      t -= e / d;
    }
    return sy(clamp(t));
  };
};
/** The house curve for reveals: fast out, long soft landing. */
export const easeReveal = bezier(0.16, 1, 0.3, 1);
export const easeExit = bezier(0.7, 0, 0.84, 0);

export type Key = [time: number, value: number, ease?: Ease];
/** Piecewise keyframe track. Each key's ease shapes the segment that ends at it. */
export const track = (t: number, keys: Key[]): number => {
  if (t <= keys[0][0]) return keys[0][1];
  for (let i = 1; i < keys.length; i++) {
    const [t1, v1, e] = keys[i];
    if (t <= t1) {
      const [t0, v0] = keys[i - 1];
      const u = (t - t0) / (t1 - t0 || 1);
      return lerp(v0, v1, (e ?? easeInOutCubic)(u));
    }
  }
  return keys[keys.length - 1][1];
};

/** Window helper: 0 before a, 1 after b, eased between. */
export const ramp = (t: number, a: number, b: number, e: Ease = easeInOutCubic) => e(invLerp(a, b, t));

/** Damped oscillation that starts at t0 (value 0 at t0). */
export const ring = (t: number, t0: number, amp: number, freq: number, decay: number) =>
  t < t0 ? 0 : amp * Math.exp(-decay * (t - t0)) * Math.sin(2 * Math.PI * freq * (t - t0));

// Deterministic value noise (1D) -----------------------------------------------------------------
const hash = (n: number) => {
  const s = Math.sin(n * 127.1 + 311.7) * 43758.5453123;
  return s - Math.floor(s);
};
export const noise1 = (x: number, seed = 0) => {
  const i = Math.floor(x), f = x - i;
  const a = hash(i + seed * 101.3) * 2 - 1, b = hash(i + 1 + seed * 101.3) * 2 - 1;
  return lerp(a, b, smoothstep(f));
};
/** Two-octave smooth noise in [-1, 1]. */
export const fbm = (x: number, seed = 0) => 0.7 * noise1(x, seed) + 0.3 * noise1(x * 2.3 + 17.1, seed + 7);
