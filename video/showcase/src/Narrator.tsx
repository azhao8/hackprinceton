// Miguel narrating, Loom-style: a circle in the top-left corner with Miguel himself (the
// intro's 3D model, rebuilt from the sticker) talking in sync with Corey's voice. His mouth follows
// the phonemes and loudness of each line (tools/lipsync.py); between lines it rests in a smile.
// He blinks, nods a little as he speaks, glances at the phones when something happens there, and
// a thin amber ring follows his voice.
import { useEffect, useMemo, useRef } from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";
import lipsync from "./lipsync.json";
import { NEUTRAL_FACE, type FaceState } from "./miguel/face";
import { buildMiguel } from "./miguel/miguel3d";
import { Stage } from "./miguel/stage";
import { RIGHT_DELAY, clamp, easeInOut, easeOut, ramp, type Placed } from "./timeline";

export const BUBBLE = { d: 210, left: 54, top: 42 };
const SCALE = 300; // Miguel's height in world units

interface Track {
  id: string;
  scene: string;
  at: number;
  seconds: number;
  open: number[];
  round: number[];
  wide: number[];
  level: number[];
}
const HZ = lipsync.hz;
const TRACKS = lipsync.lines as unknown as Track[];

/** Each narration line placed on the video's clock. */
export function placedLines(placed: Placed[]) {
  return TRACKS.flatMap((line) => {
    const p = placed.find((x) => x.scene.id === line.scene);
    return p ? [{ line, start: p.start + line.at }] : [];
  });
}

const sample = (arr: number[], i: number) => {
  const k = Math.floor(i);
  const f = i - k;
  const a = arr[Math.max(0, Math.min(arr.length - 1, k))] ?? 0;
  const b = arr[Math.max(0, Math.min(arr.length - 1, k + 1))] ?? 0;
  return a + (b - a) * f;
};

/** Mouth and voice level at time T (seconds on the video's clock). */
export function voiceAt(lines: ReturnType<typeof placedLines>, T: number) {
  for (const { line, start } of lines) {
    const u = T - start;
    if (u >= 0 && u <= line.seconds) {
      const i = u * HZ;
      return { open: sample(line.open, i), round: sample(line.round, i), wide: sample(line.wide, i), level: sample(line.level, i), id: line.id };
    }
  }
  return { open: 0, round: 0, wide: 0, level: 0, id: null as string | null };
}

const hash = (n: number) => {
  const s = Math.sin(n * 127.1 + 311.7) * 43758.5453123;
  return s - Math.floor(s);
};

/** Blinks every 2.9–4.3 s, plus one as each scene starts. */
function blinkAt(T: number, sceneStarts: number[]) {
  const times: number[] = [];
  let t = 1.1;
  for (let i = 0; t < T + 1; i++) {
    times.push(t);
    t += 2.9 + 1.4 * hash(i);
  }
  times.push(...sceneStarts.map((s) => s + 0.12));
  let b = 0;
  for (const t0 of times) {
    const u = T - t0;
    if (u >= 0 && u < 0.17) b = Math.max(b, Math.sin((u / 0.17) * Math.PI));
  }
  return b;
}

