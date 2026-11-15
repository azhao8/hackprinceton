// An iPhone 15 Pro–sized device (393 × 852 pt) showing captured frames of the real app below an
// opaque status bar, with the Dynamic Island, the home indicator, and touch marks.
import type { CSSProperties, ReactNode } from "react";
import { Img, staticFile } from "remotion";
import { clamp, easeOut, ramp, type Touch } from "./timeline";

export const PT = 868 / 852; // video px per iPhone point
export const BEZEL = 11;
export const SCREEN = { w: 393 * PT, h: 852 * PT };
export const OUTER = { w: SCREEN.w + 2 * BEZEL, h: SCREEN.h + 2 * BEZEL };
const STATUS = 59;
const RADIUS = 55 * PT;
const PAPER = "#f7f2e8";
const INK = "#2a2630";

export interface ScreenLayer {
  key: string;
  opacity: number;
  /** A captured frame (path under public/), or the standby screen. */
  src: string | "standby";
  touches: { touch: Touch; t: number }[];
  clock: string;
}

function StatusBar({ clock }: { clock: string }) {
  return (
    <div style={{ position: "absolute", left: 0, top: 0, width: 393, height: STATUS, background: PAPER }}>
      <div
        style={{
          position: "absolute",
          left: 0,
          width: 134,
          top: 20,
          textAlign: "center",
          font: "600 17px Figtree, sans-serif",
          letterSpacing: "-0.01em",
          color: INK,
        }}
      >
        {clock}
      </div>
      <svg width={80} height={14} viewBox="0 0 80 14" style={{ position: "absolute", left: 289, top: 23 }}>
        {[4, 6.3, 8.6, 11].map((h, i) => (
          <rect key={i} x={i * 4.8} y={12 - h} width={3.2} height={h} rx={0.9} fill={INK} />
        ))}
        <g transform="translate(26 1.4)" fill={INK}>
          <path d="M8 2.2c2.6 0 5 1 6.8 2.6l1.2-1.3C13.9 1.6 11.1.5 8 .5S2.1 1.6 0 3.5l1.2 1.3C3 3.2 5.4 2.2 8 2.2z" />
          <path d="M8 5.6c1.7 0 3.2.6 4.4 1.7l1.2-1.3C12.1 4.6 10.1 3.9 8 3.9S3.9 4.6 2.4 6l1.2 1.3C4.8 6.2 6.3 5.6 8 5.6z" />
          <path d="M8 9c.8 0 1.5.3 2 .8L8 11.9 6 9.8c.5-.5 1.2-.8 2-.8z" />
        </g>
        <g transform="translate(47 1)">
          <rect x={0.5} y={0.5} width={24} height={11.5} rx={3.6} fill="none" stroke={INK} strokeOpacity={0.4} />
          <rect x={2.2} y={2.2} width={17.5} height={8.1} rx={2.1} fill={INK} />
          <path d="M26.2 4.3v4c.8-.3 1.3-1.1 1.3-2s-.5-1.7-1.3-2z" fill={INK} fillOpacity={0.45} />
        </g>
      </svg>
    </div>
  );
}

/** The right phone before anything happens: asleep, dark glass. */
function Standby() {
  return <div style={{ position: "absolute", inset: 0, background: "linear-gradient(160deg, #1b1918 0%, #0b0a0a 55%, #131111 100%)" }} />;
}

/** A finger: lands, presses, lifts with a ring; or drags up as the page scrolls. */
function TouchMark({ touch, t }: { touch: Touch; t: number }) {
  const R = 23;
  if (touch.kind === "tap") {
    const appear = ramp(t, touch.t0 - 0.12, touch.t0);
    const lift = ramp(t, touch.t1, touch.t1 + 0.26);
    if (appear <= 0 || lift >= 1) return null;
    const scale = (1.3 - 0.3 * easeOut(appear)) * (t >= touch.t0 && t < touch.t1 ? 0.9 : 1);
    const core = appear * (1 - easeOut(lift));
    const y = STATUS + (touch.y ?? 0);
    return (
      <>
        <div style={dot(touch.x, y, R * scale, core)} />
        {lift > 0 && <div style={ring(touch.x, y, R * (1 + 0.8 * easeOut(lift)), 0.85 * (1 - lift))} />}
      </>
    );
  }
  // swipe: the finger travels up to 250 pt with the page, lifting before the glide ends
  const dur = touch.t1 - touch.t0;
  const appear = ramp(t, touch.t0 - 0.1, touch.t0);
  const travelU = easeOut(ramp(t, touch.t0, touch.t0 + 0.55 * dur));
  const fade = ramp(t, touch.t0 + 0.45 * dur, touch.t0 + 0.7 * dur);
  if (appear <= 0 || fade >= 1) return null;
  const dist = Math.min(250, Math.abs((touch.to ?? 0) - (touch.from ?? 0))) * Math.sign((touch.to ?? 0) - (touch.from ?? 0));
  const y = STATUS + 560 - dist * travelU;
  return <div style={dot(touch.x, y, R * (1.25 - 0.25 * easeOut(appear)), appear * (1 - fade))} />;
}

