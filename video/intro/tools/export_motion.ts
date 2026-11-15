// Samples Miguel's motion so the sound design can follow it: npx tsx tools/export_motion.ts
import fs from "node:fs";
import opentype from "opentype.js";
import T from "../src/timeline.json";
import { buildChoreo3D } from "../src/scene/choreo3d";
import { computeWordLayout } from "../src/scene/layout";
import { project } from "../src/lib/camera";

const buf = fs.readFileSync(new URL("../public/fonts/outfit-latin-800-normal.woff", import.meta.url));
const font = opentype.parse(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength));
const layout = computeWordLayout(font as never);
const c = buildChoreo3D(layout.slotX);
const hz = 240;
const n = Math.ceil(T.duration * hz);
const w: number[] = [], x: number[] = [], pitch: number[] = [], roll: number[] = [], drop: number[] = [];
for (let i = 0; i < n; i++) {
  const t = i / hz;
  const m = c.motorAt(t);
  const p = c.pose(t);
  w.push(+m.w.toFixed(3));
  x.push(+project(p.x, 0, p.z).X.toFixed(1));
  pitch.push(+((p.pitch * 180) / Math.PI).toFixed(3));
  const li = c.letterI(t);
  roll.push(+li.roll.toFixed(3));
  drop.push(+li.drop.toFixed(1));
}
fs.writeFileSync(new URL("../public/audio/motion.json", import.meta.url), JSON.stringify({ hz, w, x, pitch, roll, drop, impactT: c.impactT, landT: c.landT }));
console.log("motion samples", n, "impact", c.impactT, "land", c.landT.toFixed(3), "slotX", layout.slotX.toFixed(1), "word", layout.left.toFixed(0), "→", layout.right.toFixed(0));
