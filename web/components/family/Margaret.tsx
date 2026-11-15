"use client";

// Margaret, as an illustrated portrait for the check-in view: white hair, round glasses,
// her yellow cardigan, her armchair at home. She blinks and, while "talking", her mouth moves.
// With `greet`, she raises her arm and waves once, from the shoulder and elbow, as the call connects.

import { useEffect, useState } from "react";

/** The wave: her arm comes up from her side, waves from the elbow, goes back down (seconds). */
const WAVE = { delay: 0.35, up: 0.45, waving: 1.65, down: 0.5, hz: 2.2 };

/**
 * Joint angles in degrees, measured from straight down (0) toward her left (90, screen right)
 * and up (180). At rest the arm hangs inside her cardigan, so it's hidden behind her torso.
 */
const REST = { upper: -6, fore: -25 };
// raised: elbow down and a little out from her side, forearm up, hand by her cheek
const RAISED = { upper: 56, fore: 166 };

export interface ArmPose {
  upper: number;
  fore: number;
  wrist: number;
  /** 0 at rest (nothing to draw), 1 raised. */
  lift: number;
}

const easeInOut = (x: number) =>
  x < 0.5 ? 4 * x * x * x : 1 - (-2 * x + 2) ** 3 / 2;
const clamp01 = (x: number) => Math.min(1, Math.max(0, x));
const mix = (a: number, b: number, u: number) => a + (b - a) * u;

/** The arm's pose `t` seconds after the call connects. */
export function wavePose(t: number): ArmPose {
  const u = t - WAVE.delay;
  const end = WAVE.up + WAVE.waving + WAVE.down;
  if (u <= 0 || u >= end)
    return { upper: REST.upper, fore: REST.fore, wrist: 0, lift: 0 };
  const lift =
    u < WAVE.up
      ? u / WAVE.up
      : u < WAVE.up + WAVE.waving
        ? 1
        : 1 - (u - WAVE.up - WAVE.waving) / WAVE.down;
  // the hand comes up first, close to her side, then the elbow lifts out; the reverse going down
  const foreU = easeInOut(clamp01(lift * 1.35));
  const elbowU = easeInOut(clamp01(lift * 1.3 - 0.3));
  const w = u - WAVE.up * 0.7;
  const amp =
    clamp01(w / 0.3) *
    clamp01((WAVE.up + WAVE.waving + WAVE.down * 0.3 - u) / 0.35);
  const ph = w * 2 * Math.PI * WAVE.hz;
  return {
    upper: mix(REST.upper, RAISED.upper, elbowU) + 2 * Math.sin(ph - 0.8) * amp,
    fore: mix(REST.fore, RAISED.fore, foreU) + 11 * Math.sin(ph) * amp,
    wrist: 8 * Math.sin(ph - 0.6) * amp,
    lift: Math.max(elbowU, foreU),
  };
}