const dot = (x: number, y: number, r: number, o: number): CSSProperties => ({
  position: "absolute",
  left: x - r,
  top: y - r,
  width: 2 * r,
  height: 2 * r,
  borderRadius: "50%",
  background: "rgba(42, 38, 48, 0.2)",
  border: "2.5px solid rgba(255, 255, 255, 0.95)",
  boxShadow: "0 0 0 1px rgba(42, 38, 48, 0.28), 0 3px 10px rgba(42, 38, 48, 0.25)",
  opacity: clamp(o),
});
const ring = (x: number, y: number, r: number, o: number): CSSProperties => ({
  position: "absolute",
  left: x - r,
  top: y - r,
  width: 2 * r,
  height: 2 * r,
  borderRadius: "50%",
  border: "2px solid rgba(255, 255, 255, 0.95)",
  boxShadow: "0 0 0 1px rgba(42, 38, 48, 0.2)",
  opacity: clamp(o),
});

const button = (side: "left" | "right", top: number, h: number): CSSProperties => ({
  position: "absolute",
  [side]: -3,
  top,
  width: 5,
  height: h,
  borderRadius: 2,
  background: "linear-gradient(90deg, #2a2725, #4a4643 50%, #2a2725)",
});

export function Phone({
  x,
  y,
  scale,
  dim,
  glow,
  layers,
  awake = 1,
  children,
}: {
  x: number;
  y: number;
  scale: number;
  /** 0: lit, 1: fully dimmed. */
  dim: number;
  /** 0–1 warm light behind the phone. */
  glow: number;
  layers: ScreenLayer[];
  /** 0 hides the home indicator (screen asleep). */
  awake?: number;
  children?: ReactNode;
}) {
  return (
    <div style={{ position: "absolute", left: x, top: y, width: OUTER.w, height: OUTER.h, transform: `scale(${scale})`, transformOrigin: "50% 50%" }}>
      <div
        style={{
          position: "absolute",
          left: "50%",
          top: "50%",
          width: OUTER.w * 1.9,
          height: OUTER.h * 1.25,
          transform: "translate(-50%, -50%)",
          background: "radial-gradient(closest-side, rgba(255, 196, 140, 0.13), rgba(255, 196, 140, 0.04) 55%, rgba(255, 196, 140, 0))",
          opacity: glow,
        }}
      />
      <div style={button("left", 150, 30)} />
      <div style={button("left", 210, 58)} />
      <div style={button("left", 282, 58)} />
      <div style={button("right", 238, 92)} />
      <div
        style={{
          position: "absolute",
          inset: 0,
          borderRadius: RADIUS + BEZEL,
          background: "linear-gradient(155deg, #57514c 0%, #2b2826 18%, #191716 50%, #2f2b29 85%, #4b4642 100%)",
          boxShadow: "0 50px 90px -20px rgba(0,0,0,0.75), 0 0 0 1px rgba(0,0,0,0.9), inset 0 0 0 1px rgba(255,255,255,0.14)",
        }}
      />
      <div style={{ position: "absolute", inset: 2.6, borderRadius: RADIUS + BEZEL - 2.6, background: "#050505" }} />
      <div
        style={{
          position: "absolute",
          left: BEZEL,
          top: BEZEL,
          width: SCREEN.w,
          height: SCREEN.h,
          borderRadius: RADIUS,
          overflow: "hidden",
          background: PAPER,
        }}
      >
        <div style={{ position: "absolute", left: 0, top: 0, width: 393, height: 852, transform: `scale(${PT})`, transformOrigin: "0 0" }}>
          {layers.map((l) => (
            <div key={l.key} style={{ position: "absolute", inset: 0, opacity: l.opacity }}>
              {l.src === "standby" ? (
                <Standby />
              ) : (
                <>
                  <Img src={staticFile(l.src)} style={{ position: "absolute", left: 0, top: STATUS, width: 393, height: 852 - STATUS }} />
                  <StatusBar clock={l.clock} />
                </>
              )}
              {l.touches.map((tt, i) => (
                <TouchMark key={i} touch={tt.touch} t={tt.t} />
              ))}
            </div>
          ))}
          {/* Dynamic Island and home indicator */}
          <div style={{ position: "absolute", left: (393 - 125) / 2, top: 11, width: 125, height: 37, borderRadius: 19, background: "#000" }} />
          <div style={{ position: "absolute", left: (393 - 139) / 2, bottom: 8, width: 139, height: 5, borderRadius: 3, background: INK, opacity: 0.88 * awake }} />
        </div>
        <div style={{ position: "absolute", inset: 0, background: "#0c0a09", opacity: 0.5 * dim }} />
        <div
          style={{
            position: "absolute",
            inset: 0,
            borderRadius: RADIUS,
            boxShadow: "inset 0 0 0 1px rgba(0,0,0,0.25)",
            background: "linear-gradient(125deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0) 35%)",
          }}
        />
      </div>
      {children}
    </div>
  );
}
