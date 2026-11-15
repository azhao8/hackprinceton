// Every sound-worthy moment on the video's clock, for the full showcase and each feature clip:
// taps, swipes, the handoff light, the right phone waking, delivery steps, the call connecting,
// scene changes and Miguel's lines. tools/synth_audio.py turns these into the mix.
//
//   npx tsx tools/export_events.ts      → public/audio/events-<mix>.json
import { mkdirSync, writeFileSync } from "node:fs";
import demo from "../capture/demo-timing.json";
import { SCENES as SCRIPTS } from "../capture/scenes.mjs";
import narration from "../src/narration.json";
import { RIGHT_DELAY, SCENES, place, type Scene } from "../src/timeline";

type Ev = { t: number; kind: string; pan?: number; dur?: number; id?: string };

function events(scenes: Scene[]) {
  const { placed, duration } = place(scenes);
  const ev: Ev[] = [{ t: 0.04, kind: "open" }];
  const voice: { t: number; id: string }[] = [];
  placed.forEach((p, i) => {
    const s = p.scene;
    const S = p.start;
    const script = SCRIPTS.find((x: { id: string }) => x.id === s.id)!;
    if (i > 0) ev.push({ t: S, kind: "scene" });
    const taps = script.steps.filter((x: { tap?: unknown }) => x.tap);
    let k = 0;
    for (const touch of s.left.touches) {
      if (touch.kind === "swipe") {
        ev.push({ t: S + touch.t0, kind: "swipe", pan: -0.35, dur: touch.t1 - touch.t0 });
        continue;
      }
      const step = taps[k++];
      const kind = step?.handoff ? "send" : step?.nav ? "nav" : "select";
      ev.push({ t: S + touch.t0, kind, pan: -0.35 });
    }
    for (const touch of s.right.touches) ev.push({ t: S + touch.t0 + RIGHT_DELAY, kind: "swipe", pan: 0.35, dur: touch.t1 - touch.t0 });
    const H = S + s.handoff;
    ev.push({ t: H, kind: "handoff" });
    const R = H + RIGHT_DELAY;
    ev.push({ t: R, kind: "wake", pan: 0.35 });
    if (s.id === "send") {
      ev.push({ t: R + demo.loading / 1000, kind: "step", pan: 0.35 });
      ev.push({ t: R + demo.onTheWay / 1000, kind: "step", pan: 0.35 });
      ev.push({ t: R + demo.delivered / 1000, kind: "delivered", pan: 0.3 });
    }
    if (s.id === "checkin") ev.push({ t: R + demo.checkInAnswer / 1000, kind: "connect", pan: 0.3 });
    for (const line of narration.lines) if (line.scene === s.id) voice.push({ t: S + line.at, id: line.id });
  });
  return { duration, scenes: placed.map((p) => ({ id: p.scene.id, start: p.start, end: p.start + p.scene.duration })), events: ev.sort((a, b) => a.t - b.t), voice };
}

mkdirSync("public/audio", { recursive: true });
const mixes: [string, Scene[]][] = [["mix", SCENES], ...SCENES.map((s) => [`mix-${s.id}`, [s]] as [string, Scene[]])];
for (const [name, scenes] of mixes) {
  const e = events(scenes);
  writeFileSync(`public/audio/events-${name}.json`, JSON.stringify(e, null, 1));
  console.log(`${name}: ${e.duration.toFixed(2)} s, ${e.events.length} sounds, ${e.voice.length} lines`);
}