function useWave(greet: boolean): ArmPose {
  const [arm, setArm] = useState<ArmPose>(wavePose(0));
  useEffect(() => {
    if (!greet) return;
    let raf = 0;
    const t0 = performance.now();
    const loop = () => {
      const t = (performance.now() - t0) / 1000;
      setArm(wavePose(t));
      if (t < WAVE.delay + WAVE.up + WAVE.waving + WAVE.down + 0.05)
        raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [greet]);
  return arm;
}

const SHOULDER = { x: 189, y: 290 };
const UPPER = 50;
const FORE = 47;
const dir = (deg: number) => ({
  x: Math.sin((deg * Math.PI) / 180),
  y: Math.cos((deg * Math.PI) / 180),
});

/** Her right arm in her cardigan sleeve: shoulder (hidden behind her torso), elbow, cuff, hand. */
function WavingArm({ pose }: { pose: ArmPose }) {
  const d1 = dir(pose.upper);
  const d2 = dir(pose.fore);
  const e = { x: SHOULDER.x + d1.x * UPPER, y: SHOULDER.y + d1.y * UPPER };
  const w = { x: e.x + d2.x * FORE, y: e.y + d2.y * FORE };
  const c0 = { x: w.x - d2.x * 8, y: w.y - d2.y * 8 };
  const upper = `M${SHOULDER.x} ${SHOULDER.y}L${e.x} ${e.y}`;
  const fore = `M${e.x} ${e.y}L${w.x} ${w.y}`;
  // the hand is drawn upright with its wrist at (238, 236); turn it to follow the forearm
  const handTurn = 180 - pose.fore + pose.wrist;
  return (
    <g strokeLinecap="round" strokeLinejoin="round" fill="none">
      {/* both outlines first, then both fills, so the elbow reads as one bent sleeve; the forearm tapers */}
      <path d={upper} stroke="#2a2630" strokeWidth={26} />
      <path d={fore} stroke="#2a2630" strokeWidth={22.5} />
      <path d={upper} stroke="#f6c445" strokeWidth={21.5} />
      <path d={fore} stroke="#f6c445" strokeWidth={18} />
      <path
        d={`M${c0.x} ${c0.y}L${w.x} ${w.y}`}
        stroke="#2a2630"
        strokeWidth={22}
        strokeLinecap="butt"
      />
      <path
        d={`M${c0.x} ${c0.y}L${w.x} ${w.y}`}
        stroke="#fffaf0"
        strokeWidth={17.5}
        strokeLinecap="butt"
      />
      <g
        transform={`translate(${w.x + d2.x * 1.5} ${w.y + d2.y * 1.5}) rotate(${handTurn}) translate(-238 -236)`}
      >
        <path
          d="M231.5 233c-3.5-6-4.5-15-2.5-23 .9-3.6 5.6-3.4 6 .4l.6 5.4c-.3-6.6.3-12.4 1.6-15.6 1.4-3.4 6-2.8 6.2 1l.2 13.4c.4-5.6 1.5-10.4 3-12.6 1.9-2.8 6-1.6 5.9 1.8l-.5 13c1.2-3 2.6-5 4.1-5.6 2.6-1 4.6 1.4 3.7 4.2-1.8 5.6-3.6 11.4-6.6 16.8-2.4 4.2-6.6 6-11.2 6-4.4 0-8.2-2-10.5-5.8z"
          fill="#f2c9a8"
          stroke="#2a2630"
          strokeWidth="2.3"
        />
      </g>
    </g>
  );
}

export function Margaret({
  talking = false,
  greet = false,
  className = "",
}: {
  talking?: boolean;
  greet?: boolean;
  className?: string;
}) {
  const [blink, setBlink] = useState(false);
  const [mouth, setMouth] = useState(0);
  const arm = useWave(greet);

  useEffect(() => {
    let alive = true;
    let t: ReturnType<typeof setTimeout>;
    const loop = () => {
      t = setTimeout(
        () => {
          if (!alive) return;
          setBlink(true);
          setTimeout(() => alive && setBlink(false), 150);
          loop();
        },
        2400 + Math.random() * 2600,
      );
    };
    loop();
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, []);

  useEffect(() => {
    if (!talking) return;
    const id = setInterval(() => setMouth(Math.random()), 110);
    return () => {
      clearInterval(id);
      setMouth(0);
    };
  }, [talking]);

  const open = talking ? 1.5 + mouth * 5 : 0;

  return (
    <svg
      viewBox="0 0 300 360"
      className={className}
      role="img"
      aria-label="Margaret, in her armchair at home"
    >
      {/* Room */}
      <rect width="300" height="360" fill="#f3e6c9" />
      <rect
        x="168"
        y="34"
        width="104"
        height="132"
        rx="6"
        fill="#dde7f4"
        stroke="#2a2630"
        strokeWidth="2.5"
      />
      <path d="M220 34v132M168 100h104" stroke="#2a2630" strokeWidth="2.5" />
      <path
        d="M176 152c18-14 34-6 52-20s34-2 40-12v42h-92z"
        fill="#bcd2ea"
        opacity="0.8"
      />
      {/* Plant */}
      <path
        d="M44 256h40l-6 44H50z"
        fill="#ef9468"
        stroke="#2a2630"
        strokeWidth="2.5"
        strokeLinejoin="round"
      />
      <path
        d="M64 256c-4-30-26-42-34-62 18 6 30 22 34 40 2-24 12-46 30-56-4 22-14 40-22 58"
        fill="#7fb07e"
        stroke="#2a2630"
        strokeWidth="2.5"
        strokeLinejoin="round"
      />

      {/* Armchair */}
      <g transform="translate(1.5 2)" fill="#ef9468">
        <path d="M62 200c0-40 30-66 88-66s88 26 88 66v120H62z" />
      </g>
      <path
        d="M62 200c0-40 30-66 88-66s88 26 88 66v120H62z"
        fill="#e9a07a"
        stroke="#2a2630"
        strokeWidth="2.5"
      />

      <path
        d="M48 238c0-14 22-16 26 0v82H48zM226 238c4-16 26-14 26 0v82h-26z"
        fill="#e9a07a"
        stroke="#2a2630"
        strokeWidth="2.5"
      />

      {/* Her waving arm: in front of the armrest, behind her torso so the sleeve comes out of her cardigan */}
      {arm.lift > 0 && <WavingArm pose={arm} />}

      {/* Body: blouse and yellow cardigan */}
      <path
        d="M88 360c0-64 26-104 62-104s62 40 62 104z"
        fill="#f6c445"
        stroke="#2a2630"
        strokeWidth="2.5"
      />
      <path
        d="M134 262l16 58 16-58c-6-4-11-6-16-6s-10 2-16 6z"
        fill="#fffaf0"
        stroke="#2a2630"
        strokeWidth="2.5"
        strokeLinejoin="round"
      />
      <path d="M150 320v40" stroke="#2a2630" strokeWidth="2" />
      <circle cx="150" cy="332" r="2.4" fill="#2a2630" />
      <circle cx="150" cy="348" r="2.4" fill="#2a2630" />

      {/* Neck: starts up behind the face, so the head sits on it */}
      <path
        d="M137 204h26v58c-4 6-22 6-26 0z"
        fill="#f0c4a2"
        stroke="#2a2630"
        strokeWidth="2.5"
      />
      {/* Soft shadow under the chin */}
      <path
        d="M138.3 222h23.4v13c-7 6-16.4 6-23.4 0z"
        fill="#dfae8c"
        transform="translate(0 9)"
      />

      {/* Head: sits 9 units down on her neck, so the neck reads short */}
      <g transform="translate(0 9)">
        {/* Hair back */}
        <path
          d="M100 172c-8-50 22-82 50-82s58 32 50 82c-4 22-14 30-22 34H122c-8-4-18-12-22-34z"
          fill="#f4f0ea"
          stroke="#2a2630"
          strokeWidth="2.5"
        />
        {/* Face */}
        <ellipse
          cx="150"
          cy="182"
          rx="40"
          ry="46"
          fill="#f2c9a8"
          stroke="#2a2630"
          strokeWidth="2.5"
        />
        {/* Hair front: soft curls and a bun */}
        <path
          d="M110 162c-2-26 18-48 40-48s42 22 40 48c-8-10-18-14-26-12 2-8-2-14-6-16-6 8-18 14-34 14-6 4-10 10-14 14z"
          fill="#f8f5f0"
          stroke="#2a2630"
          strokeWidth="2.5"
          strokeLinejoin="round"
        />
        <circle
          cx="150"
          cy="96"
          r="18"
          fill="#f8f5f0"
          stroke="#2a2630"
          strokeWidth="2.5"
        />
        <path
          d="M140 92c4-4 10-6 16-2"
          fill="none"
          stroke="#2a2630"
          strokeWidth="1.8"
          strokeLinecap="round"
          opacity="0.5"
        />
        {/* Ears */}
        <path
          d="M110 186c-8-2-10 12-2 16"
          fill="#f2c9a8"
          stroke="#2a2630"
          strokeWidth="2.5"
        />
        <path
          d="M190 186c8-2 10 12 2 16"
          fill="#f2c9a8"
          stroke="#2a2630"
          strokeWidth="2.5"
        />
        {/* Cheeks */}
        <ellipse
          cx="124"
          cy="202"
          rx="9"
          ry="5.5"
          fill="#f0a39a"
          opacity="0.6"
        />
        <ellipse
          cx="176"
          cy="202"
          rx="9"
          ry="5.5"
          fill="#f0a39a"
          opacity="0.6"
        />
        {/* Eyes */}
        {blink ? (
          <path
            d="M127 186h12M161 186h12"
            stroke="#2a2630"
            strokeWidth="2.6"
            strokeLinecap="round"
          />
        ) : (
          <>
            <ellipse cx="133" cy="186" rx="3.6" ry="4.4" fill="#2a2630" />
            <ellipse cx="167" cy="186" rx="3.6" ry="4.4" fill="#2a2630" />
          </>
        )}
        {/* Glasses */}
        <g fill="none" stroke="#2a2630" strokeWidth="2.4">
          <circle cx="133" cy="186" r="13" />
          <circle cx="167" cy="186" r="13" />
          <path
            d="M146 185c2.6-2 5.4-2 8 0M120 184l-9-3M180 184l9-3"
            strokeLinecap="round"
          />
        </g>
        {/* Brows */}
        <path
          d="M124 166c5-3 11-3 16 0M160 166c5-3 11-3 16 0"
          fill="none"
          stroke="#c9c2b8"
          strokeWidth="3"
          strokeLinecap="round"
        />
        {/* Nose */}
        <path
          d="M150 192c-2 6-4 9-1 10"
          fill="none"
          stroke="#2a2630"
          strokeWidth="2"
          strokeLinecap="round"
          opacity="0.7"
        />
        {/* Mouth */}
        {open > 0 ? (
          <path
            d={`M138 210c4 ${2 + open} 20 ${2 + open} 24 0c-4 ${-1} -20 ${-1} -24 0z`}
            fill="#8a3f3a"
            stroke="#2a2630"
            strokeWidth="2"
            strokeLinejoin="round"
          />
        ) : (
          <path
            d="M137 209c6 7 20 7 26 0"
            fill="none"
            stroke="#2a2630"
            strokeWidth="2.6"
            strokeLinecap="round"
          />
        )}
        {/* Pearl earrings */}
        <circle
          cx="108"
          cy="204"
          r="3"
          fill="#fffaf0"
          stroke="#2a2630"
          strokeWidth="1.6"
        />
        <circle
          cx="192"
          cy="204"
          r="3"
          fill="#fffaf0"
          stroke="#2a2630"
          strokeWidth="1.6"
        />
      </g>
    </svg>
  );
}
