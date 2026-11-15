// The two-phone showcase. Left phone: where you act. Right phone: what happens. One phone is lit
// at a time; the light moves to the right phone the moment the action is made.
import { AbsoluteFill, Audio, staticFile, useCurrentFrame } from "remotion";
import { Narrator } from "./Narrator";
import { BEZEL, OUTER, PT, Phone, type ScreenLayer } from "./Phone";
import { FPS, LEAD, RIGHT_DELAY, SCENES, TAIL, WAKE, XFADE, clamp, easeInOut, easeOut, lerp, place, ramp, type Placed, type Run, type Scene } from "./timeline";

const W = 1920;
const GAP = 132;
const TOP = 168;
const LEFT_X = (W - (2 * OUTER.w + GAP)) / 2;
const RIGHT_X = LEFT_X + OUTER.w + GAP;
const CREAM = "#f4ecdd";
const AMBER = "#f0b25a";

const pad = (n: number) => String(n).padStart(6, "0");
const frameOf = (run: Run, t: number) => clamp(Math.round((t - run.start) * FPS), 0, run.frames - 1);

/** How present a scene is at its local time t: fades in over the crossfade (not the first), out at the end (not the last). */
function presence(p: Placed, t: number, first: boolean, last: boolean) {
  const inW = first ? 1 : ramp(t, 0, XFADE);
  const outW = last ? 1 : 1 - ramp(t, p.scene.duration - XFADE, p.scene.duration);
  return Math.min(inW, outW);
}

/** 1 while the left phone is the one to watch, 0 once the action has been made. */
const leftActive = (s: Scene, t: number) => 1 - easeInOut(ramp(t, s.handoff, s.handoff + 0.4));

function Heading({ scene, t, first, last, T, total }: { scene: Scene; t: number; first: boolean; last: boolean; T: number; total: number }) {
  const inU = first ? easeOut(ramp(T, 0.05, 0.5)) : easeOut(ramp(t, XFADE * 0.5, XFADE));
  const outU = last ? 0 : easeInOut(ramp(t, scene.duration - XFADE, scene.duration - XFADE + 0.28));
  const o = inU * (1 - outU);
  if (o <= 0) return null;
  const dy = (1 - inU) * 14 - outU * 10;
  void total;
  return (
    <div style={{ position: "absolute", left: 0, right: 0, top: 44, textAlign: "center", opacity: o, transform: `translateY(${dy}px)` }}>
      <div style={{ font: "500 15px 'DM Mono', monospace", letterSpacing: "0.24em", textTransform: "uppercase", color: AMBER }}>
        {String(SCENES.indexOf(scene) + 1).padStart(2, "0")} <span style={{ opacity: 0.55, margin: "0 0.5em" }}>—</span> {scene.eyebrow}
      </div>
      <div style={{ marginTop: 14, font: "500 50px Literata, Georgia, serif", letterSpacing: "-0.015em", color: CREAM }}>{scene.title}</div>
    </div>
  );
}

function Flank({ side, title, caption, opacity, swap }: { side: "left" | "right"; title: string; caption: string; opacity: number; swap?: { title: string; u: number } }) {
  if (opacity <= 0) return null;
  const x = side === "left" ? LEFT_X - 52 : RIGHT_X + OUTER.w + 52;
  const titleStyle = { font: "500 14px 'DM Mono', monospace", letterSpacing: "0.22em", textTransform: "uppercase" as const, color: AMBER };
  return (
    <div
      style={{
        position: "absolute",
        top: 470,
        width: 300,
        left: side === "left" ? x - 300 : x,
        textAlign: side === "left" ? "right" : "left",
        opacity,
      }}
    >
      <div style={{ position: "relative", height: 18 }}>
        <div style={{ ...titleStyle, position: "absolute", inset: 0, opacity: 1 - (swap?.u ?? 0) }}>{title}</div>
        {swap && <div style={{ ...titleStyle, position: "absolute", inset: 0, opacity: swap.u }}>{swap.title}</div>}
      </div>
      <div style={{ marginTop: 14, height: 1, width: 44, background: AMBER, opacity: 0.45, marginLeft: side === "left" ? "auto" : 0 }} />
      <div style={{ marginTop: 14, font: "400 25px/1.3 Literata, Georgia, serif", color: CREAM, opacity: 0.86 }}>{caption}</div>
    </div>
  );
}

