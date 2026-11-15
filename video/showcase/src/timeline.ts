// The showcase's timing: the captured scenes laid end to end with short crossfades, and the small
// easing helpers the layers share.
import checkin from "../public/capture/checkin.json";
import day from "../public/capture/day.json";
import send from "../public/capture/send.json";
import summary from "../public/capture/summary.json";

export interface Touch {
  kind: "tap" | "swipe";
  t0: number;
  t1: number;
  x: number;
  y?: number;
  from?: number;
  to?: number;
}

export interface Run {
  frames: number;
  /** Scene seconds of this run's first frame (the right phone starts at the handoff). */
  start: number;
  touches: Touch[];
  /** Status-bar time, from the app's demo clock. */
  clock: string;
}

export interface Scene {
  id: string;
  eyebrow: string;
  title: string;
  labels: { left: [string, string]; right: [string, string] };
  rightLabelAfter: { t: number; label: string } | null;
  duration: number;
  handoff: number;
  phone: { width: number; height: number; statusBar: number; safeBottom: number };
  view: { width: number; height: number };
  left: Run;
  right: Run;
}

export const SCENES = [day, send, checkin, summary] as unknown as Scene[];
export const FPS = 60;

/** Before the first scene, the crossfade between scenes, and the hold + fade at the end (s). */
export const LEAD = 0.3;
export const XFADE = 0.6;
export const TAIL = 1.2;
/** The right phone answers a beat after the tap, as the light reaches it, and wakes this fast (s). */
export const RIGHT_DELAY = 0.25;
export const WAKE = 0.22;

export interface Placed {
  scene: Scene;
  index: number;
  start: number;
}

export function place(scenes: Scene[]): { placed: Placed[]; duration: number } {
  const placed: Placed[] = [];
  let t = LEAD;
  scenes.forEach((scene, i) => {
    placed.push({ scene, index: SCENES.indexOf(scene), start: t });
    t += scene.duration - (i < scenes.length - 1 ? XFADE : 0);
  });
  return { placed, duration: t + TAIL };
}

export const clamp = (x: number, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, x));
export const ramp = (t: number, a: number, b: number) => clamp((t - a) / (b - a));
export const easeInOut = (u: number) => (u < 0.5 ? 4 * u * u * u : 1 - (-2 * u + 2) ** 3 / 2);
export const easeOut = (u: number) => 1 - (1 - u) ** 3;
export const lerp = (a: number, b: number, u: number) => a + (b - a) * u;