export const Narrator: React.FC<{ placed: Placed[]; opacity: number }> = ({ placed, opacity }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const T = frame / fps;
  const ref = useRef<HTMLCanvasElement>(null);
  const lines = useMemo(() => placedLines(placed), [placed]);

  const world = useMemo(() => {
    const stage = new Stage(BUBBLE.d, BUBBLE.d, 3, 2.1);
    stage.setOutline(2.1, 5);
    const miguel = buildMiguel(SCALE);
    stage.scene.add(miguel.root);
    const cam = stage.camera;
    cam.fov = 30;
    cam.near = 10;
    cam.far = 5000;
    // head and shoulders, like a webcam bubble: the gold phone on top, his face below it, a level camera
    cam.position.set(0, 0.79 * SCALE, 0.74 * SCALE);
    cam.lookAt(0, 0.778 * SCALE, 0);
    cam.updateProjectionMatrix();
    stage.render(); // warm-up: the first render after creating a WebGL context can come back empty
    return { stage, miguel };
  }, []);

  // what's happening in the scenes: handoffs (he glances at the phones), happy moments
  const moments = useMemo(() => {
    const glances: number[] = [];
    const happy: [number, number][] = [];
    for (const p of placed) {
      const H = p.start + p.scene.handoff;
      glances.push(H - 0.05);
      if (p.scene.rightLabelAfter) {
        const t = H + RIGHT_DELAY + p.scene.rightLabelAfter.t;
        happy.push([t, t + 1.7]);
      }
    }
    const last = lines[lines.length - 1];
    if (last && last.line.id === "n9") happy.push([last.start + 0.1, 1e9]);
    return { glances, happy, sceneStarts: placed.slice(1).map((p) => p.start) };
  }, [placed, lines]);

  const v = voiceAt(lines, T);
  // a slightly slower level for the ring and the nods
  const ringLevel = Math.max(...[0, 0.05, 0.1, 0.15].map((d) => voiceAt(lines, T - d).level * (1 - d * 2)));

  useEffect(() => {
    const { stage, miguel } = world;
    const look = Math.max(0, ...moments.glances.map((g) => easeInOut(ramp(T, g, g + 0.25)) * (1 - easeInOut(ramp(T, g + 1.25, g + 1.6)))));
    const happy = Math.max(0, ...moments.happy.map(([a, b]) => easeOut(ramp(T, a, a + 0.2)) * (1 - easeOut(ramp(T, b, b + 0.3)))));
    const face: FaceState = {
      ...NEUTRAL_FACE,
      lookX: 0.85 * look + 0.12 * Math.sin(T * 0.7),
      lookY: 0.2 * look - 0.06,
      blink: blinkAt(T, moments.sceneStarts),
      eyeOpen: 1 + 0.06 * v.level,
      happy: happy * (v.open > 0.05 ? 0.6 : 1),
      smile: 1.08 + 0.2 * happy,
      mouthOpen: clamp(v.open * 1.9),
      round: v.round,
      wide: v.wide,
    };
    miguel.setPose({
      x: 0,
      z: 0,
      yaw: 0.1 + 0.2 * look + 0.035 * Math.sin(T * 2 * Math.PI * 0.11),
      pitch: 0.004 * Math.sin(T * 2 * Math.PI * 0.45),
      headTilt: 0.035 * Math.sin(T * 2 * Math.PI * 0.17 + 1) + 0.03 * ringLevel * Math.sin(T * 2 * Math.PI * 0.9),
      headNod: -0.05 * ringLevel + 0.012 * Math.sin(T * 2 * Math.PI * 0.23),
      wheelL: 0,
      wheelR: 0,
      face,
      cable: { swayX: 0.003 * Math.sin(T * 2.1), swayZ: 0.002 * Math.sin(T * 1.7) },
    });
    stage.render();
    const ctx = ref.current!.getContext("2d")!;
    ctx.clearRect(0, 0, ref.current!.width, ref.current!.height);
    ctx.drawImage(stage.canvas, 0, 0, ref.current!.width, ref.current!.height);
  }, [T, world, moments, v.open, v.round, v.wide, v.level, ringLevel]);

  const D = BUBBLE.d;
  const ring = ringLevel;
  return (
    <div style={{ position: "absolute", left: BUBBLE.left, top: BUBBLE.top, width: D, height: D, opacity }}>
      {/* the speaking ring */}
      <div
        style={{
          position: "absolute",
          inset: -9 - 3 * ring,
          borderRadius: "50%",
          border: `${2.5 + 1.5 * ring}px solid rgba(240, 178, 90, ${0.12 + 0.7 * ring})`,
          boxShadow: `0 0 ${14 + 22 * ring}px rgba(240, 178, 90, ${0.22 * ring})`,
        }}
      />
      <div
        style={{
          position: "absolute",
          inset: 0,
          borderRadius: "50%",
          overflow: "hidden",
          background: "radial-gradient(circle at 50% 38%, #fbf6ec 0%, #f3e9d8 55%, #e3d3b8 100%)",
          boxShadow: "0 0 0 4px #f4ecdd, 0 18px 44px rgba(0,0,0,0.55)",
        }}
      >
        <canvas ref={ref} width={D * 3} height={D * 3} style={{ width: D, height: D, display: "block" }} />
      </div>
    </div>
  );
};