/** A point on the left phone's screen (points, below the status bar) in video px. */
function onLeft(x: number, y: number, phoneY: number, scale: number) {
  const lx = BEZEL + x * PT;
  const ly = BEZEL + (59 + y) * PT;
  return { X: LEFT_X + OUTER.w / 2 + (lx - OUTER.w / 2) * scale, Y: phoneY + OUTER.h / 2 + (ly - OUTER.h / 2) * scale };
}

/** The tap's light, carried from the left phone over to the right one, which wakes as it arrives. */
function Spark({ x, y, u, o, phoneY, leftScale, rightScale }: { x: number; y: number; u: number; o: number; phoneY: number; leftScale: number; rightScale: number }) {
  if (u <= 0 || u >= 1) return null;
  const a = onLeft(x, y, phoneY, leftScale);
  const b = { X: RIGHT_X + OUTER.w * (0.5 - 0.36 * rightScale), Y: phoneY + OUTER.h * 0.42 };
  const c = { X: (a.X + b.X) / 2, Y: Math.min(a.Y, b.Y) - 120 };
  const e = easeInOut(u);
  const L = 0.32;
  const at = (k: number) => ({
    X: (1 - k) ** 2 * a.X + 2 * (1 - k) * k * c.X + k * k * b.X,
    Y: (1 - k) ** 2 * a.Y + 2 * (1 - k) * k * c.Y + k * k * b.Y,
  });
  const head = at(e);
  const alpha = o * Math.min(1, u / 0.12) * (1 - ramp(u, 0.78, 1));
  return (
    <svg width={1920} height={1080} style={{ position: "absolute", inset: 0, opacity: alpha }}>
      <defs>
        <radialGradient id="spark">
          <stop offset="0" stopColor="#fff6e6" />
          <stop offset="0.35" stopColor="#f0b25a" stopOpacity="0.9" />
          <stop offset="1" stopColor="#f0b25a" stopOpacity="0" />
        </radialGradient>
      </defs>
      <path
        d={`M${a.X} ${a.Y} Q${c.X} ${c.Y} ${b.X} ${b.Y}`}
        pathLength={1}
        fill="none"
        stroke="#f0b25a"
        strokeOpacity={0.55}
        strokeWidth={2.2}
        strokeLinecap="round"
        strokeDasharray={`${L} 2`}
        strokeDashoffset={L - e}
      />
      <circle cx={head.X} cy={head.Y} r={16} fill="url(#spark)" />
    </svg>
  );
}

export const Showcase: React.FC<{ only?: string; audio?: string | null }> = ({ only, audio }) => {
  const frame = useCurrentFrame();
  const T = frame / FPS;
  const scenes = only ? SCENES.filter((s) => s.id === only) : SCENES;
  const { placed, duration } = place(scenes);
  const lastIdx = placed.length - 1;

  const leftLayers: ScreenLayer[] = [];
  const rightLayers: ScreenLayer[] = [];
  let active = 1; // left
  let awake = 0; // right phone's screen
  const sparks: { key: string; x: number; y: number; u: number; o: number }[] = [];
  const headings: React.ReactNode[] = [];
  const flanks: React.ReactNode[] = [];
  let seen = 0;

  placed.forEach((p, i) => {
    const s = p.scene;
    const t = T - p.start;
    const first = i === 0;
    const last = i === lastIdx;
    if (t < (first ? -LEAD - 1 : 0) || t > s.duration + (last ? TAIL + 1 : 0)) return;
    const w = presence(p, t, first, last);
    if (w <= 0) return;
    const incoming = seen > 0; // a second visible scene is the one fading in
    seen += 1;
    // Screens change through a moment of blank paper (left) or dark glass (right), never a
    // double exposure: the old screen clears in the first half of the crossfade, the new one
    // comes in during the second.
    const leaving = last ? 0 : easeInOut(ramp(t, s.duration - XFADE, s.duration - XFADE / 2));
    const leftOpacity = incoming ? easeInOut(ramp(t, XFADE / 2, XFADE)) : 1 - leaving;
    const layerOpacity = incoming ? easeInOut(w) : 1;

    leftLayers.push({
      key: `${s.id}-l`,
      opacity: leftOpacity,
      src: `capture/${s.id}/left/${pad(frameOf(s.left, t))}.jpg`,
      touches: s.left.touches.map((touch) => ({ touch, t })),
      clock: s.left.clock,
    });
    const tr = t - RIGHT_DELAY;
    const standby = 1 - easeInOut(ramp(tr, s.handoff, s.handoff + WAKE));
    if (tr >= s.handoff) {
      rightLayers.push({
        key: `${s.id}-r`,
        opacity: layerOpacity,
        src: `capture/${s.id}/right/${pad(frameOf(s.right, tr))}.jpg`,
        touches: s.right.touches.map((touch) => ({ touch, t: tr })),
        clock: s.right.clock,
      });
    }
    if (standby > 0) rightLayers.push({ key: `${s.id}-s`, opacity: layerOpacity * standby, src: "standby", touches: [], clock: "" });
    awake = incoming ? lerp(awake, 1 - standby, easeInOut(w)) : 1 - standby;
    const tap = s.left.touches.find((x) => x.kind === "tap" && Math.abs(x.t1 - s.handoff) < 0.05);
    if (tap) sparks.push({ key: s.id, x: tap.x, y: tap.y ?? 0, u: ramp(t, s.handoff - 0.02, s.handoff + RIGHT_DELAY + 0.08), o: layerOpacity });

    const a = leftActive(s, t);
    active = incoming ? lerp(active, a, easeInOut(w)) : a;

    headings.push(<Heading key={s.id} scene={s} t={t} first={first} last={last} T={T} total={duration} />);
    const textIn = first ? easeOut(ramp(T, 0.15, 0.6)) : easeOut(ramp(t, XFADE * 0.5, XFADE + 0.05));
    const textOut = last ? 0 : easeInOut(ramp(t, s.duration - XFADE, s.duration - XFADE + 0.28));
    const tw = textIn * (1 - textOut);
    const rightIn = easeOut(ramp(tr, s.handoff + 0.05, s.handoff + 0.4));
    const swap = s.rightLabelAfter ? { title: s.rightLabelAfter.label, u: easeInOut(ramp(tr, s.handoff + s.rightLabelAfter.t, s.handoff + s.rightLabelAfter.t + 0.35)) } : undefined;
    flanks.push(<Flank key={`${s.id}-fl`} side="left" title={s.labels.left[0]} caption={s.labels.left[1]} opacity={tw * (0.32 + 0.68 * a)} />);
    flanks.push(
      <Flank key={`${s.id}-fr`} side="right" title={s.labels.right[0]} caption={s.labels.right[1]} opacity={tw * rightIn * (0.32 + 0.68 * (1 - a))} swap={swap} />,
    );
  });

  // the phones rise in at the start; everything fades out at the end
  const intro = easeOut(ramp(T, 0, 0.42));
  const outro = 1 - easeInOut(ramp(T, duration - 0.8, duration - 0.02));
  const bg = Math.min(ramp(T, 0, 0.25), outro);
  const phoneY = TOP + (1 - intro) * 36;
  const leftScale = 0.955 + 0.045 * active;
  const rightScale = 0.955 + 0.045 * (1 - active);

  return (
    <AbsoluteFill style={{ background: "#000" }}>
      {audio && <Audio src={staticFile(audio)} />}
      <AbsoluteFill style={{ opacity: bg }}>
        <AbsoluteFill style={{ background: "radial-gradient(ellipse 70% 62% at 50% 60%, #1f1813 0%, #120e0c 45%, #0a0808 100%)" }} />
      </AbsoluteFill>
      <AbsoluteFill style={{ opacity: Math.min(intro, outro) }}>
        <Phone x={LEFT_X} y={phoneY} scale={leftScale} dim={1 - active} glow={active} layers={leftLayers} />
        <Phone x={RIGHT_X} y={phoneY} scale={rightScale} dim={active * awake} glow={(1 - active) * awake} layers={rightLayers} awake={awake} />
        {sparks.map((sp) => (
          <Spark key={sp.key} x={sp.x} y={sp.y} u={sp.u} o={sp.o} phoneY={phoneY} leftScale={leftScale} rightScale={rightScale} />
        ))}
      </AbsoluteFill>
      <AbsoluteFill style={{ opacity: outro }}>
        {headings}
        {flanks}
        <div
          style={{
            position: "absolute",
            right: 40,
            bottom: 30,
            font: "400 12px 'DM Mono', monospace",
            letterSpacing: "0.16em",
            textTransform: "uppercase",
            color: CREAM,
            opacity: 0.32 * ramp(T, 0.5, 1.0),
          }}
        >
          Miguel family app · demo data
        </div>
        <Narrator placed={placed} opacity={easeOut(ramp(T, 0.1, 0.45))} />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const showcaseDuration = (only?: string) => place(only ? SCENES.filter((s) => s.id === only) : SCENES).duration;
